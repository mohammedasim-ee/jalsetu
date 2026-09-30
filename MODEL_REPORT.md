# JalSetu model report

Every number here is produced by `python ml/train.py` and stored in `ml/artifacts/metrics.json` (trained 2026-09-30T15:02:26Z, data SHA-256 `5612037b…`). Re-running the script on the same data reproduces them (fixed random seed 42).

## Dataset

| Item | Value |
| --- | --- |
| Source | IMD sub-divisional monthly rainfall **1901–2017**, Open Government Data Platform India ("Sub Divisional Monthly Rainfall from 1901 to 2017") |
| Sub-division | South Interior Karnataka (the IMD sub-division that contains Bengaluru) |
| Rows | 117 years × 12 months = 1,404 monthly totals |
| Validation | 117/117 years kept: no missing values, no negatives, no annual-sum mismatches |
| Consistency with the earlier release | All 1,380 overlapping values for 1901–2015 are identical to the 1901–2015 release used before (checked value by value) |
| Status | Historical, official. Not city-level |
| Newer data | 2018 onwards is not available to JalSetu as a downloadable official monthly series; see data/external/README.md |

Pipeline: `data/raw → pipeline/run_pipeline.py → data/processed/rainfall_monthly.csv → ml/features.py`.

## A. Deficient-monsoon early warning (classification)

**Question.** At the end of July, will the June–September monsoon end deficient, meaning 20% or more below normal (IMD's "deficient" boundary)?

**Features** (all known by 31 July):

| Feature | Definition |
| --- | --- |
| `jun_dep_pct` | June departure from the training-period June mean (%) |
| `jul_dep_pct` | July departure (%) |
| `jun_jul_dep_pct` | June + July combined departure (%) |
| `premonsoon_dep_pct` | March–May departure (%) |
| `prev_ond_dep_pct` | Previous year's October–December departure (%) |

**Leakage control.** Monthly means are computed from the training years only in each fold, and the label uses the same means.

**Validation.** Time-series cross-validation with an expanding window. There are 9 folds; each trains on all earlier years and tests on the next decade (1931–1940, …, 2011–2017). In total there are 87 test seasons, 6 of them deficient.

| Model | Accuracy | Precision | Recall | F1 | ROC AUC | Brier |
| --- | --- | --- | --- | --- | --- | --- |
| Always "not deficient" (majority) | 0.931 | 0.000 | 0.000 | 0.000 | 0.598 | 0.069 |
| Rule: June–July departure ≤ −20% | 0.897 | 0.364 | 0.667 | **0.471** | – | – |
| Logistic regression (balanced, standardised) | 0.851 | 0.267 | 0.667 | 0.381 | 0.805 | 0.127 |
| **Random Forest** (300 trees, depth 3, balanced) | 0.885 | 0.333 | 0.667 | 0.444 | **0.879** | 0.083 |

Confusion matrix of the Random Forest over the 87 test seasons:

| | Predicted deficient | Predicted normal |
| --- | --- | --- |
| **Actually deficient** | 4 (TP) | 2 (FN) |
| **Actually normal** | 8 (FP) | 73 (TN) |

**Selection and reason.** Among the ML models, the Random Forest has the best F1 and the best ROC AUC, so it is deployed. However:

- **It does not beat the one-line rule on F1** (0.444 vs 0.471). The early-warning engine uses the transparent rule, and the Random Forest is shown alongside it as a ranking score.
- **Its probabilities are not calibrated.** Training with balanced class weights gives a Brier score (0.083) worse than always predicting the base rate (0.069). The website labels the output "risk score, not a calibrated chance".
- **There are only 6 positive test cases**, so each detection moves recall by about 0.17.
- **Adding 2016–2017 lowered the scores** compared with the 1901–2015 version (F1 0.50 → 0.44, AUC 0.935 → 0.879). The 2016 drought is a hard case: its June was only slightly below normal, and even the model trained on all 117 years scores 2016 at 0.46, just below the 0.5 cut-off. This is reported rather than tuned away.

**Explainability.** Each prediction is decomposed with path contributions (the Saabas / "treeinterpreter" method): probability = base value + sum of per-feature contributions, exactly. This is tested.

| Feature | RF importance | Logistic coefficient (standardised) |
| --- | --- | --- |
| June–July combined | 0.456 | −1.30 |
| July | 0.228 | −0.98 |
| June | 0.188 | −0.90 |
| Pre-monsoon | 0.071 | +0.03 |
| Previous Oct–Dec | 0.057 | +0.35 |

## B. Next-month rainfall forecast (regression)

**Split.** Train on 1902–1995; test on 1996–2017 (264 months, never seen in training).

| Model | MAE (mm) | RMSE (mm) | R² | Skill vs climatology (MAE) |
| --- | --- | --- | --- | --- |
| **Climatology** (training-period monthly mean) | **28.8** | **41.9** | 0.757 | 0% |
| Seasonal naive (same month last year) | 40.4 | 57.9 | 0.535 | −40.2% |
| Linear anomaly persistence | 29.1 | 42.0 | 0.755 | −1.1% |
| Random Forest (200 trees, depth 6) | 30.0 | 43.2 | 0.741 | −4.0% |

**Selected: climatology.** No model beat the long-term monthly average. The Random Forest put 90% of its importance on the month's normal; past anomalies carry almost no information about next month's rain.

## C. Unusual-month detection (unsupervised)

**Model.** Isolation Forest (100 trees, 256 samples each, contamination 2%) on three features: the month's z-score, a 3-month rolling z-score, and the log ratio to normal.

**Result.** It flagged 29 of 1,402 months. The most unusual:

| Month | Rainfall | Normal |
| --- | --- | --- |
| March 2008 | 108.9 mm | 9.5 mm |
| December 1902 | 84.9 mm | 11.7 mm |
| March 1984 | 75.4 mm | 9.5 mm |
| February 1928 | 44.3 mm | 4.1 mm |

**Evaluation limitation.** There are no labelled anomalies, so precision and recall cannot be measured. As a proxy, the model flagged 13 of the 14 months that lie 3 or more standard deviations from normal (93%); 45% of its flags meet that rule. This is agreement with a rule, not accuracy.

## Deployment and inference

- **Exported to JSON.** The models are exported as tree arrays with exact thresholds (`ml/export.py`) and run in pure Python on the server (`app/ml_runtime.py`). Inputs are cast to 32-bit floats, as scikit-learn does inside trees.
- **Tested for equivalence.** The Random Forest matches scikit-learn's `predict_proba` to within 0.001; Isolation Forest scores match `decision_function` to within 1e-9.
- **Logged.** Every prediction is stored in `model_predictions` with the model name, version, inputs, output and time.

## Limitations

1. **Region.** The data is regional (South Interior Karnataka), not Bengaluru city, and that series peaks in July whereas Bengaluru's rain peaks in September and October. A daily Bengaluru city station file for 1990–2022 was checked, but only 98 of 391 months are complete, so it was not used.
2. **Time range.** The official series available here ends in 2017. The 2026 figures on the website come from IMD district bulletins, which are a different series.
3. **Small positive class.** There are about 19 deficient seasons in 116 years, so every classification metric has wide uncertainty.
4. **No labels for risk.** No ward-level or labelled "risk" data exists, so the overall risk score is rule-based, not learned.
5. **Trend.** There is a significant increasing trend (Mann-Kendall p = 0.0006 for June–September), so older years are drier on average. The expanding training window partly absorbs this.
