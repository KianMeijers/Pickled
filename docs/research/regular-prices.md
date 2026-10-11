# Where do regular prices come from for the cost estimate?

Research for [issue #15](https://github.com/KianMeijers/Pickled/issues/15). It follows on from [ah-jumbo-deals.md](https://github.com/KianMeijers/Pickled/blob/research/ah-jumbo-deals/docs/research/ah-jumbo-deals.md) (issue #2) and works inside ADR 0005 ("Deals come from unofficial store endpoints, within a private-use budget").
Researched 2026-10-11 (a Sunday). "Verified live" means I made the request myself on that date and saw the response. In total I made 1 token request and 5 search requests to `api.ah.nl`, and 4 page requests to `jumbo.com`.

## Answer in one line

**Jumbo:** use Checkjebon's `supermarkets.json`. Its Jumbo prices are refreshed daily and matched the live site exactly for 30 of 30 products I checked, and reading it costs zero requests to Jumbo. **AH:** do *not* use Checkjebon. Its AH data has not changed since autumn 2025, and 29 of 54 sampled prices are wrong today. Use the Appie product search endpoint (`api.ah.nl/mobile-services/product/search/v2`) instead. It returns the regular price, unit size and price per kg for each product, at one request per ingredient term, cached in Postgres. Every AH Deal product we already fetch also carries `priceBeforeBonus`, which is a free regular-price observation.

## Options considered

| Option | AH | Jumbo | Store requests | Verdict |
|---|---|---|---|---|
| **Checkjebon** `data/supermarkets.json` (MIT) | 16,173 products, **frozen since Oct/Nov 2025**, 54% of sampled prices wrong | 17,081 products, refreshed daily, 30/30 sampled prices correct | 0 (one ~2.3 MB gzip download from GitHub) | **Jumbo: use.** AH: don't |
| **AH Appie product search** (`api.ah.nl`) | Regular price, unit size, price per kg, Bonus state. Up to 1,000 results per request | n/a | 1 per ingredient term | **AH: use**, cached |
| AH Bonus data we already fetch (#2) | `priceBeforeBonus` on every Deal product | n/a | 0 extra | **Use as a bonus source** |
| **Jumbo search page** (`jumbo.com/producten/?searchTerms=…`) | n/a | `price`, `promoPrice`, `pricePerUnit` in `__NUXT_DATA__` | 1 per ingredient term | Works, but scraping is against Jumbo's ToS and Checkjebon makes it unnecessary. Keep as a fallback |
| Jumbo GraphQL (`jumbo.com/api/graphql`) | n/a | Reference client is login-oriented | n/a | Not needed |
| Open Food Facts product DB | Unit size by barcode only, often empty | Same | n/a | Don't use: the stores already give the size |
| Open Food Facts **Open Prices** | ~106 crowd-sourced prices across 40 NL AH stores | ~68 across 19 NL Jumbo stores | n/a | Don't use: far too sparse |

## Checkjebon

### What it is

[supermarkt/checkjebon](https://github.com/supermarkt/checkjebon) is the open-data backend of checkjebon.nl, a shopping-list price comparer. Its README ("Open data") says the price data "is updated frequently and may be reused in other projects". The repo licence is MIT (GitHub API, verified live). A bot commits `data/supermarkets.json` once a day at around 05:00 UTC. The last five commits were on 2026-10-06, 08, 09, 10 and 11.

- **Size:** 10,088,950 bytes raw, 2,312,985 bytes when served gzipped from `raw.githubusercontent.com` (verified live). `cache-control: max-age=300`.
- **Shape:** a JSON array of 12 stores, each `{n, u, c, i, d}`, where `n` is the store key (`ah`, `jumbo`, …), `u` is the product URL prefix, and `d` is the product list. Each product is exactly `{n, l, p, s}`: name, link slug, price in euros (float), size (free text). There is **no** price per unit, no category, no EAN, no Deal flag and no timestamp.

```json
{"n": "AH Biologisch Kipfilet 2 stuks", "l": "wi57741/ah-biologisch-kipfilet-2-stuks", "p": 8.99, "s": "ca. 320 g"}
{"n": "Jumbo Kipfilet ca. 215 g", "l": "jumbo-kipfilet-ca-215-g-596629KGR", "p": 3.86, "s": ""}
```

The AH link contains the AH `webshopId` (`wi57741` → 57741). The Jumbo link ends in the Jumbo SKU (`596629KGR`). Both are stable keys for joining with the stores' own data.

### Freshness: AH is frozen, Jumbo is live (verified live)

I compared today's file with older commits of the same file, keyed by link:

| Compared with | AH: products changed | Jumbo: products with a changed price | Jumbo: added / removed |
|---|---|---|---|
| 2026-10-10 (yesterday) | 0 of 16,173 | 565 | 1,938 / 79 |
| 2026-10-04 | 0 | 961 | 365 / 280 |
| 2026-01-14 | 0 | 5,622 | 5,543 / 6,201 |
| 2025-11-13 | 0 | not checked | not checked |
| 2025-10-12 | 4,478 changed prices, 21,692 → 16,173 products | not checked | not checked |

**The AH section has been byte-for-byte identical since somewhere between 2025-10-12 and 2025-11-13.** Dirk, Hoogvliet, DekaMarkt, Lidl, Plus and Vomar are also unchanged since yesterday. Upstream issue [#24](https://github.com/supermarkt/checkjebon/issues/24) "Several shops' prices look stuck — Albert Heijn, Plus, Dirk, …" (opened 2026-09-15, no reply) reports the same. Issue [#20](https://github.com/supermarkt/checkjebon/issues/20) "AH products incomplete" (2025-12) has been open since then too.

### Accuracy against the live stores (verified live)

- **AH:** I sent 66 Checkjebon AH product IDs to AH's `search/v2/products?ids=…` endpoint (one request). 54 came back; the other 12 are presumably no longer sold. Of the 54, **25 matched** `priceBeforeBonus` and **29 differed**, typically by 3 to 20% in either direction. Examples: AH Kipfilet grootverpakking 250 g is €4.89 in Checkjebon vs €4.19 live; AH Runder hamburger 4 stuks is €5.49 vs €4.79; Mentos Gum is €4.69 vs €5.39. None of the differences matched the current Bonus price, so they are stale regular prices, not Deal prices.
- **Jumbo:** the 24 products with prices on the live `kipfilet` search page and 6 products on two promotion pages: **30 of 30 matched** Checkjebon exactly. Checkjebon matched `price.price` (the regular price) for products on a multi-buy Deal ("2 voor 5,00", "2 voor 4,99"). I did not find a product with a non-null `promoPrice`, so I could not check whether Checkjebon stores the promo price or the regular price for single-product discounts.

### Unit sizes

- **AH:** `s` is filled for all but 5 products and mostly has the form "300 g", "ca. 210 g", "1 l", "6 x 0,2 l", "4 stuks". 1,116 products are "per stuk" (mostly fresh produce sold by the piece), and some are recipe boxes ("2 pers | 30 min").
- **Jumbo:** `s` is **empty for 7,221 of 17,081 products**, but the size is usually at the end of the name ("Jumbo Kipfilet ca. 215 g"). A simple regex finds a size in `s` or the name for 94% of Jumbo products and 90% of AH products. Units are written inconsistently ("g", "G", "gram", "GRM", "Mililiters"), so they need normalising.

### Licence and ToS

The repo is MIT, and the README invites reuse. The data itself is scraped from the supermarkets by Checkjebon, so the supermarkets' database rights still exist in principle. Upstream issue [#16](https://github.com/supermarkt/checkjebon/issues/16) asks whether using it is legal; the only answer is from another user, not the maintainer. For Pickled, downloading a public MIT file from GitHub makes **zero requests to Jumbo**, which avoids the Jumbo scraping clause (art. II-9.3) for us directly. ADR 0005's rules still apply: we keep it private and don't redistribute it.

### Requests and matching

- **Refresh:** one HTTP GET to GitHub per refresh (daily or weekly), no store requests. Load the `jumbo` slice (~17k rows) into Postgres.
- **Matching:** name only. There is no search endpoint, category or EAN, so matching "400g kipfilet" is a local text search over product names (Postgres `pg_trgm` or full-text search, or an LLM picking from the top candidates). Checkjebon's own README describes its matching algorithm: exact name match, then a subsequence "fuzzy" match, filter out products smaller than the requested amount, prefer the shortest match, then the cheapest. Searching "kipfilet" today gives 66 Jumbo hits and 79 AH hits, from €1.99 sliced chicken to €11.80 for organic 400 g. So the hard part is choosing among candidates, not finding them.

## Albert Heijn: Appie product search

### How it works

Primary source: [gwillem/appie-go](https://github.com/gwillem/appie-go) `doc/albertheijn_api.md`, section "Search Products (REST)". The same anonymous token as for Deals (`POST /mobile-auth/v1/auth/token/anonymous`, `{"clientId":"appie-ios"}`, valid for about 7 days, verified live), with headers `Authorization: Bearer …` and `x-application: AHWEBSHOP`.

- `GET /mobile-services/product/search/v2?query=<term>&page=0&size=<n>&sortOn=RELEVANCE` (`sortOn` can also be `PRICE_ASC` or `PRICE_DESC`). Verified live: `query=kipfilet` returned 295 products. `size=1000` was accepted and returned all 295 in one response (886 KB).
- `GET /mobile-services/product/search/v2/products?ids=…&ids=…&sortOn=INPUT_PRODUCT_IDS` returns many known products at once. Verified live with 66 IDs in one request (166 KB).
- Searching with no `query` and `size=1000` returned 1,000 products, with `totalElements` capped at 10,000, plus a `taxonomy` facet listing 67 product types with counts (e.g. "Kip en gevogelte" 358, "Sauzen" 982). So pulling the whole assortment means splitting by `taxonomyId` and would need roughly 40 to 70 requests.

### Data shape (verified live, `query=kipfilet`)

Each product has about 50 fields. The useful ones:

| Field we need | Where it is |
|---|---|
| Product | `title`, `brand`, `webshopId`, `hqId`, `mainCategory`, `subCategory` |
| Regular price | `priceBeforeBonus` (euros). For a product not on Bonus, `currentPrice` is absent and `priceBeforeBonus` is the shelf price |
| Deal price | `currentPrice` when `isBonus` is true, plus `bonusMechanism`, `discountLabels`, `bonusStartDate`/`bonusEndDate` |
| Unit size | `salesUnitSize` ("300 g", "ca. 200 g", "4 stuks") |
| Price per unit | `unitPriceDescription`, a string: "prijs per kg €14.97", or "normale prijs per kg €18.30" when on Bonus. It is **missing** on multipack bundles |
| Noise | `isVirtualBundle`: 143 of the 295 `kipfilet` results were "4-pack"/"6-pack" bundles, several of them `isBonus` with a small discount. Filter these out |

```json
{"webshopId": 533083, "title": "AH Scharrel kipfilet 2 stuks", "salesUnitSize": "300 g",
 "priceBeforeBonus": 4.49, "isBonus": false, "unitPriceDescription": "prijs per kg €14.97",
 "mainCategory": "Vlees", "subCategory": "…", "isVirtualBundle": false}
```

### Freshness, requests and budget

Prices are live at request time. Matching uses AH's own server-side relevance search, so "kipfilet" gives sensible candidates, and one request per distinct ingredient term is enough (`size=30` to `100`).

The catch is **ADR 0005's budget of about 30 requests per store per week**. The AH Deal refresh already uses about 25. Pricing a Meal Plan's 20 to 30 distinct ingredients from scratch each week would double that. Two things make it fit:

1. **Regular prices change slowly**, and the estimate is rough guidance. A cached price that is a few weeks old is good enough. Cache each `(store, search term) → chosen product, price, size, fetched_at` in Postgres and refresh only entries older than, say, 4 weeks, with a hard cap per week (e.g. 5 to 10 AH requests). After a few weeks most of the Household's recurring ingredients are cached.
2. **Deals give regular prices for free.** Every AH Bonus product in the `bonuspage` and GraphQL responses has `priceBeforeBonus` and its unit size, and every Jumbo promotion product has `price.price`. Store these as regular-price observations too.

A bulk taxonomy pull (40 to 70 requests) only fits if it is spread over many weeks. That is not worth it.

### Legal / ToS

This is the same as for Deals (see the #2 research). AH's terms allow personal use; its app terms forbid reverse engineering, and we only call endpoints that open-source clients already document. This falls under ADR 0005 unchanged.

## Jumbo: own endpoints (fallback only)

`GET https://www.jumbo.com/producten/?searchType=keyword&searchTerms=kipfilet` with a browser UA returned 200 and 883 KB (verified live). The `__NUXT_DATA__` payload decodes to `Product` objects with `sku`, `title`, `brand`, `category`, `subtitle` (unit size, often null), `link`, and `price {price, promoPrice, pricePerUnit {price, unit}}` (cents, e.g. `{"price": 386, "pricePerUnit": {"price": 1795, "unit": "kg"}}`) and `promotions[].tags`. About 24 products per page were fully populated; the rest were stubs with only an id. [vghoost360/Jumbo-API](https://github.com/vghoost360/Jumbo-API) `app/jumbo_client.py` uses the same URL (`SEARCH_ENDPOINT`, `searchType=keyword`) to look up products by barcode or name. Its GraphQL client is aimed at logged-in basket use, and I did not verify an anonymous GraphQL product search.

This works and has the best data shape of all the options (structured price per unit). But each lookup is a scrape that Jumbo's terms (art. II-9.3) forbid, and it competes with the Deal refresh for the weekly budget. Since Checkjebon already mirrors Jumbo daily and accurately, **use this only if Checkjebon's Jumbo collector breaks**.

## Open Food Facts

- **Product database** ([API docs](https://openfoodfacts.github.io/openfoodfacts-server/api/), ODbL): `GET /api/v2/product/<ean>.json` gives `quantity`, `product_quantity` and `product_quantity_unit` by barcode. Rate limits are 15 requests/min per IP for product reads and 10 requests/min for search ("don't use it for a search-as-you-type feature"). Neither store's search gives the EAN directly; Jumbo's image filenames happen to contain it. The one product I checked (Kips Vega Boterhamworst, 8710991006012) had **no quantity** recorded. Both stores already give the unit size, so OFF adds nothing for prices.
- **Open Prices** ([prices.openfoodfacts.org](https://prices.openfoodfacts.org/api/docs), ODbL, crowd-sourced from receipts and shelf photos): verified live, there are 40 Dutch AH locations with 106 prices in total and 19 Dutch Jumbo locations with 68. Far too sparse to use.

## Turning a match into a cost

None of the sources solve this step. For "400g kipfilet" it needs:

1. **Parse** the ingredient into quantity, unit and name (400, g, "kipfilet"). The LLM already writes the ingredient, so it can emit this structure directly.
2. **Find candidates:** AH search (server-side relevance) or a local text search over Checkjebon's Jumbo names. Drop bundles/multipacks, non-food and ready meals ("Iglo Ping & Klaar … kipfilet").
3. **Choose one:** e.g. the cheapest per kg among plausible plain matches, or prefer the store's own basic brand. Choosing the first result is too random: "kipfilet" ranks sliced sandwich chicken next to raw breast fillet.
4. **Price it** either as price per kg × amount (smooth, good for a rough estimate) or as whole packs needed × pack price (what the Household actually pays). "ca." weights and "per stuk" produce need an assumed weight per piece.

## Recommendation

1. **Introduce a `RegularPriceSource` port** next to `DealSource`, normalising to one shape: store, store product id, name, regular price, unit size (parsed quantity and unit), price per kg/l/piece, source, observed_at.
2. **Jumbo: Checkjebon adapter.** A Procrastinate job downloads `supermarkets.json` once a week (or daily, since it is cheap), keeps only the `jumbo` slice, parses sizes from `s` or the name, and replaces the table. Zero requests to Jumbo. Watch for staleness: if the Jumbo slice stops changing for more than about 3 days, mark it stale, as has already happened to AH upstream.
3. **AH: Appie search adapter with a price cache.** Key it on the ingredient search term. A weekly job refreshes the terms used by upcoming Meal Plans that are missing or older than about 4 weeks, with a hard cap (5 to 10 requests) so the store total stays within ADR 0005's ~30. Filter out `isVirtualBundle`.
4. **Record Deal products' `priceBeforeBonus` / `price.price`** as regular-price observations at no extra cost.
5. **Fallbacks for a rough estimate:** if an ingredient has no AH price yet, use the Jumbo price (or the reverse), and label the estimate as approximate. Do not use Checkjebon's AH slice, not even as a fallback, unless upstream fixes its collector.
6. **Don't use** Open Food Facts, Open Prices, paid aggregators or Jumbo scraping for regular prices.

## Open questions for "How are ingredients matched to Deals and prices?"

- **Structured ingredients:** does the LLM emit `{quantity, unit, name, search_term}` for each Meal Plan ingredient, or does code parse free text? Who owns the search term ("kipfilet" vs "scharrel kipfilet naturel")?
- **Choosing a product:** cheapest per kg among plausible matches, house brand, the product the Household bought before, or the LLM picking from the top N candidates? How are bundles, ready meals and sliced vs raw ("kipfilet" sandwich slices vs breast fillet) told apart?
- **Cost model:** price per kg × amount, or whole packs × pack price? What weight is assumed for "per stuk" produce and "ca. 200 g" items?
- **Shared matcher:** should Deal matching and regular-price matching use the same matcher? A Deal is often a group ("Alle AH kipfilet 25% korting") rather than one product.
- **Budget split:** ADR 0005 caps about 30 requests per store per week, and AH Deals use about 25. How many are reserved for AH price lookups, and is the cap per store in total or per purpose?
- **Staleness:** how old may a cached regular price be before the estimate says so? What happens when Checkjebon's Jumbo slice goes stale like its AH slice did?
- **Cross-store fallback:** is it acceptable to price an AH ingredient with the Jumbo price (or the reverse) when one is missing, given that it is "rough guidance only"?
- **Ingredient identity:** do we keep a canonical ingredient catalogue (e.g. "kipfilet" → chosen AH product, chosen Jumbo product) that is reused across Meal Plans and learned from the Household's corrections, or match fresh every time?
- **Jumbo promo prices in Checkjebon:** for single-product discounts (non-null `promoPrice`), does Checkjebon store the regular price or the promo price? This was unverified because no such product came up. If it stores the promo price, Deal products need their regular price taken from the Deal data instead.
