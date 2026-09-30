# Water-risk methodology (config `2026.09-1`)

The JalSetu water-risk score answers one question: how much pressure is Bengaluru's water system under right now, and which factor is causing it? It is a transparent, rule-based index. It is not machine learning, because no labelled "risk outcome" data exists to train on, and not an official index.

Code: `app/risk.py`. Configuration: `config/risk_config.json`, where the weights and anchors can be changed without touching code. Tests: `tests/test_risk.py`.

## Steps

1. **Gather.** Read each indicator's latest value and provenance from `data/processed/indicators.json`, plus the database (admin-added reservoir readings and verified reports).
2. **Validate.** Every value must be finite and within physical bounds; a bad input raises `RiskInputError` rather than producing a number.
3. **Normalise.** Each indicator is scaled to 0–100 between two anchors:

   `normalised = clamp((value − zero_risk_at) / (full_risk_at − zero_risk_at) × 100, 0, 100)`

4. **Weight and sum.** `score = Σ weight × normalised`. The weights sum to 1 (checked on load).
5. **Classify.** LOW below 25; MODERATE 25–50; HIGH 50–75; CRITICAL 75 and above.
6. **Explain.**
   - Each component's points (`weight × normalised`) are listed, largest first, with value, anchors, source, date and status.
   - Data older than its freshness limit is flagged as stale.
7. **Record.** A snapshot goes into `risk_scores` whenever any input value or the configuration changes, which gives `/api/risk/history`.

## Components

| Component | Indicator | 0 risk at | 100 risk at | Weight | Anchor reasoning |
| --- | --- | --- | --- | --- | --- |
| Rainfall | Bengaluru Urban monsoon departure (IMD) | 0% | −60% | 0.25 | −60% is IMD's "large deficient" boundary |
| Groundwater | Stage of extraction, Bengaluru Urban (CGWB 2024) | 70% | 100% | 0.25 | CGWB: up to 70% is safe; above 100% is over-exploited |
| Reservoir | Cauvery reservoirs storage (% of capacity) | 80% | 20% | 0.20 | JalSetu planning choice |
| Demand | Unmet share of piped demand, (demand − supply) ÷ demand | 0% | 40% | 0.15 | JalSetu planning choice |
| Quality | Mean of (share of lakes not in class A–C) and (share in class E) | 0 | 100 | 0.10 | Uses the KSPCB summary |
| Community | Admin-verified reports in the last 30 days | 0 | 50 | 0.05 | Only verified reports count, so spam can't move the score |

The weights reflect how directly each factor affects the water households get: groundwater and rainfall drive borewell and tanker dependence; reservoirs drive piped supply. They are a documented judgement, not a statistical fit, and can be changed in the config.

## Worked example (current data)

| Component | Value | Normalised | × Weight | Points |
| --- | --- | --- | --- | --- |
| Groundwater | 186.7% | 100 | 0.25 | 25.0 |
| Rainfall | −48.4% | 80.7 | 0.25 | 20.2 |
| Demand | 25.6% gap | 64.0 | 0.15 | 9.6 |
| Quality | 70.0 | 70.0 | 0.10 | 7.0 |
| Reservoir | 63.7% | 27.2 | 0.20 | 5.4 |
| Community | 0 verified | 0 | 0.05 | 0.0 |
| **Total** | | | | **67.2 → HIGH** |

## Early-warning rules

Warnings are evaluated in `risk.evaluate_warnings`. Each one produces a level, the trigger, the affected indicator, a timestamp and suggested actions.

| Rule | Condition | Level |
| --- | --- | --- |
| `RAIN_DEFICIT` | Departure ≤ −20% | WATCH |
| `RAIN_DEFICIT` | Departure ≤ −40% | WARNING |
| `RESERVOIR_LOW` | Storage < 50% | WATCH, or WARNING if storage fell since the previous reading |
| `RESERVOIR_FALLING_DRY_SEASON` | Storage falling while rain ≤ −20% | WATCH |
| `GROUNDWATER_OVEREXPLOITED` | Extraction > 100% | WARNING |
| `BOREWELL_STRESS` | Rain ≤ −20% AND extraction > 100% | ALERT |
| `LAKE_QUALITY` | Quality index ≥ 50 | WATCH |
| `HOTSPOT_<area>` | ≥ 5 verified reports in an area in 30 days | WATCH |

Warnings are persisted with `first_seen` and `last_seen`; a warning is marked inactive when its condition stops holding. The suggested actions are practical and non-medical (rainwater harvesting, reuse, leak fixing, lab testing).

## Limitations

- The inputs come from different dates: rain to 28 Sep 2026, reservoirs 5 Sep 2026, groundwater 2024, and demand and supply from different years. Freshness is shown for each component.
- The score is city-wide. Ward-level inputs are not publicly available.
- The anchors marked "planning choice" are judgements, and they are documented as such.
