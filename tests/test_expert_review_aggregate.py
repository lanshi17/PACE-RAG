"""专家审核汇总工具 v3 的针对性测试（测试数据，非真实审核记录）。

场景：空白双包、单方缺项、仅派生判断不同（含理由逐字断言）、
重复 ID／内容漂移／基准漂移（临时材料副本，不改仓库文件）、
完整一致标注逐字段导出 + 真实文件哈希、非法工时、部分填写与明确无项。
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "benchmark/qa/dataset/pace_conditions_v1"
TOOL = REPO / "benchmark/pace_research/aggregate_expert_review.py"
NOW = "2026-10-14T10:00:00"
REASON_A = "基于 ISUOG 条款独立判断（测试数据）"
REASON_B = "审核者 B 的替代理由（测试数据）"


def _make_materials(tmp: Path) -> Path:
    """材料临时副本（漂移测试不触碰仓库文件）。"""
    mdir = tmp / "materials"
    mdir.mkdir()
    for f in ("dev_families.json", "evidence_candidates.json", "template_overlap_audit_v3.json", "legacy_exposure_inventory.json"):
        shutil.copy(BASE / f, mdir / f)
    return mdir


def _bind_hashes(pkg: dict, mdir: Path) -> None:
    for f in ("dev_families.json", "evidence_candidates.json", "template_overlap_audit_v3.json", "legacy_exposure_inventory.json"):
        pkg["material_version"]["files"][f]["sha256"] = hashlib.sha256((mdir / f).read_bytes()).hexdigest()


def _filled_row(r: dict, *, applicability="Applicable", required=None, forbidden=None,
                change=None, keep=None, derived="independent", reason=REASON_A,
                minutes="10.5", when=NOW):
    """构造一份**完整**的模拟审核记录。缺省按变体要求填满；"无项"用 ["无"]。"""
    if change is None and r["variant_type"] == "condition_change":
        change = ["测试应变项"]
    if keep is None and r["variant_type"] == "invariant_control":
        keep = ["测试应保持项"]
    r["clinical_fields"] = {
        "适用性判定": applicability,
        "必需陈述": required if required is not None else ["无"],
        "禁止断言": forbidden if forbidden is not None else ["无"],
    }
    r["conditional_fields"] = {"应变项": change if change is not None else (["无"] if r["variant_type"] != "condition_change" else []),
                               "应保持项": keep if keep is not None else (["无"] if r["variant_type"] != "invariant_control" else [])}
    r["derived_relationship"] = {"判断": derived, "理由": reason}
    r["耗时分钟"] = minutes
    r["完成时间"] = when


def _make_filled(tmp: Path, who: str, mutate=None, mdir: Path | None = None) -> Path:
    pkg = json.loads((BASE / f"review_package_{who}.json").read_text(encoding="utf-8"))
    for r in pkg["rows"]:
        _filled_row(r)
    if mutate:
        mutate(pkg, who)
    if mdir is not None:
        _bind_hashes(pkg, mdir)
    p = tmp / f"filled_{who}.json"
    p.write_text(json.dumps(pkg, ensure_ascii=False), encoding="utf-8")
    return p


def _run(tmp: Path, pa: Path, pb: Path, out="out", mdir: Path | None = None):
    cmd = [sys.executable, str(TOOL), "--reviewed-a", str(pa), "--reviewed-b", str(pb), "--out", str(tmp / out)]
    if mdir is not None:
        cmd += ["--materials-dir", str(mdir)]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)


def _statuses(tmp: Path, out="out") -> dict:
    return json.loads((tmp / out / "family_status_table.json").read_text(encoding="utf-8"))["status_counts"]


def test_blank_packages_yield_incomplete_not_gold() -> None:
    """空白双包：27 题全部待补全，不进 gold，工时 54 条缺失。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        mdir = _make_materials(tmp)

        def blank(pkg, _who):
            for r in pkg["rows"]:
                r["clinical_fields"] = {"适用性判定": "", "必需陈述": [], "禁止断言": []}
                r["conditional_fields"] = {"应变项": [], "应保持项": []}
                r["derived_relationship"] = {"判断": "", "理由": ""}
                r["耗时分钟"] = ""
                r["完成时间"] = ""

        pa = _make_filled(tmp, "A", blank, mdir)
        pb = _make_filled(tmp, "B", blank, mdir)
        result = _run(tmp, pa, pb, mdir=mdir)
        assert result.returncode == 0
        assert _statuses(tmp) == {"incomplete_pending_completion": 27}
        gold = json.loads((tmp / "out" / "gold_draft.json").read_text(encoding="utf-8"))
        assert gold["summary"]["n_questions"] == 0
        wt = json.loads((tmp / "out" / "worktime_summary.json").read_text(encoding="utf-8"))
        assert wt["totals"]["missing_records"] == 54 and wt["totals"]["valid_records"] == 0


