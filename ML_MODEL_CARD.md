# Model card: JalSetu rainfall models v2.0.0

| Field | Value |
| --- | --- |
| Models | Deficient-monsoon classifier (Random Forest); next-month forecaster (climatology, selected over RF and linear models); unusual-month detector (Isolation Forest) |
| Version | 2.0.0, trained 2026-09-30T11:44:48Z, seed 42 |
| Training data | IMD South Interior Karnataka monthly rainfall 1901–2015 (data.gov.in); SHA-256 `bef026758d1c…` |
| Code | `ml/features.py`, `ml/train.py`, `ml/export.py`; inference in `app/ml_runtime.py` |
| Owner | JalSetu project (student project) |

## Intended use

- **Planning and education.** Show how rainfall in June and July relates to the monsoon ending deficient, and flag unusual months in the historical record.
- **Alongside the transparent rules.** Used with, not instead of, the early-warning rules and official IMD bulletins.

## Not intended for

- Operational water-supply decisions, official warnings, or any claim about Bengaluru city rainfall or ward-level conditions.
- Forecasting years after 2015 without new data. The forecaster simply returns the long-term monthly mean.

## Metrics

Full tables are in MODEL_REPORT.md.

| Model | Validation | Key metrics |
| --- | --- | --- |
| Classifier | 9 time-series folds, 85 test seasons (5 deficient) | F1 0.50, recall 0.80, precision 0.36, ROC AUC 0.935, Brier 0.066. The simple rule scores F1 0.533 |
| Forecaster | Test 1996–2015 | Climatology MAE 28.1 mm; the Random Forest was 5% worse |
| Anomaly detector | No labels | Flags 93% of the months at 3 or more standard deviations from normal; this is agreement with a rule, not accuracy |

## Explanations shown to users

- **Classifier:** the probability is split into a base value plus per-feature contributions (path contributions); these add up exactly.
- **Forecaster:** the method text states that no model beat the average.
- **Anomaly detector:** each check shows its z-score and model score.

## Known limitations and risks

- **Region and period.** The data is regional and ends in 2015.
- **Tiny positive class.** Recall moves by 0.2 per season.
- **Uncalibrated probabilities.** The classifier's probabilities come from class-balanced training, so the website presents them as a "risk score".
- **Possible misreading.** Someone could mistake the risk score for an official forecast. Every result on the website carries the model name, version, generation time, region, and a note that it is not an official forecast.

## Updating

1. Add newer data to `data/raw`.
2. Run `python pipeline/run_pipeline.py`, then `python ml/train.py`.
3. Run the ML tests, `pytest ml/tests`. They check that the JSON inference matches scikit-learn and that the metrics are consistent.
4. Update MODEL_REPORT.md with the new numbers from `ml/artifacts/metrics.json`.
