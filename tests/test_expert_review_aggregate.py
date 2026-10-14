"""专家审核汇总工具 v2 的针对性测试（测试数据，非真实审核记录）。

场景：空白双包、单方缺项、仅派生判断不同、重复 ID／材料漂移、
完整一致标注导出、非法工时。
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "benchmark/qa/dataset/pace_conditions_v1"
TOOL = REPO / "benchmark/pace_research/aggregate_expert_review.py"
NOW = "2026-10-14T10:00:00"


def _filled_row(r: dict, *, applicability="Applicable", required=None, forbidden=None,
                change=None, keep=None, derived="independent", minutes="10.5", when=NOW):
    """构造一份**完整**的模拟审核记录（明确为测试数据）。缺省按变体要求填满。"""
    if change is None and r["variant_type"] == "condition_change":
        change = ["测试应变项"]
    if keep is None and r["variant_type"] == "invariant_control":
        keep = ["测试应保持项"]
    r["clinical_fields"] = {"适用性判定": applicability, "必需陈述": required or [], "禁止断言": forbidden or []}
    r["conditional_fields"] = {"应变项": change or [], "应保持项": keep or []}
    r["derived_relationship"] = {"判断": derived, "理由": "测试数据"}
    r["耗时分钟"] = minutes
    r["完成时间"] = when


def _make_filled(tmp: Path, who: str, mutate=None) -> Path:
    pkg = json.loads((BASE / f"review_package_{who}.json").read_text(encoding="utf-8"))
    for r in pkg["rows"]:
        _filled_row(r)
    if mutate:
        mutate(pkg, who)
    p = tmp / f"filled_{who}.json"
    p.write_text(json.dumps(pkg, ensure_ascii=False), encoding="utf-8")
    return p


def _run(tmp: Path, pa: Path, pb: Path, out="out"):
    return subprocess.run(
        [sys.executable, str(TOOL), "--reviewed-a", str(pa), "--reviewed-b", str(pb), "--out", str(tmp / out)],
        capture_output=True, text=True, cwd=REPO,
    )


def _statuses(tmp: Path) -> dict:
    return json.loads((tmp / "out" / "family_status_table.json").read_text(encoding="utf-8"))["status_counts"]


def test_blank_packages_yield_incomplete_not_gold() -> None:
    """空白双包：27 题全部待补全，不进 gold，工时 54 条缺失。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        def blank(pkg, _who):
            for r in pkg["rows"]:
                r["clinical_fields"] = {"适用性判定": "", "必需陈述": [], "禁止断言": []}
                r["conditional_fields"] = {"应变项": [], "应保持项": []}
                r["derived_relationship"] = {"判断": ""}
                r["耗时分钟"] = ""
                r["完成时间"] = ""

        pa = _make_filled(tmp, "A", blank)
        pb = _make_filled(tmp, "B", blank)
        result = _run(tmp, pa, pb)
        assert result.returncode == 0
        counts = _statuses(tmp)
        assert counts == {"incomplete_pending_completion": 27}
        gold = json.loads((tmp / "out" / "gold_draft.json").read_text(encoding="utf-8"))
        assert gold["summary"]["n_questions"] == 0
        wt = json.loads((tmp / "out" / "worktime_summary.json").read_text(encoding="utf-8"))
        assert wt["totals"]["missing_records"] == 54 and wt["totals"]["valid_records"] == 0


