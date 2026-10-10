# Where to get Dutch Seasonal Produce data

Research for [#5](https://github.com/KianMeijers/Pickled/issues/5). Sources checked on 2026-10-10.

## Question

Which sources say which fruit and vegetables are in season in the Netherlands, by week or by month? Are they machine-readable? Does their licence allow personal use? Should Pickled keep a small static dataset in the repo?

## Short answer

There is one authoritative Dutch source: the **Voedingscentrum seizoenskalender**. Milieu Centraal now links to it instead of keeping its own calendar. It is **monthly, not weekly**. It covers about 55 vegetables and about 20 fruits grown in the Netherlands in open ground (volle grond), plastic tunnels or unheated greenhouses. It comes as a one-page PDF and as an HTML page that embeds the same lists as schema.org `FAQPage` JSON-LD. There is no API or open-data release, and data.overheid.nl has nothing. The terms allow personal, non-commercial use.

**Recommendation:** keep a small static dataset in the repo, transcribed by hand from the Voedingscentrum calendar with a source note. Do not fetch it at runtime.

## Sources

### 1. Voedingscentrum: seizoensgroente- en seizoensfruitkalender (primary, recommended)

- **HTML page:** <https://www.voedingscentrum.nl/nl/service/vraag-en-antwoord/gezonde-voeding-en-voedingsstoffen/wat-zijn-seizoensgroenten-en-seizoensfruit.aspx>
- **PDF:** <https://www.voedingscentrum.nl/Assets/Uploads/voedingscentrum/Documents/Consumenten/Veelgestelde%20vragen/Voedingscentrum%20seizoengroente-%20en%20fruitkalender.pdf>
- **What counts as seasonal.** The page defines seasonal produce as fruit and vegetables "die worden geteeld in de volle grond, onder een plastic tunnel of in de onverwarmde kas" during their harvest period in the Netherlands. The calendar shows "in welke maand groente en fruit uit de Nederlandse volle grond, plastic tunnel of onverwarmde kas te koop zijn". So the list covers Dutch produce only. Imported fruit with a low climate impact is deliberately left out ("komen ... niet voor in onderstaande lijst").
- **Granularity.** Monthly, January to December. Each month has two lists, *Seizoensgroente* and *Seizoensfruit*. Nothing marks storage produce (bewaarproducten) or the start and end of a season within a month. The page warns that "de oogstperiode kan per jaar verschillen" because of the weather.
- **Provenance.** The PDF footnote says: "samengesteld op basis van informatie van Velt. Aangevuld met inzichten van Bionext en het Voedingscentrum." Velt is a Flemish organisation for ecological growing.
- **Format and machine-readability:**
  - **PDF.** One page, made in InDesign. Created 2023-12-04; the server reports Last-Modified 2025-06-10. `pdftotext -layout` gets the twelve columns out cleanly, but the bottom rows of the fruit lists run into each other, so the output has to be checked by hand.
  - **HTML.** All twelve months are in the static HTML as a schema.org `FAQPage` JSON-LD block. Each month is a `Question` whose `acceptedAnswer.text` holds `<h3>Seizoensgroente</h3><ul><li>…` and `<h3>Seizoensfruit</h3><ul><li>…`. A script can parse this without running JavaScript. The page shows the current month first.
  - **Differences.** The two versions differ a little. For example, the PDF has "raap(steel)" and the HTML has "Raapsteel" for the same month. Treat the HTML as the more current version.
- **Licence.** The terms on the site ([Over de site](https://www.voedingscentrum.nl/nl/service/over-ons/privacy/over-de-site.aspx)) say that all IP belongs to Stichting Voedingscentrum Nederland. Publishing, copying or adapting content without written permission is not allowed "anders dan voor persoonlijk en niet-commercieel gebruik". Quoting with attribution is allowed.
  - Pickled is personal and non-commercial, so using the data in Pickled is covered.
  - Committing a transcription to a **public** GitHub repo is a grey area, because it is publication. That leaves two clean options: keep the dataset in a private repo, or ask the Voedingscentrum communications department for permission. A month-to-crop list is mostly facts, which have little copyright protection on their own, but the terms do not draw that line.

### 2. Milieu Centraal (now "Kenniscentrum Duurzaam Leven")

- Its own groente- en fruitkalender is gone: the old URL `/eten-en-drinken/groente-en-fruitkalender/` returns 404, and the sitemap has no calendar page.
- Its [Groente en fruit](https://www.milieucentraal.nl/eten-en-drinken/milieubewust-eten/groente-en-fruit/) page says "Op deze groente- en fruitkalender (pdf) zie je wat de seizoenen te bieden hebben", and that link points to the **Voedingscentrum PDF** above. Milieu Centraal is therefore not a separate data source any more.
- The page is useful background for the planner's rules. Examples: choose vegetables from Dutch open ground in their season; avoid fresh soft fruit in winter; apples and pears are fine all year.
- **Licence** ([copyright](https://www.milieucentraal.nl/over-ons/copyright/)): reuse is allowed with attribution, but literal quotes are limited to one or two sentences. Infographics need permission.
- `groentefruit.milieucentraal.nl`, an old interactive tool that third-party PDFs still cite, did not respond.

### 3. Other sources considered

| Source | Region | Granularity | Format | Verdict |
|---|---|---|---|---|
| [Velt seizoenskalender](https://velt.nu/seizoenskalender) | Flanders (Belgium); "onze regio" | Monthly, per crop | Interactive HTML; the PDF sits behind a newsletter sign-up | Upstream of the Voedingscentrum list, but Belgian. "© Velt vzw", no reuse terms. Not needed. |
| [EU seasonal calendar](https://agriculture.ec.europa.eu/farming/crops/fruit-and-vegetables/calendar_nl) | "Oceanic" zone (NL, BE, IE, DK, …) | Four seasons | HTML | Too coarse and not specific to the Netherlands. |
| Test-Aankoop / GoodPlanet calendars | Belgium | Monthly | PDF/HTML | Belgian, and commercial or educational. Not needed. |
| data.overheid.nl | — | — | — | No dataset: the CKAN `package_search` for seasonal produce returned 0 results. |
| GroentenFruit Huis | NL trade body | — | — | Publishes consumption figures, not a seasonal calendar. |

No source gives **weekly** data.

## Recommendation

**Keep a static dataset in the repo.** For example, `data/seasonal_produce.toml` or `.json`, keyed by month, with `vegetables` and `fruit` lists. Transcribe it once from the Voedingscentrum HTML page; the JSON-LD makes this a 20-line script or 30 minutes by hand. Record the source URL, licence note and retrieval date in the file.

Why not fetch at runtime:

- The data changes rarely. The PDF was last changed in 2023–2025, and the seasons themselves do not move.
- The repo stays local-first, works offline, and is deterministic in tests.
- There is no API or stable contract. Scraping JSON-LD from a CMS page would break silently if the page changes.
- About 70 products × 12 months is tiny.

**Mapping weeks to months.** The source is monthly, but the CONTEXT.md glossary defines Seasonal Produce "during a given week". The simplest rule is to use the month that contains most of the Meal Plan's days. Another option is the union of both months when a week spans two.

**Matching products.** Names are Dutch common names such as "rodekool", "paddenstoelen" and "raap(steel)". Matching them to Albert Heijn and Jumbo product titles for Deals will need a small alias table, e.g. "rode kool" ↔ "rodekool" and "spruitjes" ↔ "spruiten".

## Open questions

1. **Public repo and licence.** Is the repo public? If so, either ask Voedingscentrum for permission or keep the transcribed dataset out of the public tree. Another option is a small dataset written from several sources in our own words, with attribution.
2. **Week vs month.** Should the Seasonal Produce definition in CONTEXT.md change to "in a given month", or should the planner map each week to a month with a fixed rule?
3. **Storage and year-round produce.** The calendar does not distinguish fresh-harvested produce from stored produce such as apples, pears, onions and carrots in winter-spring. It also leaves out year-round staples such as potatoes. Does Pickled need these distinctions?
4. **Product matching.** Matching Seasonal Produce names to supermarket product names, which overlaps with the Deals research, needs an alias or normalisation layer.
