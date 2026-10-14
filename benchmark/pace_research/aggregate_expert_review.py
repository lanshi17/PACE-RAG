"""专家双审记录汇总 v3（审计补正 §1–§3）：完整性契约、双方理由保留、
内容基准纳入材料绑定、工时缺失/非法明确报告。

用法：
    uv run python benchmark/pace_research/aggregate_expert_review.py \
        --reviewed-a PATH --reviewed-b PATH [--materials-dir DIR] [--out DIR]

输入：专家填写后的 review_package_A.json / review_package_B.json。
--materials-dir：材料目录（默认仓库 pace_conditions_v1）；测试用临时副本。

审核完成契约（§1）：
- 适用性判定必须为 Applicable/Inapplicable/Unknown；
- 必需陈述/禁止断言/应变项/应保持项（按变体要求）：每个元素必须是非空白
  字符串；"已审核且无此项"必须显式写 ["无"]，空列表视为尚未填写；
- 派生关系：判断非空且理由非空；
- 完成时间必须为 ISO 格式。

内容基准（§3）：从**已绑定材料**构造——dev_families.json 提供
家族/变体/题干/条件/证据 ID，evidence_candidates.json 提供证据摘录；
dual_review_template.json 不再作为基准。

状态（互斥，逐题）：
- incomplete_pending_completion  任一审核者记录未完成（不进 gold）
- pending_arbitration            双方已完成但存在分歧（含派生关系判断）
- agreed_pending_signoff         双方已完成且全部一致（进入 gold 草稿）

拒绝（SystemExit 非零）：材料哈希漂移、题集重复/遗漏、填写包内容漂移、
基准漂移。CLI 恒返回 0（拒绝路径除外）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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
APPLICABILITY_ENUM = {"Applicable", "Inapplicable", "Unknown"}
NONE_MARKER = "无"
EXPECTED_N = 27


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _build_baseline(materials_dir: Path) -> dict[str, dict[str, Any]]:
    """从已绑定材料构造内容基准（§3）：身份字段 + 证据摘录。"""
    dev = json.loads((materials_dir / "dev_families.json").read_text(encoding="utf-8"))
    cand = json.loads((materials_dir / "evidence_candidates.json").read_text(encoding="utf-8"))
    excerpt_by_id = {r["evidence_id"]: r["excerpt"] for r in cand["records"]}
    baseline: dict[str, dict[str, Any]] = {}
    for rec in dev["records"]:
        eids = rec.get("candidate_evidence_ids") or []
        evidence = [{"evidence_id": eid, "excerpt": excerpt_by_id[eid]} for eid in eids]
        for v in rec["variants"]:
            baseline[v["draft_question_id"]] = {
                "family_id": rec["scenario_family_id"],
                "variant_type": v["variant_type"],
                "question": v["question"],
                "known_conditions": v["known_conditions"],
                "evidence_ids": eids,
                "evidence": evidence,
            }
    return baseline


def _check_content_identity(
    pkg: dict[str, Any], baseline: dict[str, dict[str, Any]], src: str
) -> None:
    """填写包逐题核对家族/变体/题干/条件/证据（§2/§3 拒绝漂移）。"""
    for r in pkg["rows"]:
        qid = r["draft_question_id"]
        b = baseline[qid]
        for key in ("family_id", "variant_type", "question", "known_conditions"):
            assert r[key] == b[key], f"{src}: {qid}.{key} drifted from bound materials"
        got = r.get("evidence_excerpts") or []
        got_ids = [e.get("evidence_id") for e in got]
        assert got_ids == b["evidence_ids"], f"{src}: {qid} evidence ids drifted"
        for e in got:
            expected_excerpt = next(x["excerpt"] for x in b["evidence"] if x["evidence_id"] == e["evidence_id"])
            assert e.get("excerpt") == expected_excerpt, (
                f"{src}: {qid} evidence {e['evidence_id']} excerpt drifted"
            )


def _load_filled(
    path: Path, expect_reviewer: str, materials_dir: Path, baseline: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    pkg = json.loads(path.read_text(encoding="utf-8"))
    assert pkg["reviewer_id"] == expect_reviewer, f"{path}: reviewer_id={pkg['reviewer_id']}"
    # 材料哈希必须与绑定值一致（材料漂移拒绝）
    for f in MATERIAL_FILES:
        bound = pkg["material_version"]["files"][f]["sha256"]
        actual = _sha256_file(materials_dir / f)
        assert bound == actual, f"{path}: material hash mismatch for {f}"
    # 题目身份：27 个唯一 ID，无重复无遗漏
    got_ids = [r["draft_question_id"] for r in pkg["rows"]]
    assert len(got_ids) == EXPECTED_N, f"{path}: rows={len(got_ids)} != {EXPECTED_N}"
    dupes = [q for q, c in Counter(got_ids).items() if c > 1]
    assert not dupes, f"{path}: duplicate ids {dupes}"
    missing = sorted(set(baseline) - set(got_ids))
    extra = sorted(set(got_ids) - set(baseline))
    assert not missing and not extra, f"{path}: id set mismatch; missing={missing} extra={extra}"
    # 内容核验：与绑定材料构造的基准逐题比对
    _check_content_identity(pkg, baseline, str(path))
    return pkg


def _is_filled(v: Any) -> bool:
    if isinstance(v, str):
        return bool(v.strip())
    return v is not None


def _list_complete(v: Any) -> bool:
    """声明式列表完整性：空列表=尚未填写；元素必须是非空白字符串或"无"。"""
    if not isinstance(v, list) or len(v) == 0:
        return False
    return all(isinstance(x, str) and (x.strip() == NONE_MARKER or x.strip()) for x in v)


_ISO_SEPARATORS = ("T", " ")


def _valid_timestamp(v: Any) -> bool:
    if not isinstance(v, str) or not v.strip():
        return False
    s = v.strip()
    for sep in _ISO_SEPARATORS:
        if sep in s:
            try:
                datetime.fromisoformat(s.replace("Z", "+00:00"))
                return True
            except ValueError:
                return False
    return False


def _variant_required_fields(variant_type: str) -> list[str]:
    req: list[str] = []
    if variant_type == "condition_change":
        req.append("应变项")
    elif variant_type == "invariant_control":
        req.append("应保持项")
    return req


def _record_complete(r: dict[str, Any]) -> tuple[bool, list[str]]:
    """返回 (完整?, 缺失列表)（§1 契约）。"""
    missing: list[str] = []
    cf = r.get("clinical_fields") or {}
    app = cf.get("适用性判定")
    if not _is_filled(app):
        missing.append("适用性判定")
    elif app not in APPLICABILITY_ENUM:
        missing.append(f"适用性判定非法值:{app}")
    for field in ("必需陈述", "禁止断言"):
        if not _list_complete(cf.get(field)):
            missing.append(field if _is_filled(cf.get(field)) else f"{field}(未填写)")
    for field in _variant_required_fields(r["variant_type"]):
        v = (r.get("conditional_fields") or {}).get(field)
        if not _list_complete(v):
            missing.append(field if _is_filled(v) else f"{field}(未填写)")
    dr = r.get("derived_relationship") or {}
    if not _is_filled(dr.get("判断")):
        missing.append("派生关系判断")
    if not _is_filled(dr.get("理由")):
        missing.append("派生关系理由")
    if not _is_filled(r.get("完成时间")):
        missing.append("完成时间")
    elif not _valid_timestamp(r.get("完成时间")):
        missing.append("完成时间格式非法")
    return (not missing, missing)


def _parse_minutes(v: Any) -> tuple[str, float | None]:
    """工时解析（缺失/非法明确报告，不静默归零）。"""
    if v is None or (isinstance(v, str) and not v.strip()):
        return ("missing", None)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ("invalid", None)
    if not math.isfinite(f) or f < 0:
        return ("invalid", None)
    return ("ok", f)


def _diffs(ra: dict[str, Any], rb: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    pairs = [
        ("适用性判定", ra["clinical_fields"].get("适用性判定"), rb["clinical_fields"].get("适用性判定")),
        ("必需陈述", ra["clinical_fields"].get("必需陈述"), rb["clinical_fields"].get("必需陈述")),
        ("禁止断言", ra["clinical_fields"].get("禁止断言"), rb["clinical_fields"].get("禁止断言")),
        ("应变项", ra["conditional_fields"].get("应变项"), rb["conditional_fields"].get("应变项")),
        ("应保持项", ra["conditional_fields"].get("应保持项"), rb["conditional_fields"].get("应保持项")),
        (
            "派生关系",
            {"判断": (ra.get("derived_relationship") or {}).get("判断"),
             "理由": (ra.get("derived_relationship") or {}).get("理由")},
            {"判断": (rb.get("derived_relationship") or {}).get("判断"),
             "理由": (rb.get("derived_relationship") or {}).get("理由")},
        ),
    ]
    for key, fa, fb in pairs:
        if fa != fb:
            out.append({"field": key, "reviewer_A": fa, "reviewer_B": fb})
    return out


def aggregate(path_a: Path, path_b: Path, out_dir: Path, materials_dir: Path) -> dict[str, Any]:
    baseline = _build_baseline(materials_dir)
    assert len(baseline) == EXPECTED_N, f"baseline has {len(baseline)} questions != {EXPECTED_N}"
    pkg_a = _load_filled(path_a, "A", materials_dir, baseline)
    pkg_b = _load_filled(path_b, "B", materials_dir, baseline)
    rows_a = {r["draft_question_id"]: r for r in pkg_a["rows"]}
    rows_b = {r["draft_question_id"]: r for r in pkg_b["rows"]}
    filled_hashes = {"reviewer_A_file_sha256": _sha256_file(path_a), "reviewer_B_file_sha256": _sha256_file(path_b)}

    ovl = json.loads((materials_dir / "template_overlap_audit_v3.json").read_text(encoding="utf-8"))
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
        ok_a, miss_a = _record_complete(ra)
        ok_b, miss_b = _record_complete(rb)
        for who, r, ok, miss in (("A", ra, ok_a, miss_a), ("B", rb, ok_b, miss_b)):
            validation.append(
                {"draft_question_id": qid, "reviewer": who, "complete": ok, "missing": miss,
                 "input_file": f"{path_a.name if who == 'A' else path_b.name}#{qid}"}
            )
        for who, r in (("A", ra), ("B", rb)):
            state, minutes = _parse_minutes(r.get("耗时分钟"))
            worktime["per_question"].append(
                {"draft_question_id": qid, "reviewer": who, "state": state, "minutes": minutes}
            )
        if not (ok_a and ok_b):
            status = "incomplete_pending_completion"
        else:
            diffs = _diffs(ra, rb)
            if diffs:
                status = "pending_arbitration"
                disagreements.append(
                    {
                        "draft_question_id": qid,
                        "family_id": fid,
                        "priority": "high" if fid in flagged_families else "normal",
                        "input_files": {"reviewer_A": f"{path_a.name}#{qid}", "reviewer_B": f"{path_b.name}#{qid}"},
                        "items": diffs,
                        "arbitration": {"decision": "", "basis": "", "arbitrator": "", "时间": ""},
                    }
                )
            else:
                status = "agreed_pending_signoff"
                gold.append(
                    {
                        "draft_question_id": qid,
                        "family_id": fid,
                        "variant_type": ra["variant_type"],
                        "status": status,
                        "known_conditions": ra["known_conditions"],
                        "agreed": {
                            "适用性判定": ra["clinical_fields"].get("适用性判定"),
                            "必需陈述": ra["clinical_fields"].get("必需陈述"),
                            "禁止断言": ra["clinical_fields"].get("禁止断言"),
                            "应变项": ra["conditional_fields"].get("应变项"),
                            "应保持项": ra["conditional_fields"].get("应保持项"),
                            "派生关系判断": (ra.get("derived_relationship") or {}).get("判断"),
                            "派生关系理由": (ra.get("derived_relationship") or {}).get("理由"),
                        },
                        "sources": {
                            "reviewer_A": f"{path_a.name}#{qid}",
                            "reviewer_B": f"{path_b.name}#{qid}",
                            **filled_hashes,
                        },
                    }
                )
        status_counter[status] += 1
        family_rows.setdefault(fid, []).append({"draft_question_id": qid, "status": status})

    valid_minutes = [x["minutes"] for x in worktime["per_question"] if x["state"] == "ok"]
    worktime["totals"] = {
        "valid_records": len(valid_minutes),
        "missing_records": sum(1 for x in worktime["per_question"] if x["state"] == "missing"),
        "invalid_records": sum(1 for x in worktime["per_question"] if x["state"] == "invalid"),
        "minutes_total": sum(valid_minutes),
        "minutes_A": sum(x["minutes"] for x in worktime["per_question"] if x["state"] == "ok" and x["reviewer"] == "A"),
        "minutes_B": sum(x["minutes"] for x in worktime["per_question"] if x["state"] == "ok" and x["reviewer"] == "B"),
    }
    family_status = {
        fid: {
            "flagged_for_adjudication": fid in flagged_families,
            "n_pending_arbitration": sum(1 for r in rows if r["status"] == "pending_arbitration"),
            "rows": rows,
        }
        for fid, rows in family_rows.items()
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = {"generated_at": datetime.now().isoformat(), "gold_frozen": False, "hidden_questions": 0, **filled_hashes}
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
    (out_dir / "worktime_summary.json").write_text(json.dumps({**worktime, **stamp}, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "gold_draft.json").write_text(
        json.dumps({"summary": {"n_questions": len(gold), "status_counts": dict(status_counter)}, "questions": gold, **stamp}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"records: {len(validation)} | statuses: {dict(status_counter)} | "
        f"worktime valid={worktime['totals']['valid_records']} "
        f"missing={worktime['totals']['missing_records']} invalid={worktime['totals']['invalid_records']}"
    )
    print(f"wrote 5 files to {out_dir}（gold 未冻结，隐藏题仍为 0）")
    return {"records": len(validation), "status_counts": dict(status_counter)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewed-a", type=Path, required=True)
    parser.add_argument("--reviewed-b", type=Path, required=True)
    parser.add_argument("--materials-dir", type=Path, default=BASE)
    parser.add_argument("--out", type=Path, default=BASE / "expert_review")
    args = parser.parse_args()
    aggregate(args.reviewed_a, args.reviewed_b, args.out, args.materials_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
