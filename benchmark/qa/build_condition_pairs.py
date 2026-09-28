"""PACE 条件配对题集生成器（§8.1，15 组变体）。

从 `sample_questions.json` 选 15 个基底问题，各派生两个 GA 变体——
`matched`（孕周子句与基底自然检查时点一致，B1 过滤几乎不剔除）与
`mismatched`（孕周子句远移第三孕周，B1 过滤应剔除大量明确不适用片段）。

设计要点：
- 变体只改**查询条件子句**，核心题面与基底共享；gold_answer / gold_sources /
  must_have_statements / gold_entities / gold_relations 从基底**逐字复制**，
  不新造任何临床内容；
- 全 GA 轴（配对题集的目的：让 B1 的显式条件过滤"可见"）。人群/技术轴在
  本语料上大量 Unknown（未标注 → 永不丢弃），作为诚实发现写进批次文档；
- 每个变体带 `variant_group` / `variant_role` / `window_label` /
  `condition_note` 元数据（`Question.from_dict` 忽略多余键，探针读取）。

自检（构建即断言，失败则退出非零）：
1) 15 组、每组恰 2 变体；
2) 每个变体的 `parse_query_conditions` 抽出的孕周窗 == 声明的 window_label；
3) 每个变体的 gold_sources 全部落在证据真值层语料 source_ids 内。

Usage (repo root):
    PYTHONPATH=. .venv/bin/python benchmark/qa/build_condition_pairs.py [--out PATH]
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from prenatal_rag.conditions import parse_query_conditions
from prenatal_rag.evidence_store import EvidenceStore

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = REPO_ROOT / "benchmark/qa/dataset/sample_questions.json"
DEFAULT_OUT = REPO_ROOT / "benchmark/qa/dataset/condition_pairs.json"
EVIDENCE_STORE_DIR = REPO_ROOT / "benchmark/data/evidence_store"

# window_label -> GaWindow 天数（含边界）
WINDOW_DAYS = {
    "11-14 weeks": (77, 98),
    "18-24 weeks": (126, 168),
    "32-36 weeks": (224, 252),
}

# (group_id, base_id, matched, mismatched, window_label_m, window_label_x, note)
GROUPS: list[tuple[str, str, str, str, str, str, str]] = [
    (
        "CP-01",
        "PU-L1-001",
        "At 11 to 14 weeks of gestation, what crown-rump length (CRL) range is "
        "required when measuring nuchal translucency (NT)?",
        "At 32 to 36 weeks of gestation, what crown-rump length (CRL) range is "
        "required when measuring nuchal translucency (NT)?",
        "11-14 weeks",
        "32-36 weeks",
        "NT/CRL 测量是一孕周专属；把查询孕周远移到第三孕周应使首孕周证据全部不适用。",
    ),
    (
        "CP-02",
        "PU-L1-002",
        "At 18 to 24 weeks of gestation, which structures should be assessed in "
        "the four-chamber view?",
        "At 32 to 36 weeks of gestation, which structures should be assessed in "
        "the four-chamber view?",
        "18-24 weeks",
        "32-36 weeks",
        "四腔心为中孕基本切面；远移第三孕周后中孕切面证据应转为不适用。",
    ),
    (
        "CP-03",
        "PU-L1-013",
        "At the 18 to 24 week scan, what renal pelvis measurement should prompt "
        "reassessment?",
        "At the 32 to 36 week scan, what renal pelvis measurement should prompt "
        "reassessment?",
        "18-24 weeks",
        "32-36 weeks",
        "肾盂测量标准是中孕筛查语境；第三孕周变体应触发大量不适用。",
    ),
    (
        "CP-04",
        "PU-L1-008",
        "At 18 to 24 weeks of gestation, if gestational age was not established "
        "in the first trimester, which parameters are preferred for dating?",
        "At 32 to 36 weeks of gestation, if gestational age was not established "
        "in the first trimester, which parameters are preferred for dating?",
        "18-24 weeks",
        "32-36 weeks",
        "孕周校正参数语境为中/晚孕；远移第三孕周验证过滤方向。",
    ),
    (
        "CP-05",
        "PU-L1-011",
        "At 18 to 24 weeks of gestation, which views are included in the fetal "
        "cardiac screening examination?",
        "At 32 to 36 weeks of gestation, which views are included in the fetal "
        "cardiac screening examination?",
        "18-24 weeks",
        "32-36 weeks",
        "胎儿心脏筛查为中孕检查；第三孕周变体应使中孕切面证据不适用。",
    ),
    (
        "CP-06",
        "PU-L1-012",
        "At 18 to 24 weeks of gestation, what does the normal three-vessel view "
        "(3VV) show?",
        "At 32 to 36 weeks of gestation, what does the normal three-vessel view "
        "(3VV) show?",
        "18-24 weeks",
        "32-36 weeks",
        "三血管切面为中孕标准切面；第三孕周变体触发过滤。",
    ),
    (
        "CP-07",
        "PU-L1-014",
        "At the 18 to 24 week scan, which placental findings indicate the need "
        "for third-trimester follow-up?",
        "At the 32 to 36 week scan, which placental findings indicate the need "
        "for third-trimester follow-up?",
        "18-24 weeks",
        "32-36 weeks",
        "胎盘位置评估原为中孕；把查询放到第三孕周制造条件错配。",
    ),
    (
        "CP-08",
        "PU-L2-018",
        "At 11 to 14 weeks of gestation, what is the minimum set of stored planes "
        "for first-trimester screening?",
        "At 32 to 36 weeks of gestation, what is the minimum set of stored planes "
        "for first-trimester screening?",
        "11-14 weeks",
        "32-36 weeks",
        "一孕周留存切面是一孕周专属要求；第三孕周变体应全部不适用。",
    ),
    (
        "CP-09",
        "PU-L2-028",
        "At 11 to 14 weeks of gestation, what is the role of color Doppler in "
        "early fetal cardiac assessment?",
        "At 32 to 36 weeks of gestation, what is the role of color Doppler in "
        "early fetal cardiac assessment?",
        "11-14 weeks",
        "32-36 weeks",
        "早孕期彩色多普勒是一孕周专属；远移第三孕周验证过滤。",
    ),
    (
        "CP-10",
        "PU-L2-029",
        "At 11 to 14 weeks of gestation, how should an increased nuchal "
        "translucency measurement be interpreted?",
        "At 32 to 36 weeks of gestation, how should an increased nuchal "
        "translucency measurement be interpreted?",
        "11-14 weeks",
        "32-36 weeks",
        "NT 增大解释是一孕周专属（NT 非三孕周筛查项目）；远移第三孕周应强触发。",
    ),
    (
        "CP-11",
        "PU-L2-030",
        "At 11 to 14 weeks of gestation, what is the role of the nasal bone in "
        "first-trimester screening?",
        "At 32 to 36 weeks of gestation, what is the role of the nasal bone in "
        "first-trimester screening?",
        "11-14 weeks",
        "32-36 weeks",
        "鼻骨是一孕周筛查标志；第三孕周变体应使一孕周证据不适用。",
    ),
    (
        "CP-12",
        "PU-L2-031",
        "At 11 to 14 weeks of gestation, what is the role of ductus venosus (DV) "
        "flow assessment?",
        "At 32 to 36 weeks of gestation, what is the role of ductus venosus (DV) "
        "flow assessment?",
        "11-14 weeks",
        "32-36 weeks",
        "静脉导管血流评估是一孕周项目；远移第三孕周验证过滤。",
    ),
    (
        "CP-13",
        "PU-L2-032",
        "At 11 to 14 weeks of gestation, what should be documented about the "
        "fetal bladder?",
        "At 32 to 36 weeks of gestation, what should be documented about the "
        "fetal bladder?",
        "11-14 weeks",
        "32-36 weeks",
        "膀胱检查内容随孕周变化（11–14 周口径 vs 晚孕口径）；远移验证过滤。",
    ),
    (
        "CP-14",
        "PU-L3-031",
        "At 18 to 24 weeks of gestation, what is the clinical significance of an "
        "abnormal fetal cardiac axis?",
        "At 32 to 36 weeks of gestation, what is the clinical significance of an "
        "abnormal fetal cardiac axis?",
        "18-24 weeks",
        "32-36 weeks",
        "心脏轴异常评估为中孕心筛语境；第三孕周变体触发过滤。",
    ),
    (
        "CP-15",
        "PU-L3-026",
        "At 11 to 14 weeks of gestation, how do ISUOG and Chinese guidelines "
        "differ in their minimum requirements for first-trimester structural "
        "examination?",
        "At 32 to 36 weeks of gestation, how do ISUOG and Chinese guidelines "
        "differ in their minimum requirements for first-trimester structural "
        "examination?",
        "11-14 weeks",
        "32-36 weeks",
        "一孕周最低要求对比是一孕周语境；远移第三孕周验证过滤。",
    ),
]

# 复制到变体的基底字段（逐字拷贝，不改造）
COPY_FIELDS = [
    "question_type",
    "difficulty",
    "rag_arch_type",
    "kg_hops",
    "clinical_scenario",
    "gold_answer",
    "gold_entities",
    "gold_relations",
    "gold_sources",
    "must_have_statements",
    "safety_flags",
]


def main(out_path: Path) -> None:
    source = json.loads(DEFAULT_SOURCE.read_text(encoding="utf-8"))
    base = {q["question_id"]: q for q in source}

    store = EvidenceStore(EVIDENCE_STORE_DIR)
    corpus_sources = {c.source_id for c in store.iter_chunks()}

    variants: list[dict] = []
    for gid, bid, m_text, x_text, wm, wx, note in GROUPS:
        b = base[bid]
        for role, text, wlabel in (
            ("matched", m_text, wm),
            ("mismatched", x_text, wx),
        ):
            v: dict = copy.deepcopy({f: b[f] for f in COPY_FIELDS})
            v["question_id"] = f"{bid}-{gid.lower()}{'a' if role == 'matched' else 'b'}"
            v["question"] = text
            v["variant_group"] = gid
            v["variant_axis"] = "gestational_age"
            v["variant_role"] = role
            v["window_label"] = wlabel
            v["condition_note"] = note
            variants.append(v)

    # ── 自检 1+2：组数 / 条件可解析 ─────────────────────────────────
    groups = sorted({v["variant_group"] for v in variants})
    assert len(groups) == 15, f"组数应为 15，实际 {len(groups)}"
    for gid in groups:
        in_group = [v for v in variants if v["variant_group"] == gid]
        assert len(in_group) == 2, f"{gid} 应恰 2 变体，实际 {len(in_group)}"
    for v in variants:
        query = parse_query_conditions(v["question"])
        assert query.gestational_age is not None, (
            f"{v['question_id']} 未抽出孕周条件"
        )
        expected = WINDOW_DAYS[v["window_label"]]
        got = (query.gestational_age.lower_days, query.gestational_age.upper_days)
        assert got == expected, (
            f"{v['question_id']} 孕周 {got} != 声明 {expected}"
        )

    # ── 自检 3：gold 全部在语料 ─────────────────────────────────────
    missing: list[str] = []
    for v in variants:
        for s in v.get("gold_sources", []):
            g = s.get("guide", "")
            if g and g not in corpus_sources:
                missing.append(f"{v['question_id']}:{g}")
    assert not missing, f"gold_sources 不在语料: {missing}"

    out_path.write_text(
        json.dumps(variants, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {len(variants)} variants ({len(groups)} groups x2) -> {out_path}")
    for gid in groups:
        a = next(v for v in variants if v["variant_group"] == gid and v["variant_role"] == "matched")
        b = next(v for v in variants if v["variant_group"] == gid and v["variant_role"] == "mismatched")
        print(f"  {gid} {a['question_id'][:18]:18s} {a['window_label']:10s} vs "
              f"{b['question_id'][:18]:18s} {b['window_label']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    main(args.out)