def test_single_side_missing_field() -> None:
    """单方缺项：仅 B 第 1 题未填适用性 → 该题待补全，其余 26 题一致。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        def partial(pkg, who):
            if who == "B":
                pkg["rows"][0]["clinical_fields"]["适用性判定"] = ""

        pa = _make_filled(tmp, "A")
        pb = _make_filled(tmp, "B", partial)
        result = _run(tmp, pa, pb)
        assert result.returncode == 0
        counts = _statuses(tmp)
        assert counts == {"incomplete_pending_completion": 1, "agreed_pending_signoff": 26}


def test_derived_relationship_diff_arbitrated() -> None:
    """仅派生判断不同（其余字段一致）→ 进入仲裁，双方理由原样保留。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        def diff(pkg, _who):
            if _who == "B":
                pkg["rows"][0]["derived_relationship"] = {"判断": "derived", "理由": "审核者 B 测试理由"}

        pa = _make_filled(tmp, "A")
        pb = _make_filled(tmp, "B", diff)
        result = _run(tmp, pa, pb)
        assert result.returncode == 0
        counts = _statuses(tmp)
        assert counts["pending_arbitration"] == 1
        dg = json.loads((tmp / "out" / "disagreement_log.json").read_text(encoding="utf-8"))
        item = dg["items"][0]
        assert item["items"][0]["field"] == "派生关系判断"
        assert item["items"][0]["reviewer_A"] == "independent"
        assert item["items"][0]["reviewer_B"] == "derived"
        gold = json.loads((tmp / "out" / "gold_draft.json").read_text(encoding="utf-8"))
        assert gold["summary"]["n_questions"] == 26


def test_duplicate_id_and_material_drift_rejected() -> None:
    """重复 ID 与材料漂移都必须拒绝（非零退出）。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        def dupe(pkg, who):
            if who == "A":
                pkg["rows"][1]["draft_question_id"] = pkg["rows"][0]["draft_question_id"]

        pa = _make_filled(tmp, "A", dupe)
        pb = _make_filled(tmp, "B")
        assert _run(tmp, pa, pb, out="o1").returncode != 0

        # 材料漂移：篡改绑定文件后汇总必须拒绝
        material = BASE / "dev_families.json"
        original = material.read_bytes()
        try:
            material.write_bytes(original + b"\n")
            pa2 = _make_filled(tmp, "A")
            pb2 = _make_filled(tmp, "B")
            assert _run(tmp, pa2, pb2, out="o2").returncode != 0
        finally:
            material.write_bytes(original)


def test_full_agreement_exports_complete_gold_with_hashes() -> None:
    """完整一致：27 题全一致，gold 导出全部必要标注并绑定双方文件哈希。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pa = _make_filled(tmp, "A")
        pb = _make_filled(tmp, "B")
        result = _run(tmp, pa, pb)
        assert result.returncode == 0
        assert _statuses(tmp) == {"agreed_pending_signoff": 27}
        gold = json.loads((tmp / "out" / "gold_draft.json").read_text(encoding="utf-8"))
        assert gold["summary"]["n_questions"] == 27
        q = gold["questions"][0]
        assert q["agreed"]["适用性判定"] == "Applicable"
        assert q["agreed"]["必需陈述"] == ["S1"] or q["agreed"]["必需陈述"] == []
        assert "派生关系判断" in q["agreed"]
        assert len(q["sources"]["reviewer_A_file_sha256"]) == 64
        assert len(q["sources"]["reviewer_B_file_sha256"]) == 64


def test_invalid_worktime_reported_not_zeroed() -> None:
    """非法/缺失工时：明确报告，不参与合计；非法时间格式 → 待补全。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        def bad(pkg, who):
            pkg["rows"][0]["耗时分钟"] = "-3"
            pkg["rows"][1]["耗时分钟"] = "abc"
            pkg["rows"][2]["耗时分钟"] = ""
            pkg["rows"][3]["完成时间"] = "yesterday"

        pa = _make_filled(tmp, "A", bad)
        pb = _make_filled(tmp, "B")
        result = _run(tmp, pa, pb)
        assert result.returncode == 0
        wt = json.loads((tmp / "out" / "worktime_summary.json").read_text(encoding="utf-8"))
        totals = wt["totals"]
        # A 包 4 条异常（3 非法 + 1 缺失），B 包 54-4 条有效
        assert totals["invalid_records"] == 2
        assert totals["missing_records"] == 1
        assert totals["valid_records"] == 51
        assert totals["minutes_total"] == pytest.approx(51 * 10.5)
        # 第 4 题时间格式非法 → 待补全
        counts = _statuses(tmp)
        assert counts["incomplete_pending_completion"] == 1
        assert counts["agreed_pending_signoff"] == 26
