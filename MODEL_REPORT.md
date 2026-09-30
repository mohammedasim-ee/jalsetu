# JalSetu model report

Every number here is produced by `python ml/train.py` and stored in `ml/artifacts/metrics.json` (trained 2026-09-30T11:44:48Z, data SHA-256 `bef02675…`). Re-running the script on the same data reproduces them (fixed random seed 42).

## Dataset

| Item | Value |
| --- | --- |
| Source | IMD sub-divisional monthly rainfall, 1901–2015, Open Government Data Platform India |
| Sub-division | South Interior Karnataka (the IMD sub-division that contains Bengaluru) |
| Rows | 115 years × 12 months = 1,380 monthly totals |
| Validation | 115/115 years kept: no missing values, no negatives, 0 years where the month sum differs from the published annual total by more than 1 mm |
| Status | Historical, official. Not city-level; ends in 2015 |

Pipeline: `data/raw → pipeline/run_pipeline.py → data/processed/rainfall_monthly.csv → ml/features.py`.

## A. Deficient-monsoon early warning (classification)

**Question.** At the end of July, will the June–September monsoon end deficient, meaning 20% or more below normal (IMD's "deficient" boundary)?

**Features** (all known by 31 July):

| Feature | Definition |
| --- | --- |
| `jun_dep_pct` | June rainfall departure from the training-period June mean (%) |
| `jul_dep_pct` | July departure (%) |
| `jun_jul_dep_pct` | June + July combined departure (%) |
| `premonsoon_dep_pct` | March–May departure (%) |
| `prev_ond_dep_pct` | Previous year's October–December departure (%) |

**Preprocessing and leakage control.** The monthly means used for every departure are computed from the training years only in each fold, and the label is defined against the same means.

**Validation.** Time-series cross-validation with an expanding window. There are 9 folds; each trains on all earlier years and tests on the next decade (1931–1940, …, 2011–2015). In total there are 85 test seasons, of which 5 were deficient.

| Model | Accuracy | Precision | Recall | F1 | ROC AUC | Brier |
| --- | --- | --- | --- | --- | --- | --- |
| Always "not deficient" (majority) | 0.941 | 0.000 | 0.000 | 0.000 | 0.556 | 0.063 |
| Rule: June–July departure ≤ −20% | 0.918 | 0.400 | 0.800 | **0.533** | – | – |
| Logistic regression (balanced, standardised) | 0.871 | 0.286 | 0.800 | 0.421 | 0.875 | 0.109 |
| **Random Forest** (300 trees, depth 3, balanced) | 0.906 | 0.364 | 0.800 | 0.500 | **0.935** | 0.066 |

Confusion matrix of the Random Forest over the 85 test seasons:

| | Predicted deficient | Predicted normal |
| --- | --- | --- |
| **Actually deficient** | 4 (TP) | 1 (FN) |
| **Actually normal** | 7 (FP) | 73 (TN) |

**Selection and reason.** Among the ML models, the Random Forest has the best F1 and the best ROC AUC, so it is deployed. However:

- **It does not beat the one-line rule on F1** (0.500 vs 0.533). The early-warning engine therefore uses the transparent rule, and the Random Forest is shown alongside it as a risk score that ranks years well (AUC 0.935).
- **Its probabilities are not calibrated.** It was trained with balanced class weights, and its Brier score (0.066) is no better than always predicting the base rate (0.063). The website therefore labels its output "risk score, not a calibrated chance".
- **There are only 5 positive test cases.** One more or one fewer correct detection moves recall by 0.2. The metrics are indicative, not precise.

**Explainability.** Each prediction is decomposed with path contributions (the Saabas / "treeinterpreter" method): probability = base value + sum of per-feature contributions, exactly, for tree ensembles. `ml/tests/test_ml.py` checks that the parts add up.

Global view:

| Feature | Random Forest importance | Logistic coefficient (standardised) |
| --- | --- | --- |
| June–July combined | 0.455 | −1.29 |
| July | 0.207 | −0.97 |
| June | 0.196 | −0.88 |
| Previous Oct–Dec | 0.073 | +0.37 |
| Pre-monsoon | 0.069 | +0.21 |

Rain in June and July dominates, which is expected: those two months make up about half of the June–September total.

## B. Next-month rainfall forecast (regression)

**Question.** Predict next month's rainfall (mm) from the anomalies of the previous 3 months and of the same month last year, plus seasonality.

**Split.** Train on 1902–1995; test on 1996–2015 (240 months, never seen in training).

| Model | MAE (mm) | RMSE (mm) | R² | Skill vs climatology (MAE) |
| --- | --- | --- | --- | --- |
| **Climatology** (training-period monthly mean) | **28.1** | **40.8** | 0.772 | 0% |
| Seasonal naive (same month last year) | 38.8 | 55.9 | 0.573 | −38.3% |
| Linear anomaly persistence | 28.3 | 40.9 | 0.771 | −0.9% |
| Random Forest (200 trees, depth 6) | 29.5 | 42.7 | 0.751 | −5.0% |

**Selected: climatology.** No model beat the long-term monthly average. The Random Forest put 90% of its importance on the month's normal, and the lagged anomalies carry almost no information about next month's rain. So the forecast endpoint returns the monthly mean and says why. R² is high only because the seasonal cycle is easy; the skill score shows there is no skill beyond it.

## C. Unusual-month detection (unsupervised)

**Model.** Isolation Forest (100 trees, 256 samples each, contamination 2%) on three features:
- the month's z-score against its calendar-month mean;
- a 3-month rolling z-score;
- the log ratio to normal.

**Result.** It flagged 28 of 1,378 months. The most unusual:

| Month | Rainfall | Normal |
| --- | --- | --- |
| March 2008 | 108.9 mm | 9.5 mm |
| February 1928 | 44.3 mm | 4.2 mm |
| December 1902 | 84.9 mm | 11.5 mm |
| March 1984 | 75.4 mm | 9.5 mm |

**Evaluation limitation.** There are no labelled "true anomalies", so precision and recall cannot be measured. As a proxy, the model flagged 13 of the 14 months that lie 3 or more standard deviations from normal (93%). 46% of its flags meet that rule; the rest are unusual in combination, for example a dry month after a wet spell. This is agreement with a rule, not accuracy.

## Deployment and inference

- **Exported to JSON.** scikit-learn models are exported as tree arrays (`ml/export.py`). The server runs them in pure Python (`app/ml_runtime.py`), so the Vercel function needs no scikit-learn or numpy.
- **Tested for equivalence.** The Random Forest output matches scikit-learn's `predict_proba` to within 0.001 (limited by threshold rounding in the JSON export); Isolation Forest scores match `decision_function` to within 1e-9.
- **Logged.** Every prediction is stored in `model_predictions` with the model name, version, inputs, output and timestamp.

## Limitations

1. **Region.** The data is regional (South Interior Karnataka), not Bengaluru city. That sub-division's rainfall peaks in July, whereas Bengaluru's peaks in September and October.
2. **Time range.** The series ends in 2015, so the models cannot see 2016–2026. The 2026 Bengaluru figures on the website come from IMD district bulletins, which are a different series.
3. **Small positive class.** Only about 19 deficient seasons exist in 114 years, so every classification metric has wide uncertainty.
4. **No ward-level data.** No ward-level or groundwater time series is publicly available, so there is no ML model for ward risk or groundwater. The overall risk score is rule-based, not learned, because no labelled "risk" outcomes exist to learn from.
5. **Linear trend.** The significant increasing trend (Mann-Kendall p = 0.0002 for June–September) means older years are drier on average. An expanding training window partly absorbs this.
