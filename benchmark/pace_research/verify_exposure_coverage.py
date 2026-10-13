"""历史暴露集覆盖校验 v2：以 legacy_exposure_inventory.json 驱动。

覆盖 4 文件共 98 条；记录文件 sha256 与实际计数；缺失/不一致 → 明确报错
（审计标记未完成）。condition_pairs.json 30 个变体已纳入。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def verify_exposure_coverage(
    inventory_path: Path,
) -> dict:
    inv = json.loads(inventory_path.read_text(encoding="utf-8"))
    results = []
    failures = []
    total = 0
    for r in inv.get("records", []):
        path = REPO / r["path"]
        entry: dict = {"path": r["path"]}
        if not path.is_file():
            entry["verdict"] = "fail"
            entry["failures"] = ["file_missing"]
            failures.append(entry)
            results.append(entry)
            continue
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        entry["sha256_actual"] = sha
        entry["sha_match"] = sha == r.get("sha256")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entry["question_count_actual"] = len(data)
        except (json.JSONDecodeError, TypeError):
            entry["question_count_actual"] = None
        entry["count_match"] = entry["question_count_actual"] == r.get("question_count")
        if not entry["sha_match"]:
            failures.append({**entry, "failures": ["sha256_mismatch"]})
        if not entry["count_match"]:
            failures.append({**entry, "failures": ["count_mismatch"]})
        if entry["sha_match"] and entry["count_match"]:
            entry["verdict"] = "pass"
        else:
            entry["verdict"] = "fail"
        total += entry["question_count_actual"] or 0
        results.append(entry)
    return {
        "schema_version": "exposure-coverage-v2",
        "total_exposure_questions": total,
        "files_passed": sum(1 for r in results if r.get("verdict") == "pass"),
        "files_failed": len(failures),
        "failures": failures,
        "results": results,
    }


if __name__ == "__main__":
    rep = verify_exposure_coverage(
        REPO / "benchmark/qa/dataset/pace_conditions_v1/legacy_exposure_inventory.json"
    )
    print(
        f"coverage: {rep['files_passed']}/{len(rep['results'])} files pass | "
        f"total exposure questions: {rep['total_exposure_questions']}"
    )
    for f in rep["failures"]:
        print("FAIL:", f)
    if rep["files_failed"]:
        print("审计标记未完成：历史暴露集存在缺失或不一致", file=sys.stderr)
        raise SystemExit(1)
