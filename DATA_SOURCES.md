# Data sources and provenance

Every figure JalSetu shows carries a **source**, a **URL** where public, a **data date or period**, the **date it was entered into JalSetu**, and a **status**:

| Status | Meaning |
| --- | --- |
| **historical** | Real published data for a past date |
| **modelled** | An estimate produced by a model |
| **live** | Computed from JalSetu's own database at request time |
| **demonstration** | Invented example rows, only in demo mode |
| **manually uploaded** | Added by an admin with its source |
| **unavailable** | JalSetu has no data for this |

**Nothing in JalSetu is a live government feed.** Official figures are entered by hand from published bulletins (`data/raw/official_indicators.json`). They are re-validated by `python pipeline/run_pipeline.py`, which refuses to run if any record lacks a source, a URL or a status.

## Datasets

| # | Dataset | Source (type) | URL | Period / as of | Retrieved | Status | Processing | Limitations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Sub-divisional monthly rainfall 1901–2015 | India Meteorological Department via Open Government Data Platform India (official). Copy used: GitHub mirror of the same CSV | https://www.data.gov.in/resource/sub-divisional-monthly-rainfall-1901-2017 · copy: https://github.com/chandanverma07/DataSets/blob/master/rainfall%20in%20india%201901-2015.csv | 1901–2015 | 2026-09-30 | historical | Filter to South Interior Karnataka; validate (missing, negative, duplicate, month-sum vs annual); climatology, anomalies, IMD categories, 10-year moving average, OLS trend, Mann-Kendall | Regional, not Bengaluru city; ends 2015; the mirror's integrity was checked by internal consistency (0 annual-sum mismatches), not against data.gov.in directly |
| 2 | Current monsoon rainfall, Bengaluru Urban and Rural | IMD Bengaluru district-wise cumulative rainfall (official) | https://mausam.imd.gov.in/bengaluru/mcdata/cum_stats.pdf | 1 Jun – 28 Sep 2026 | 2026-09-29 | historical | Anomaly = actual − normal; departure % | Hand-entered; one date |
| 3 | Cauvery reservoir storage | IBC World News report of reservoir levels (news report of official figures) | https://ibcworldnews.com/2026/09/05/cauvery-reservoirs-under-pressure/ | 5 Sep 2026 | 2026-09-29 | historical | % full = storage ÷ capacity; trend when more readings are added | Secondary source (news); one reading; KSNDMC bulletins would be the primary source |
| 4 | Stage of groundwater extraction, Bengaluru Urban: 186.7% | National Compilation on Dynamic Ground Water Resources of India 2024 (CGWB), reported by Deccan Herald | https://www.deccanherald.com/amp/story/india%2Fkarnataka%2Fbengaluru%2Fbengaluru-urban-among-5-districts-with-100-plus-groundwater-extraction-3757568 | 2024 assessment (article 9 Oct 2025) | 2026-09-30 | historical | CGWB category (over 100% = over-exploited) | District-wide; secondary source for an official figure |
| 5 | City water balance: 1,372 MLD pumped vs 148 MLD recharge | WELL Labs urban water balance, reported by The Wire | https://m.thewire.in/article/environment/whats-causing-bengalurus-water-crisis | 2024 | 2026-09-29 | **modelled** | Ratio 9.27× | A model estimate, shown separately from the official assessment |
| 6 | Borewells dried: 6,900 of 13,900 | Statement by D.K. Shivakumar (then Deputy CM), reported by SANDRP | https://sandrp.in/2025/03/05/2024-bengaluru-groundwater-top-ten-reports-problems-causes-solutions/ | 2024 | 2026-09-29 | historical | Share | Reported count |
| 7 | Demand ~2,600 MLD | 2024 BWSSB estimate, reported by Neerain | https://neerain.com/bengaluru-water-crisis/ | 2024 | 2026-09-29 | historical | Gap = (demand − supply) ÷ demand | Different year from supply |
| 8 | Supply ~1,935 MLD | BBMP council reply, reported by NammaWard | https://nammaward.in/wardpulse/cauvery-5th-stage-is-supplying-485-mld-of-its-775-mld-capacity | Aug 2026 | 2026-09-29 | historical | Used in the gap | Secondary source |
| 9 | Lake quality: 0 of 149 lakes in class A–C; about 40% class E | KSPCB monitoring, reported by News Karnataka | https://newskarnataka.com/bengaluru/nearly-40-bengaluru-lakes-in-worst-water-quality-class/22022026 | Apr – Nov 2025 | 2026-09-29 | historical | Quality index | City summary only; no per-lake series |
| 10 | Sewage: 580 of 2,300 MLD untreated | SANDRP | (as #6) | 2025 | 2026-09-29 | historical | Shown as context | Secondary source |
| 11 | Treated-water price ₹10/kL | The Hindu, 3 Apr 2024 | https://www.pressreader.com/india/the-hindu-bangalore-9WW1/20240403/281651080121605 | Apr 2024 | 2026-09-29 | historical | Used in savings | May have changed since |
| 12 | BBMP ward boundaries (243 wards, 2022 delimitation) | KSRSAC KGIS, compiled by DataMeet (CC BY-SA 2.5 India) | https://github.com/datameet/Municipal_Spatial_Data/tree/master/Bangalore | 2022 | 2026-09-30 | historical | Validate (243 unique IDs, valid polygons); simplify (RDP, 73,546 → 10,999 points); area (sum 709.8 km², consistent with BBMP's ~712 km²); centroids | Boundaries as scraped by DataMeet; newer GBA corporations are not reflected |
| 13 | Lake locations (7 lakes) | Wikipedia, one article per lake | Listed in `data/raw/lakes.csv` | – | 2026-09-30 | historical | Bounds check, then point-in-polygon ward assignment (all 7 fall in BBMP wards) | Encyclopedia coordinates; only 7 lakes |
| 14 | Locality centres (28) | Hand-entered approximate centres | – | – | – | approximate | Ward assignment (Electronic City lies outside BBMP) | Not surveyed points |
| 15 | Monthly rainfall for the RWH default | climate-data.org, 1991–2021 | https://en.climate-data.org/asia/india/karnataka/bengaluru-4562/ | 1991–2021 | – | **modelled** | Planner input | Not IMD; the IMD regional series is offered as the alternative |
| 16 | IS 10500:2012 limits | Bureau of Indian Standards | – | 2012 + amendments | – | standard | Rule table | See docs/water-quality-standards.md |
| 17 | BWSSB rainwater-harvesting rules | BWSSB guide (as cited on the website) | https://www.euroguardhysquare.com/news-blogs/bwssb-rainwater-harvesting-guidelines | Jan 2026 | 2026-09-29 | historical | Rules | Secondary summary of BWSSB rules |

## Data that does not exist in JalSetu (and is not faked)

- Ward-level rainfall, groundwater levels and supply hours.
- Live reservoir telemetry.
- Per-lake KSPCB time series.
- IoT sensor readings.

Admins can add reservoir readings and lake observations through the API, with a required https source URL. Everything added is audit-logged.

## Adding a real dataset

See `data/external/README.md`.
