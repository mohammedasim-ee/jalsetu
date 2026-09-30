"""Reproducible JalSetu data pipeline.

    python pipeline/run_pipeline.py

Raw data (data/raw) -> validation -> cleaning -> normalisation -> feature engineering -> data/processed.
Deterministic: the same raw files always produce the same processed files (only manifest.generated_at changes).
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import rules  # noqa: E402
from pipeline import gis, indicators, rainfall  # noqa: E402

RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "processed"
PIPELINE_VERSION = "2.0.0"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def dump(obj, name: str) -> Path:
    p = OUT / name
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":") if name.endswith(".geojson") else None,
                            indent=None if name.endswith(".geojson") else 1))
    return p


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    validation = {}

    # 1. rainfall
    rows, rep = rainfall.load_and_validate(RAW / "imd_subdivision_monthly_rainfall_1901_2015.csv")
    if len(rows) < 100:
        raise SystemExit(f"Rainfall validation failed: only {len(rows)} usable years")
    monthly, analysis = rainfall.build_features(rows)
    analysis["source"] = {"name": "IMD sub-divisional monthly rainfall 1901–2015 (Open Government Data Platform India)",
                          "dataset_page": "https://www.data.gov.in/resource/sub-divisional-monthly-rainfall-1901-2017",
                          "copy_used": "https://github.com/chandanverma07/DataSets/blob/master/rainfall%20in%20india%201901-2015.csv",
                          "status": "historical", "limitations": "Sub-division average, not Bengaluru city; series ends in 2015."}
    rainfall.write_monthly_csv(monthly, OUT / "rainfall_monthly.csv")
    dump(analysis, "rainfall_analysis.json")
    validation["rainfall"] = rep

    # 2. GIS
    wards, wrep = gis.process_wards(json.loads((RAW / "bbmp_wards_kgis.geojson").read_text()))
    if wrep["features_kept"] < 200:
        raise SystemExit("Ward validation failed")
    dump(wards, "wards.geojson")
    validation["wards"] = wrep
    lakes, lrep = gis.process_lakes(RAW / "lakes.csv", wards)
    dump(lakes, "lakes.json")
    validation["lakes"] = lrep
    locs = gis.process_localities(rules.AREAS, wards)
    dump(locs, "localities.json")
    validation["localities"] = {"count": len(locs), "outside_bbmp": [x["name"] for x in locs if not x["ward"]]}

    # 3. official indicators
    ind, irep = indicators.process(json.loads((RAW / "official_indicators.json").read_text()))
    dump(ind, "indicators.json")
    validation["indicators"] = irep

    dump(validation, "validation_report.json")
    manifest = {"pipeline_version": PIPELINE_VERSION, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "duration_s": round(time.time() - t0, 2),
                "inputs": {p.name: sha256(p) for p in sorted(RAW.iterdir()) if p.is_file()},
                "outputs": {p.name: sha256(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "manifest.json"}}
    dump(manifest, "manifest.json")
    return {"validation": validation, "manifest": manifest}


if __name__ == "__main__":
    res = main()
    v = res["validation"]
    print(f"rainfall: {v['rainfall']['rows_kept']}/{v['rainfall']['rows_read']} years kept, "
          f"{v['rainfall']['annual_sum_mismatch']} annual-sum mismatches, missing years {v['rainfall']['missing_years']}")
    print(f"wards: {v['wards']['features_kept']} kept, points {v['wards']['points_before']} -> {v['wards']['points_after']}, "
          f"area {v['wards']['total_area_km2']} km2")
    print(f"lakes: {v['lakes']['rows_kept']}/{v['lakes']['rows_read']} kept {v['lakes']['issues']}")
    print(f"localities outside BBMP: {v['localities']['outside_bbmp']}")
    print("indicators: validated")
    print("outputs:", ", ".join(res["manifest"]["outputs"]))
