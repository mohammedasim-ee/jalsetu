# External data (not committed)

Put larger or licensed datasets here. Nothing in this folder is read automatically.

## How to supply a real dataset

| Dataset | How to add it |
| --- | --- |
| **Newer IMD rainfall bulletin** | Edit `rainfall_current_season` in `data/raw/official_indicators.json`: values, `as_of`, `retrieved`, `url`. Run `python pipeline/run_pipeline.py`. The pipeline refuses records without a source, an https URL or a status. |
| **Reservoir readings (KSNDMC / CWC bulletins)** | Admin dashboard → "Add a reservoir reading", or `POST /api/admin/reservoir-readings` with a source and an https URL. Trends appear once there are two or more readings. |
| **KSPCB per-lake quality** | `POST /api/admin/lake-observations` (`lake_id`, `date`, `parameter`, `value` or `class`, `source`, `url`). |
| **Longer rainfall history (after 2017)** | Add a CSV with the same columns as `data/raw/imd_subdivision_monthly_rainfall_1901_2017.csv`, set `RAINFALL_FILE` in `pipeline/run_pipeline.py` to it, then rerun `python ml/train.py` and update MODEL_REPORT.md. |
| **Ward-level groundwater (CGWB observation wells)** | Not implemented. It would need a new pipeline stage mapping wells to wards; the map currently says this data is unavailable. |