def test_base_question_with_empty_fields_is_incomplete() -> None:
    """§1 反例：base 题只填适用性和时间、其余留空 → 未完成，不进 gold。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        mdir = _make_materials(tmp)

        def lax(pkg, _who):
            for r in pkg["rows"]:
                if r["variant_type"] == "base":
                    r["clinical_fields"] = {"适用性判定": "Applicable", "必需陈述": [], "禁止断言": []}
                    r["derived_relationship"] = {"判断": "", "理由": ""}
                    r["完成时间"] = NOW

        pa = _make_filled(tmp, "A", lax, mdir)
        pb = _make_filled(tmp, "B", lax, mdir)
        result = _run(tmp, pa, pb, mdir=mdir)
        assert result.returncode == 0
        counts = _statuses(tmp)
        assert counts["incomplete_pending_completion"] == 9  # 9 道 base 题全部未完成
        assert counts["agreed_pending_signoff"] == 18  # 其余按缺省完整填写


def test_explicit_none_marker_distinct_from_blank() -> None:
    """§1 正例：["无"]（明确无项）完整；[""]（空白字符串）不完整。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        mdir = _make_materials(tmp)

        def mixed(pkg, _who):
            # 第 1 题：["无"] → 完整；第 2 题：[""] → 不完整
            pkg["rows"][1]["clinical_fields"]["禁止断言"] = [""]

        pa = _make_filled(tmp, "A", mixed, mdir)
        pb = _make_filled(tmp, "B", mixed, mdir)
        result = _run(tmp, pa, pb, mdir=mdir)
        assert result.returncode == 0
        counts = _statuses(tmp)
        assert counts == {"incomplete_pending_completion": 1, "agreed_pending_signoff": 26}
        val = json.loads((tmp / "out" / "validation_report.json").read_text(encoding="utf-8"))
        bad = [x for x in val["rows"] if not x["complete"]]
        assert len(bad) == 2  # A、B 各 1 条
        assert any("禁止断言" in m for x in bad for m in x["missing"])


def test_partial_fill_is_incomplete() -> None:
    """§1 部分填写：B 第 1 题缺派生理由 → 待补全。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        mdir = _make_materials(tmp)

        def partial(pkg, who):
            if who == "B":
                pkg["rows"][0]["derived_relationship"]["理由"] = ""

        pa = _make_filled(tmp, "A", None, mdir)
        pb = _make_filled(tmp, "B", partial, mdir)
        result = _run(tmp, pa, pb, mdir=mdir)
        assert result.returncode == 0
        counts = _statuses(tmp)
        assert counts == {"incomplete_pending_completion": 1, "agreed_pending_signoff": 26}


def test_derived_diff_keeps_both_reasons_verbatim() -> None:
    """§2：仅派生判断不同 → 仲裁日志逐字保留双方理由与输入文件引用。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        mdir = _make_materials(tmp)

        def diff(pkg, who):
            if who == "B":
                pkg["rows"][0]["derived_relationship"] = {"判断": "derived", "理由": REASON_B}

        pa = _make_filled(tmp, "A", None, mdir)
        pb = _make_filled(tmp, "B", diff, mdir)
        result = _run(tmp, pa, pb, mdir=mdir)
        assert result.returncode == 0
        counts = _statuses(tmp)
        assert counts["pending_arbitration"] == 1
        dg = json.loads((tmp / "out" / "disagreement_log.json").read_text(encoding="utf-8"))
        item = dg["items"][0]
        entry = item["items"][0]
        assert entry["field"] == "派生关系"
        # 双方理由逐字保留
        assert entry["reviewer_A"]["判断"] == "independent"
        assert entry["reviewer_A"]["理由"] == REASON_A
        assert entry["reviewer_B"]["判断"] == "derived"
        assert entry["reviewer_B"]["理由"] == REASON_B
        # 输入文件引用
        assert item["input_files"]["reviewer_A"].endswith("#" + item["draft_question_id"])
        assert item["input_files"]["reviewer_B"].endswith("#" + item["draft_question_id"])


