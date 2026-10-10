# How can we get weekly AH and Jumbo Deals?

Research for [issue #2](https://github.com/KianMeijers/Pickled/issues/2), part of the v1 architecture map (#1).
Researched 2026-10-10 (a Saturday). "Verified live" means I made the request myself on that date and saw the response.

## Answer in one line

**AH:** use the unofficial Appie mobile API (`api.ah.nl`). It needs an anonymous token and nothing else, and it returns structured Bonus data with valid-from/to dates, discount types and categories. Next week's Bonus is already published by Saturday. **Jumbo:** the old mobile API no longer responds. Parse the server-rendered Nuxt payload on `jumbo.com/aanbiedingen/nu` instead (one request), and fetch product pages when we need per-product prices. Neither store has an official API.

## Options considered

| Option | AH | Jumbo | Verdict |
|---|---|---|---|
| Official public API | None exists | None exists | n/a |
| Unofficial mobile-app API | `api.ah.nl` works with an anonymous token (verified live) | `mobileapi.jumbo.com` TLS handshake hangs, no response (verified live) | **AH: use this.** Jumbo: dead or blocked |
| Website (SSR payload / GraphQL) | Possible, but not needed | `jumbo.com/aanbiedingen/nu` returns 200 with all 164 current promotions in `__NUXT_DATA__` (verified live) | **Jumbo: use this** |
| Third-party aggregators | Checkjebon (regular prices only), paid Apify actors | Same | Don't use: no deal fields, or a paid and opaque middleman |

## Albert Heijn: Appie mobile API

### How it works

Primary source: [gwillem/appie-go](https://github.com/gwillem/appie-go) (Go, actively maintained, last commit 2026-09-23). Its `client.go`, `auth.go`, `bonus.go` and `doc/albertheijn_api.md` reverse-engineer the iOS app. I verified each step below live.

1. **Anonymous token:** `POST https://api.ah.nl/mobile-auth/v1/auth/token/anonymous` with body `{"clientId":"appie-ios"}`. This returned 200 with `access_token`, `refresh_token` and `expires_in: 604798` (about 7 days). No account is needed.
2. **Periods and categories:** `GET /mobile-services/bonuspage/v3/metadata` with `Authorization: Bearer …` and `x-application: AHWEBSHOP`. It returns `periods[]`, each with `bonusStartDate`/`bonusEndDate` and tabs listing categories, a `count` per category, and a `bonusType` (`NATIONAL`, `SPOTLIGHT`, `AHONLINE`, `GALL`, `ETOS`, …).
3. **Deals per category:** `GET /mobile-services/bonuspage/v2/section?application=AHWEBSHOP&date=<YYYY-MM-DD>&promotionType=NATIONAL&category=<category description>`. This returns `bonusGroupOrProducts[]`.
4. **Expanding groups (optional):** a group like "Alle Unox rookworsten" comes back with `products: []`. appie-go expands it into individual products with the GraphQL query `FetchBonusPromotionWithProducts`, which returns `bonusPromotions(id, periodStart, periodEnd)` with `salesUnitSize` and `priceV2.now/was` (`bonus.go`).

There are about 22 NATIONAL food and household categories, so a full week takes about 25 requests.

### Data shape (verified live, week 2026-10-12 to 2026-10-18, category "Vlees")

A Bonus group item looks like this:

```json
{"bonusGroup": {
  "id": "814121", "segmentDescription": "Alle AH Greenfields beefburgers 2 stuks",
  "bonusStartDate": "2026-10-12", "bonusEndDate": "2026-10-18",
  "validityPeriod": {"start": "2026-10-12", "end": "2026-10-18", "code": "FROM_WEEKDAY"},
  "discountDescription": "VOOR 2.49",
  "discountLabels": [{"code": "DISCOUNT_FIXED_PRICE", "defaultDescription": "voor 2.49", "price": 2.49}],
  "category": "Vlees", "promotionType": "NATIONAL", "storeOnlyPromotion": false,
  "products": [], "images": [...]}}
```

A single-product item has the product fields `title`, `currentPrice` (for example 2.99), `priceBeforeBonus` (9.49), `bonusMechanism` ("100 GRAM VOOR 2.99"), `unitPriceDescription` ("normale prijs per kg €36.50"), `mainCategory`, `subCategory`, `webshopId`, `bonusStartDate` and `bonusEndDate`.

| Field we need | Where it is |
|---|---|
| Product | `segmentDescription` (group) or `title` (product) |
| Price | `currentPrice`/`priceBeforeBonus` on products. Groups have only the deal text, so use the GraphQL expansion to get prices |
| Discount type | `discountLabels[].code`, seen as `DISCOUNT_FIXED_PRICE` and `DISCOUNT_PERCENTAGE` (with `percentage`), plus the human-readable `discountDescription`/`bonusMechanism` ("25% KORTING", "2e halve prijs", "100 GRAM VOOR 2.99") |
| Valid from/to | `bonusStartDate`/`bonusEndDate`, `validityPeriod` |
| Category | `category` (the AH Bonus category) |
| Unit size | Not in the section response. It is often embedded in the title ("2 stuks"). For an exact value, use GraphQL `salesUnitSize` or the product endpoint |

### Weekly schedule

AH Bonus weeks run **Monday to Sunday**. On Saturday 2026-10-10 the metadata returned two periods: `2026-10-05 → 2026-10-11` (current) and `2026-10-12 → 2026-10-18` (next). Next week's section data was fully fetchable, with `"future": true`. appie-go's `GetBonusPeriods` doc comment says next week appears "a few days before it starts". I observed it present on Saturday but did not determine the exact publication day.

### Reliability

- **Auth:** the anonymous token lasts about 7 days. It worked with no `User-Agent` set, though appie-go sends an Appie iOS UA, and copying it is prudent.
- **Rate limits:** unknown. The appie-go README says "AH does not send back-off headers, so the practical rate limit is unknown". About 25 requests a week is negligible.
- **Breakage:** endpoints are versioned and do get retired. `bonuspage/v1/metadata` and `v2/metadata` now return **500**, while `v3` works (verified live). [SupermarktConnector](https://github.com/bartmachielsen/SupermarktConnector) (last commit 2022-12, PyPI 2022-11) still calls `v1`, so its AH Bonus code is broken today. Expect to update the client every year or two. Keep the AH adapter small and watch appie-go's commits for endpoint changes.

### Legal / ToS (AH)

[AH Algemene Voorwaarden](https://www.ah.nl/algemene-voorwaarden):
- Part II (AH.nl), art. 14: publishing, reproducing or editing the information on the site without consent is not allowed, "behalve voor persoonlijk gebruik" (except for personal use).
- Part III (AH app), art. 1: "U mag de AH app niet deassembleren, decompileren of onderwerpen aan reverse engineering". Art. 4 contains the same personal-use exception as Part II.
- I found no explicit clause on scraping or bots.
- `ah.nl/robots.txt` does not touch `/bonus` (`api.ah.nl` is a separate host).

Assessment: for one household's private use, the personal-use exception covers reading the Bonus. Calling the API that open-source clients have already documented is a grey area under the anti-reverse-engineering clause, but Pickled itself decompiles nothing. Risk is low for private use. **Do not redistribute the data or publish a hosted service.**

### Python clients

- [`supermarktconnector`](https://pypi.org/project/supermarktconnector/) (PyPI, 2022): its AH Bonus code calls the retired `v1` and is **broken**.
- [`appie`](https://pypi.org/project/appie/) 0.0.7 (svdgraaf): old and minimal.
- [wmeints/happie](https://github.com/wmeints/happie): a Python MCP server for AH. It's tiny and not a library.
- The best reference is **appie-go** (Go). We should write our own thin `httpx` adapter (about 100 lines) based on it rather than depend on an unmaintained Python package.

## Jumbo

### Mobile API: dead or blocked

`mobileapi.jumbo.com/v17/...`, used by SupermarktConnector's `jumbo.py` (`jumbo_api_version = "v17"`), resolves to Akamai (23.42.166.246). The TLS handshake never completes, and every request timed out (verified live with a browser UA). SupermarktConnector issue #18 "new jumbo version api" (2022) is still open. [peter-mdf/python-jumbo-api](https://github.com/peter-mdf/python-jumbo-api) / PyPI `python-jumbo-api` 0.9.0 covers orders, time slots and basket only, not promotions.

### Website: the server-rendered offers page works

`GET https://www.jumbo.com/aanbiedingen/nu` with a browser `User-Agent` returned 200 and about 890 KB of HTML (verified live). The page is Nuxt. The `<script id="__NUXT_DATA__">` tag holds a devalue-encoded JSON array, which a 20-line resolver decodes. It contained **164 `Promotion` objects** (the current week plus longer-running ones):

```json
{"id": "3020898", "title": "Alle Calvé pindakaas", "subtitle": "…", "group": "Week",
 "start": {"iso": "2026-10-07T00:01:00+02:00"}, "end": {"iso": "2026-10-13T23:59:59+02:00"},
 "tags": [{"text": "2e halve prijs"}], "volumeDiscounts": [], "isKiesAndMix": false,
 "durationTexts": {"shortTitle": "wo 7 t/m di 13 okt"},
 "url": "/aanbiedingen/alle-calve-pindakaas/3020898", "image": "…"}
```

The promotion detail page (`/aanbiedingen/<slug>/<id>`) uses the same structure and lists its **products** (13 for this promotion): `sku`, `title`, `brand`, `category`, `subtitle` (unit size, e.g. "1000 g"), `price.price` and `price.promoPrice` in cents, `price.pricePerUnit {price, unit}`, and `promotions[].tags`.

The site runs on a GraphQL backend at `https://www.jumbo.com/api/graphql`, with headers `apollographql-client-name: JUMBO_WEB-…` and `x-source`. See [vghoost360/Jumbo-API](https://github.com/vghoost360/Jumbo-API) `app/jumbo_client.py` (Python, 2026-02), which queries `promotions { id tags durationTexts … }` on products. That client is aimed at logged-in basket and receipt use, and its query shapes are a useful reference if the HTML route breaks. I did not verify an anonymous promotions-list GraphQL query.

| Field we need | Where it is |
|---|---|
| Product | Promotion `title` + `subtitle`. Per-product `title` on the detail page |
| Price | Detail page `price.price`/`promoPrice` (cents). The overview has only the tag text |
| Discount type | `tags[].text` is free text ("1+1 gratis", "2 voor 2,99", "2e halve prijs"), plus `volumeDiscounts` and `isKiesAndMix`. **We must parse it ourselves**, because there is no enum like AH's `discountLabels.code` |
| Valid from/to | `start.iso`/`end.iso` (ISO 8601 with offset) |
| Category | Not on the promotion. Per-product `category` on the detail page |
| Unit size | Per-product `subtitle` on the detail page |

### Weekly schedule

Jumbo week deals (`group: "Week"`) run **Wednesday 00:01 to Tuesday 23:59** (observed: 2026-10-07 → 2026-10-13). This is offset from AH's Monday to Sunday. `/aanbiedingen/volgende-week` and `/aanbiedingen/binnenkort` both 301-redirect to `/aanbiedingen/nu`, so **next week's Jumbo deals were not visible on Saturday**. I could not determine whether they appear on Tuesday, or only through GraphQL with a date.

### Reliability

- Plain HTTP with a browser UA. No auth or cookies were needed, and there was no bot challenge on the request I made.
- Breakage risk is higher than AH's. Any change to the Nuxt/GraphQL structure breaks the parser: the page is on `master-v39.2.0-web` today, while vghoost360's client from February had `v29.2.0`. Keep the Jumbo adapter isolated and tested against a saved fixture.

### Legal / ToS (Jumbo)

[Jumbo Algemene Voorwaarden](https://www.jumbo.com/service/algemene-voorwaarden) (PDF dated 2026-05-19):
- Art. II-1 lists "databankrecht" among Jumbo's rights.
- Art. II-9.3(i) forbids retrieving and reusing "een substantieel gedeelte van de inhoud" and "niet-substantiële delen … herhaald en systematisch op te vragen".
- Art. II-9.3(ii) forbids using "robots of op enigerlei andere wijze te spideren, scrapen, doorzoeken".
- **There is no personal-use exception.**
- `jumbo.com/robots.txt` does not disallow `/aanbiedingen`.

Assessment: a weekly automated read is technically contrary to Jumbo's terms even for private use. Practical risk is low: one household, about 1 to 20 requests a week, no redistribution, comparable to a person browsing the page. Enforcement would realistically be an IP block, not legal action. This risk is the user's call. Flag it and keep request volume minimal.

## Third-party aggregators

- **[Checkjebon](https://github.com/supermarkt/checkjebon)** (MIT, updated daily): `data/supermarkets.json` (about 9.9 MB) has only `n` (name), `l` (link), `p` (price) and `s` (size) per product, for AH, Jumbo and 10 other chains. **No deal or discount fields**, so it doesn't answer this question. It might help later to look up regular prices.
- **Apify actors** (e.g. "Jumbo Scraper — Dutch Supermarket Prices & Promotions"): paid, opaque scrapers of the same sources. They add cost and a dependency without being more legitimate. Not recommended.
- **Folder sites** (reclamefolder.nl, folderz, etc.): publish images or PDFs of the leaflet, not structured data. Not worth OCR.

## Recommendation

1. **Build one `DealSource` port with two adapters**, `AhDealSource` and `JumboDealSource`, both normalising to the CONTEXT.md **Deal**: product description, store, deal text, parsed discount type, price/was-price when known, valid_from, valid_to, category, unit size when known.
2. **AH:** a thin `httpx` client against `api.ah.nl` that uses an anonymous token, `bonuspage/v3/metadata`, and `bonuspage/v2/section` per NATIONAL category. Skip group expansion in v1 (the deal text is enough for meal planning) and add it later through GraphQL if prices per product matter. Base it on appie-go rather than depending on `supermarktconnector`, whose AH Bonus code is broken.
3. **Jumbo:** fetch `jumbo.com/aanbiedingen/nu` and decode `__NUXT_DATA__` into Promotions (filter `group == "Week"` for the weekly deals). Fetch individual promotion pages only for the deals the planner actually picks, to keep the request count low.
4. **Fetch once and cache locally** (SQLite/JSON), keyed by store and validity period. Refresh AH from Saturday for the coming Monday to Sunday week, and refresh Jumbo on Wednesday. Planning a week therefore has to cope with **overlapping, offset deal windows**. A plan made on Saturday or Sunday sees next week's AH deals but only Jumbo deals that end on Tuesday.
5. **Guardrails:** browser or app UA, at most about 30 requests per store per week, no redistribution, and recorded fixtures plus a test per adapter, so a silent format change fails loudly.

## Open questions surfaced

- **Plan timing vs. offset weeks:** AH runs Monday to Sunday (next week visible by Saturday), Jumbo runs Wednesday to Tuesday (next week not visible on Saturday). When does the Household plan, and how should a Meal Plan treat a Jumbo Deal that expires mid-week?
- **Exact publication times:** at what day and hour does AH publish the next period, and does Jumbo expose next week's promotions anywhere (GraphQL with a date, on Tuesday)? This needs a few weeks of observation.
- **Jumbo ToS risk acceptance:** Jumbo's terms forbid scraping with no personal-use exception. Does the user accept this for a private tool?
- **Granularity:** is deal-level data ("Alle Unox rookworsten 25% korting") enough for planning, or do we need product-level prices and unit sizes, which cost extra requests (AH GraphQL, Jumbo detail pages)?
- **Discount-type vocabulary:** AH has codes (`DISCOUNT_FIXED_PRICE`, `DISCOUNT_PERCENTAGE`, …) and Jumbo has only free-text tags. We need one shared parsed vocabulary (x% off, fixed price, N for €X, 1+1, 2nd half price, …) to compare Deals.
- **Store-specific Deals:** AH Bonus can differ online vs. in store (`storeOnlyPromotion`, `AHONLINE`), and Jumbo applies delivery-date rules for online orders. Which channel does the Household shop in?
