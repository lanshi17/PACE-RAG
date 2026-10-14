"""专家双审记录汇总（R2 专家开发试标 §4）：校验、分歧检测、家族状态表、
工时汇总、gold 草稿导出。

用法：
    uv run python benchmark/pace_research/aggregate_expert_review.py \
        --reviewed-a PATH --reviewed-b PATH [--out DIR]

输入：专家填写后的 review_package_A.json / review_package_B.json（材料哈希
必须仍与绑定值一致）。输出（--out，默认 pace_conditions_v1/expert_review/）：
- validation_report.json   54 份题级记录的完整性校验
- disagreement_log.json    逐题分歧（保留双方原始意见，供第三名专家仲裁）
- family_status_table.json 逐家族/逐题处置状态汇总
- worktime_summary.json    逐题/逐包耗时与总工时
- gold_draft.json          已审核开发集 gold 草稿（未冻结，隐藏题仍为 0）

仲裁未完成时，gold 草稿只含双方一致项；分歧项状态为 pending_arbitration。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
BASE = REPO / "benchmark/qa/dataset/pace_conditions_v1"
MATERIAL_FILES = [
    "dev_families.json",
    "evidence_candidates.json",
    "template_overlap_audit_v3.json",
    "legacy_exposure_inventory.json",
]


def _load_filled(path: Path, expect_reviewer: str) -> dict[str, Any]:
    import hashlib

    pkg = json.loads(path.read_text(encoding="utf-8"))
    assert pkg["reviewer_id"] == expect_reviewer, f"{path}: reviewer_id={pkg['reviewer_id']}"
    # 材料必须与审核包绑定值一致：材料变化 → 拒绝汇总
    for f in MATERIAL_FILES:
        bound = pkg["material_version"]["files"][f]["sha256"]
        actual = hashlib.sha256((BASE / f).read_bytes()).hexdigest()
        assert bound == actual, f"{path}: material hash mismatch for {f}"
    assert len(pkg["rows"]) == 27, f"{path}: rows={len(pkg['rows'])}"
    return pkg


def _is_filled(v: Any) -> bool:
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, list):
        return len(v) > 0
    return v is not None


def aggregate(path_a: Path, path_b: Path, out_dir: Path) -> dict[str, Any]:
    pkg_a = _load_filled(path_a, "A")
    pkg_b = _load_filled(path_b, "B")
    rows_a = {r["draft_question_id"]: r for r in pkg_a["rows"]}
    rows_b = {r["draft_question_id"]: r for r in pkg_b["rows"]}
    assert set(rows_a) == set(rows_b), "A/B 包题集不一致"

    ovl = json.loads((BASE / "template_overlap_audit_v3.json").read_text(encoding="utf-8"))
    flagged_families = set(ovl["flagged_families"])

    validation: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    family_rows: dict[str, list[dict[str, Any]]] = {}
    gold: list[dict[str, Any]] = []
    worktime: dict[str, Any] = {"per_question": [], "totals": {}}
    status_counter: Counter[str] = Counter()

    for qid in sorted(rows_a):
        ra, rb = rows_a[qid], rows_b[qid]
        fid = ra["family_id"]
        # 完整性：每份记录必填适用性判定与完成时间
        for who, r in (("A", ra), ("B", rb)):
            missing = []
            if not _is_filled(r["clinical_fields"].get("适用性判定")):
                missing.append("适用性判定")
            if not _is_filled(r.get("完成时间")):
                missing.append("完成时间")
            validation.append(
                {"draft_question_id": qid, "reviewer": who, "missing": missing}
            )
        # 分歧检测：适用性判定 / 必需陈述 / 禁止断言 / 条件字段
        diffs = []
        for key, fa, fb in (
            ("适用性判定", ra["clinical_fields"].get("适用性判定"), rb["clinical_fields"].get("适用性判定")),
            ("必需陈述", ra["clinical_fields"].get("必需陈述"), rb["clinical_fields"].get("必需陈述")),
            ("禁止断言", ra["clinical_fields"].get("禁止断言"), rb["clinical_fields"].get("禁止断言")),
            ("应变项", ra["conditional_fields"].get("应变项"), rb["conditional_fields"].get("应变项")),
            ("应保持项", ra["conditional_fields"].get("应保持项"), rb["conditional_fields"].get("应保持项")),
        ):
            if fa != fb:
                diffs.append({"field": key, "reviewer_A": fa, "reviewer_B": fb})
        if diffs:
            disagreements.append(
                {
                    "draft_question_id": qid,
                    "family_id": fid,
                    "priority": "high" if fid in flagged_families else "normal",
                    "items": diffs,
                    "arbitration": {"decision": "", "basis": "", "arbitrator": "", "时间": ""},
                }
            )
            status = "pending_arbitration"
        else:
            status = "agreed_pending_expert_signoff"
        status_counter[status] += 1
        family_rows.setdefault(fid, []).append({"draft_question_id": qid, "status": status})
        gold.append(
            {
                "draft_question_id": qid,
                "family_id": fid,
                "status": status,
                "known_conditions": ra["known_conditions"],
                "agreed": {} if diffs else {"适用性判定": ra["clinical_fields"].get("适用性判定")},
                "sources": {"reviewer_A": f"{path_a.name}#{qid}", "reviewer_B": f"{path_b.name}#{qid}"},
            }
        )
        # 工时：按包内字段解析分钟数
        for who, r in (("A", ra), ("B", rb)):
            try:
                minutes = float(r.get("耗时分钟") or 0)
            except (TypeError, ValueError):
                minutes = 0.0
            worktime["per_question"].append(
                {"draft_question_id": qid, "reviewer": who, "minutes": minutes}
            )

    worktime["totals"] = {
        "minutes_A": sum(x["minutes"] for x in worktime["per_question"] if x["reviewer"] == "A"),
        "minutes_B": sum(x["minutes"] for x in worktime["per_question"] if x["reviewer"] == "B"),
        "records": len(worktime["per_question"]),
    }
    family_status = {
        fid: {
            "flagged_for_adjudication": fid in flagged_families,
            "statuses": Counter(r["status"] for r in rows)["pending_arbitration"],
            "rows": rows,
        }
        for fid, rows in family_rows.items()
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = {"generated_at": datetime.now().isoformat(), "gold_frozen": False, "hidden_questions": 0}
    (out_dir / "validation_report.json").write_text(
        json.dumps({"summary": {"records": len(validation)}, "rows": validation, **stamp}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "disagreement_log.json").write_text(
        json.dumps({"summary": {"n_disagreements": len(disagreements)}, "items": disagreements, **stamp}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "family_status_table.json").write_text(
        json.dumps({"families": family_status, "status_counts": dict(status_counter), **stamp}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "worktime_summary.json").write_text(
        json.dumps({**worktime, **stamp}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "gold_draft.json").write_text(
        json.dumps({"summary": {"n_questions": len(gold), "status_counts": dict(status_counter)}, "questions": gold, **stamp}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"records: {len(validation)} | disagreements: {len(disagreements)} | "
        f"worktime: A={worktime['totals']['minutes_A']}min B={worktime['totals']['minutes_B']}min"
    )
    print(f"wrote 5 files to {out_dir}（gold 未冻结，隐藏题仍为 0）")
    return {"records": len(validation), "disagreements": len(disagreements)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-a", type=Path, required=True)
    parser.add_argument("--reviewed-b", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=BASE / "expert_review")
    args = parser.parse_args()
    aggregate(args.reviewed_a, args.reviewed_b, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