def test_duplicate_and_content_drift_rejected(tmp_path: Path) -> None:
    """重复 ID 与填写包内容漂移（题干/证据）都必须拒绝。"""
    mdir = _make_materials(tmp_path)

    def dupe(pkg, who):
        if who == "A":
            pkg["rows"][1]["draft_question_id"] = pkg["rows"][0]["draft_question_id"]

    pa = _make_filled(tmp_path, "A", dupe, mdir)
    pb = _make_filled(tmp_path, "B", None, mdir)
    assert _run(tmp_path, pa, pb, out="o1", mdir=mdir).returncode != 0

    def drift_question(pkg, who):
        if who == "A":
            pkg["rows"][0]["question"] = pkg["rows"][0]["question"] + "【漂移】"

    pa2 = _make_filled(tmp_path, "A", drift_question, mdir)
    pb2 = _make_filled(tmp_path, "B", None, mdir)
    assert _run(tmp_path, pa2, pb2, out="o2", mdir=mdir).returncode != 0

    def drift_evidence(pkg, who):
        if who == "B":
            pkg["rows"][0]["evidence_excerpts"][0]["excerpt"] += "【漂移】"

    pa3 = _make_filled(tmp_path, "A", None, mdir)
    pb3 = _make_filled(tmp_path, "B", drift_evidence, mdir)
    assert _run(tmp_path, pa3, pb3, out="o3", mdir=mdir).returncode != 0


def test_baseline_drift_rejected(tmp_path: Path) -> None:
    """基准漂移：材料副本被改且绑定哈希同步更新 → 基准比对仍拒绝。"""
    mdir = _make_materials(tmp_path)
    dev = json.loads((mdir / "dev_families.json").read_text(encoding="utf-8"))
    dev["records"][0]["variants"][0]["question"] += "【基准漂移】"
    (mdir / "dev_families.json").write_text(json.dumps(dev, ensure_ascii=False), encoding="utf-8")

    pa = _make_filled(tmp_path, "A", None, mdir)
    pb = _make_filled(tmp_path, "B", None, mdir)
    result = _run(tmp_path, pa, pb, out="o1", mdir=mdir)
    assert result.returncode != 0
    assert "drifted" in result.stderr


def test_full_agreement_exports_complete_gold_with_real_hashes(tmp_path: Path) -> None:
    """完整一致：gold 逐字段导出 + 绑定真实填写文件哈希（内容级核对）。"""
    mdir = _make_materials(tmp_path)
    pa = _make_filled(tmp_path, "A", None, mdir)
    pb = _make_filled(tmp_path, "B", None, mdir)
    result = _run(tmp_path, pa, pb, out="o1", mdir=mdir)
    assert result.returncode == 0
    assert _statuses(tmp_path, "o1") == {"agreed_pending_signoff": 27}
    gold = json.loads((tmp_path / "o1" / "gold_draft.json").read_text(encoding="utf-8"))
    assert gold["summary"]["n_questions"] == 27
    q = gold["questions"][0]
    # 逐字段断言导出值
    assert q["agreed"]["适用性判定"] == "Applicable"
    assert q["agreed"]["必需陈述"] == ["无"]
    assert q["agreed"]["禁止断言"] == ["无"]
    if q["variant_type"] == "condition_change":
        assert q["agreed"]["应变项"] == ["测试应变项"]
        assert q["agreed"]["应保持项"] == ["无"]
    elif q["variant_type"] == "invariant_control":
        assert q["agreed"]["应变项"] == ["无"]
        assert q["agreed"]["应保持项"] == ["测试应保持项"]
    else:
        assert q["agreed"]["应变项"] == ["无"]
        assert q["agreed"]["应保持项"] == ["无"]
    assert q["agreed"]["派生关系判断"] == "independent"
    assert q["agreed"]["派生关系理由"] == REASON_A
    # 真实文件哈希（重算比对，不只查长度）
    assert q["sources"]["reviewer_A_file_sha256"] == hashlib.sha256(pa.read_bytes()).hexdigest()
    assert q["sources"]["reviewer_B_file_sha256"] == hashlib.sha256(pb.read_bytes()).hexdigest()


