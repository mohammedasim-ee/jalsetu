# Water-quality standard used by JalSetu

**Standard:** IS 10500:2012, *Drinking Water — Specification (Second Revision)*, Bureau of Indian Standards, with amendments. Code: `app/rules.py` (`IS10500`, `judge`, `check_water`). Tests: `tests/test_api.py::test_all_18_parameters_boundaries` checks every limit at, just above and beyond its boundary.

Each parameter has an **acceptable limit** and, for some, a **permissible limit in the absence of an alternate source**. JalSetu's statuses:

| Status | Meaning |
| --- | --- |
| **Safe** | At or within the acceptable limit |
| **High** | Above the acceptable limit but within the permissible limit. The standard allows this only when no better source exists |
| **Unsafe** | Above the permissible limit; above the acceptable limit where the standard allows **no relaxation**; outside the required pH range; or bacteria detected |
| **Invalid** | Negative, not a number, or pH above 14 |

| # | Parameter | Unit | Acceptable | Permissible (no alternate source) |
| --- | --- | --- | --- | --- |
| 1 | pH | – | 6.5–8.5 | No relaxation |
| 2 | Total dissolved solids | mg/L | 500 | 2000 |
| 3 | Turbidity | NTU | 1 | 5 |
| 4 | Total hardness (as CaCO₃) | mg/L | 200 | 600 |
| 5 | Total alkalinity (as CaCO₃) | mg/L | 200 | 600 |
| 6 | Calcium | mg/L | 75 | 200 |
| 7 | Magnesium | mg/L | 30 | 100 |
| 8 | Chloride | mg/L | 250 | 1000 |
| 9 | Sulphate | mg/L | 200 | 400 |
| 10 | Nitrate | mg/L | 45 | No relaxation |
| 11 | Fluoride | mg/L | 1.0 | 1.5 |
| 12 | Iron | mg/L | 0.3 | No relaxation (2012 amendment) |
| 13 | Manganese | mg/L | 0.1 | 0.3 |
| 14 | Ammonia (as total ammonia-N) | mg/L | 0.5 | No relaxation |
| 15 | Arsenic | mg/L | 0.01 | 0.05 |
| 16 | Lead | mg/L | 0.01 | No relaxation |
| 17 | Total coliform bacteria | MPN/100 mL | Shall not be detectable | – |
| 18 | E. coli | MPN/100 mL | Shall not be detectable | – |

**Why these 18.** They are the parameters that routine drinking-water lab reports in Bengaluru commonly include, covering physical, chemical, toxic and bacteriological checks, and the ones most relevant to groundwater (nitrate, fluoride, TDS, hardness, coliform). IS 10500 lists more parameters; JalSetu does not check the others and says so.

**Verdict.**
- *Unsafe* if any parameter is Unsafe.
- Otherwise *Usable only if no other source* if any parameter is High.
- Otherwise *Meets IS 10500 for the values entered*.

Parameters that are not entered are not assumed safe.

**Not medical advice.** This compares numbers with a published standard. When bacteria are detected, the page suggests disinfection and consulting the local health authority, and makes no health claims beyond that.

Note: the arsenic value of 0.05 mg/L shown as "permissible" follows the table JalSetu has used since v1. Readers should confirm against the latest BIS amendment before relying on it. See Limitations in README.
