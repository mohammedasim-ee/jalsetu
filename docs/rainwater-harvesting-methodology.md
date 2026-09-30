# Rainwater-harvesting calculator: methodology

Code: `app/rules.py` (`harvest_litres`, `rwh_plan`). API: `POST /api/rwh`. Tests: `tests/test_api.py::test_rwh_*`.

## Harvest formula

**Harvestable water (litres) = rainfall (mm) × roof area (m²) × runoff coefficient × collection efficiency**

- **Unit check.** 1 mm of rain over 1 m² is 0.001 m³, which is 1 litre. So mm × m² gives litres directly; dividing by 1000 gives kilolitres (kL).
- **Runoff coefficient (C).** The share of rain that runs off the roof rather than soaking in or evaporating. The default is 0.8, a commonly used planning figure for concrete roofs. The user can change it (0.05–1).
- **Collection efficiency (η).** The share of runoff actually captured after first-flush diversion, filter losses and overflow. The default is 1.0, meaning nothing extra is lost. The user can change it (0.05–1).
- **Monthly calculation.** Harvest is computed for each month from monthly rainfall, then summed for the year.

## Rainfall options

| Option | Source | Status |
| --- | --- | --- |
| Bengaluru estimate (default) | climate-data.org, 1991–2021 monthly averages | **Modelled** estimate for the city; not IMD |
| IMD South Interior Karnataka mean | IMD sub-divisional data 1901–2015 (JalSetu pipeline) | **Official**, but regional: it peaks in July, unlike Bengaluru |
| Annual override | User enters an annual total in mm | The monthly pattern of the chosen series is scaled to that total |

## BWSSB rules applied

- **Mandatory or not:**
  - buildings from 2009 onwards: required on sites of 30 × 40 ft (1,200 sq ft) or more;
  - older buildings: required on sites of 60 × 40 ft (2,400 sq ft) or more.
- **Minimum storage:** 20 L per m² of roof plus 10 L per m² of paved open area.
- **Penalty for non-compliance:** 50% of the water bill for the first 3 months, then 100%.
  - The calculator shows the first-year penalty avoided as bill × 0.5 × 3 + bill × 9.
  - Example: a ₹800 bill gives ₹1,200 + ₹7,200 = ₹8,400.

Source for the BWSSB rules: the BWSSB guide cited on the website (Jan 2026).

## Limitations

- The storage figure is the BWSSB minimum, not an optimised tank size. Sizing for full capture would need daily rainfall data.
- The calculator does not model soakage, recharge-pit design or water quality.