def test_invalid_worktime_reported_not_zeroed(tmp_path: Path) -> None:
    """非法/缺失工时：明确报告，不参与合计；非法时间格式 → 待补全。"""
    mdir = _make_materials(tmp_path)

    def bad(pkg, who):
        if who == "A":
            pkg["rows"][0]["耗时分钟"] = "-3"
            pkg["rows"][1]["耗时分钟"] = "abc"
            pkg["rows"][2]["耗时分钟"] = ""
            pkg["rows"][3]["完成时间"] = "yesterday"

    pa = _make_filled(tmp_path, "A", bad, mdir)
    pb = _make_filled(tmp_path, "B", None, mdir)
    result = _run(tmp_path, pa, pb, out="o1", mdir=mdir)
    assert result.returncode == 0
    wt = json.loads((tmp_path / "o1" / "worktime_summary.json").read_text(encoding="utf-8"))
    totals = wt["totals"]
    assert totals["invalid_records"] == 2
    assert totals["missing_records"] == 1
    assert totals["valid_records"] == 51
    assert totals["minutes_total"] == pytest.approx(51 * 10.5)
    counts = _statuses(tmp_path, "o1")
    assert counts["incomplete_pending_completion"] == 1
    assert counts["agreed_pending_signoff"] == 26


@pytest.mark.parametrize(
    "value",
    ["", "   ", [], ["非空"], {}, {"判断": "x"}, 0, 1, True, False],
)
def test_non_text_derived_fields_are_incomplete(tmp_path: Path, value) -> None:
    """派生判断/理由只接受非空白字符串；列表、对象、数字、布尔一律待补全。"""
    mdir = _make_materials(tmp_path)

    def bad(pkg, who):
        if who == "A":
            pkg["rows"][0]["derived_relationship"]["判断"] = value
            pkg["rows"][0]["derived_relationship"]["理由"] = value

    pa = _make_filled(tmp_path, "A", bad, mdir)
    pb = _make_filled(tmp_path, "B", None, mdir)
    result = _run(tmp_path, pa, pb, out="o1", mdir=mdir)
    assert result.returncode == 0
    counts = _statuses(tmp_path, "o1")
    assert counts == {"incomplete_pending_completion": 1, "agreed_pending_signoff": 26}
    val = json.loads((tmp_path / "o1" / "validation_report.json").read_text(encoding="utf-8"))
    row = next(x for x in val["rows"] if not x["complete"])
    assert "派生关系判断" in row["missing"] and "派生关系理由" in row["missing"]


def test_normal_text_derived_fields_pass(tmp_path: Path) -> None:
    """正例：正常文本的派生判断/理由通过完整性检查。"""
    mdir = _make_materials(tmp_path)
    pa = _make_filled(tmp_path, "A", None, mdir)
    pb = _make_filled(tmp_path, "B", None, mdir)
    result = _run(tmp_path, pa, pb, out="o1", mdir=mdir)
    assert result.returncode == 0
    assert _statuses(tmp_path, "o1") == {"agreed_pending_signoff": 27}


@pytest.mark.parametrize(
    ("key", "value"),
    [("anchor_id", "999999"), ("page", "999-999")],
)
def test_anchor_and_page_drift_rejected(tmp_path: Path, key: str, value: str) -> None:
    """锚点/页码与绑定的 evidence_candidates.json 不一致 → 拒绝（CLI 非零退出，指明字段）。"""
    mdir = _make_materials(tmp_path)

    def drift(pkg, who):
        if who == "A":
            pkg["rows"][0]["evidence_excerpts"][0][key] = value

    pa = _make_filled(tmp_path, "A", drift, mdir)
    pb = _make_filled(tmp_path, "B", None, mdir)
    result = _run(tmp_path, pa, pb, out="o1", mdir=mdir)
    assert result.returncode != 0
    assert f"{key} drifted from bound materials" in result.stderr


def test_anchor_page_expected_values_come_from_bound_candidates(tmp_path: Path) -> None:
    """未篡改的填写包通过；预期锚点/页码来自绑定候选文件（E-AMNIO → 440, 1-1）。"""
    mdir = _make_materials(tmp_path)
    pa = _make_filled(tmp_path, "A", None, mdir)
    pb = _make_filled(tmp_path, "B", None, mdir)
    assert _run(tmp_path, pa, pb, out="o1", mdir=mdir).returncode == 0
    ev = json.loads(pa.read_text(encoding="utf-8"))["rows"][0]["evidence_excerpts"][0]
    assert (ev["anchor_id"], ev["page"]) == ("440", "1-1")
