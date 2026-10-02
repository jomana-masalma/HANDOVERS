"""
Stage 2: normalize and validate Stage 1 outputs.

No YouTube API calls here. Reads files from youtube_out/ (Stage 1) 
separate stage :
- Stage 1 saves raw API JSON + first-pass canonical JSONL.
- Stage 2 checks completeness, merges curated + search records, and prepares
  one clean file for dashboards and network scripts (Stage 3).
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Stage 1 must have produced these before Stage 2 can run.
REQUIRED_STAGE1_FILES = [
    "out_videos_raw.json",
    "out_channels_raw.json",
    "out_search_enriched_videos.json",
    "out_canonical_curated_videos.jsonl",
    "out_canonical_search_videos.jsonl",
]

CANONICAL_REQUIRED_KEYS = [
    "platform",
    "post_id",
    "author_id",
    "title_or_text",
    "url",
    "created_at",
    "engagement",
    "provenance",
]


@dataclass
class Stage2Config:
    input_dir: Path = field(default_factory=lambda: Path("./youtube_out"))
    output_dir: Path = field(default_factory=lambda: Path("./youtube_out/stage2"))


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def validate_stage1_inputs(input_dir: Path) -> Dict[str, Any]:
    """Check that Stage 1 artifacts exist before we normalize."""
    missing = [name for name in REQUIRED_STAGE1_FILES if not (input_dir / name).exists()]
    return {"ok": len(missing) == 0, "missing_files": missing}


def validate_canonical_row(row: Dict[str, Any]) -> List[str]:
    """Return list of validation errors for one canonical record."""
    errors: List[str] = []
    for key in CANONICAL_REQUIRED_KEYS:
        if key not in row or row[key] in (None, ""):
            errors.append(f"missing_or_empty:{key}")
    engagement = row.get("engagement") or {}
    if not isinstance(engagement, dict):
        errors.append("engagement_not_dict")
    elif engagement.get("viewCount") in (None, ""):
        # Views are central for impact analysis; flag but do not drop the row.
        errors.append("warning:viewCount_missing")
    return errors


def merge_canonical_records(input_dir: Path) -> List[Dict[str, Any]]:
    curated = read_jsonl(input_dir / "out_canonical_curated_videos.jsonl")
    search = read_jsonl(input_dir / "out_canonical_search_videos.jsonl")
    # Curated first, then search — provenance field keeps the source clear.
    return curated + search


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_stage2(cfg: Stage2Config) -> Path:
    input_check = validate_stage1_inputs(cfg.input_dir)
    if not input_check["ok"]:
        raise SystemExit(
            f"Stage 1 outputs incomplete. Missing: {input_check['missing_files']}"
        )

    records = merge_canonical_records(cfg.input_dir)
    validation_rows: List[Dict[str, Any]] = []
    clean_records: List[Dict[str, Any]] = []

    for row in records:
        issues = validate_canonical_row(row)
        validation_rows.append(
            {
                "post_id": row.get("post_id"),
                "provenance": row.get("provenance"),
                "issues": issues,
                "valid": len([i for i in issues if not i.startswith("warning:")]) == 0,
            }
        )
        #  for downstream review.
        clean_records.append(row)

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(cfg.output_dir / "canonical_all_videos.jsonl", clean_records)

    report = {
        "stage": 2,
        "input_dir": str(cfg.input_dir.resolve()),
        "total_records": len(clean_records),
        "curated_count": sum(1 for r in clean_records if r.get("provenance") == "curated_mentor_list"),
        "search_count": sum(
            1 for r in clean_records if str(r.get("provenance", "")).startswith("search:")
        ),
        "records_with_errors": sum(1 for v in validation_rows if not v["valid"]),
        "records_with_view_warning": sum(
            1 for v in validation_rows if any(i == "warning:viewCount_missing" for i in v["issues"])
        ),
        "per_record_validation": validation_rows,
    }
    report_path = cfg.output_dir / "stage2_validation_report.json"
    write_json(report_path, report)

    logging.info("Stage 2 complete: %s records -> %s", len(clean_records), report_path)
    return report_path


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stage 2 — normalize and validate Stage 1 YouTube outputs.")
    p.add_argument("--input-dir", type=Path, default=Path("./youtube_out"))
    p.add_argument("--output-dir", type=Path, default=Path("./youtube_out/stage2"))
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    cfg = Stage2Config(input_dir=args.input_dir.resolve(), output_dir=args.output_dir.resolve())
    run_stage2(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
