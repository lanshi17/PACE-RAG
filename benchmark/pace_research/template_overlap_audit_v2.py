"""重叠审计 v2：启发式候选分数（术语+数字 jaccard），按家族组织复核。

修正（审计补正 §3）：
- 分数更名为"启发式候选分数"，不称"语义重叠的保守下界"；
- 中英同义词映射到统一概念（术语表扩充为概念 ID）；
- 孕周/数值统一表达后再比对；
- 高分不直接判定派生，低分不证明独立——全部家族保留人工语义复核要求；
- 当前 4 个命中涉及 2 个家族、6 个变体 → **整家族 2 个标记待裁定**；
  其余 7 个家族同样保留人工语义复核要求（不是豁免）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]

# 概念 ID → 中英同义词集。特征提取映射到概念 ID（语言无关）。
CONCEPTS: dict[str, dict[str, list[str]]] = {
    "amniocentesis": {"zh": ["羊膜腔穿刺"], "en": ["amniocentesis"]},
    "cvs": {"zh": ["绒毛膜穿刺", "绒毛穿刺"], "en": ["chorionic villus sampling", "CVS"]},
    "fetal_mri": {"zh": ["胎儿 MRI", "胎儿磁共振"], "en": ["fetal MRI", "magnetic resonance"]},
    "nipt_cfdna": {"zh": ["NIPT", "无创产前检测", "游离 DNA"], "en": ["NIPT", "cell-free DNA", "cfDNA"]},
    "twin_multiples": {"zh": ["双胎", "多胎", "双绒", "单绒"], "en": ["twin", "triplet", "chorionicity", "multiple pregnancy"]},
    "singleton": {"zh": ["单胎"], "en": ["singleton"]},
    "cervix_length": {"zh": ["宫颈长度", "宫颈"], "en": ["cervical length", "cervix"]},
    "growth_efw": {"zh": ["生长", "胎儿体重", "生物测量"], "en": ["growth", "biometry", "estimated fetal weight", "EFW"]},
    "cardiac_screening": {"zh": ["心脏筛查", "心脏"], "en": ["cardiac", "heart screening"]},
    "bladder": {"zh": ["膀胱"], "en": ["bladder"]},
    "reporting": {"zh": ["报告", "书写"], "en": ["report", "reporting"]},
    "dating": {"zh": ["定孕周", "孕周估计", "核实孕周"], "en": ["dating", "gestational age estimation", "crown-rump length", "CRL"]},
    "whole_genome": {"zh": ["全基因组", "基因组范围"], "en": ["genome-wide"]},
    "variants_interpretation": {"zh": ["变异解读"], "en": ["variant interpretation", "variants interpretation"]},
}

NUM_RE = re.compile(r"\d+[+＋周天w\d]*")


def extract_features(question: str) -> set[str]:
    """提取概念 ID + 归一化数值（孕周/周天统一为天数概念）。"""
    feats: set[str] = set()
    for concept, langs in CONCEPTS.items():
        for synonyms in langs.values():
            if any(syn in question for syn in synonyms):
                feats.add(f"concept:{concept}")
                break
    # 数值：孕周格式 "14周6天" / "14+6" / "15周0天" 统一为总天数；裸数字保留
    for m in re.finditer(r"(\d+)周[+＋]?(\d+)?天?", question):
        weeks = int(m.group(1))
        days = int(m.group(2) or 0)
        feats.add(f"ga_days:{weeks * 7 + days}")
    for m in re.finditer(r"\b(\d{1,4})\b", question):
        feats.add(f"num:{m.group(1)}")
    return feats


def overlap_report_v2() -> dict:
    dev = json.loads(
        (REPO / "benchmark/qa/dataset/pace_conditions_v1/dev_families.json").read_text(
            encoding="utf-8"
        )
    )
    hist_files = [
        ("hist50", "benchmark/qa/dataset/sample_questions.json"),
        ("hist12", "benchmark/qa/dataset/preclinical_challenge_draft.json"),
        ("l4safety6", "benchmark/qa/dataset/sample_questions_l4_safety.json"),
        ("condition_pairs30", "benchmark/qa/dataset/condition_pairs.json"),
    ]
    hist: list[tuple[str, str, str]] = []
    for src, path in hist_files:
        p = REPO / path
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        for q in data:
            hist.append((q.get("question_id", "?"), src, q.get("question", "")))

    rows: list[dict[str, Any]] = []
    flagged_families: set[str] = set()
    for r in dev["records"]:
        for v in r["variants"]:
            feats = extract_features(v["question"])
            best = (0.0, None, None)
            for hid, hsrc, hq in hist:
                hfeats = extract_features(hq)
                union = feats | hfeats
                j = len(feats & hfeats) / len(union) if union else 0.0
                if j > best[0]:
                    best = (j, hid, hsrc)
            entry = {
                "draft_question_id": v["draft_question_id"],
                "family_id": r["scenario_family_id"],
                "heuristic_candidate_score": round(best[0], 3),
                "closest_hist_id": best[1],
                "closest_hist_src": best[2],
                "semantic_review_required": True,  # 全部家族保留人工语义复核
            }
            rows.append(entry)
            if best[0] >= 0.3:
                flagged_families.add(r["scenario_family_id"])

    # 整家族标记：一个变体命中 → 整家族待裁定
    for row in rows:
        if row["family_id"] in flagged_families:
            row["family_flagged_for_adjudication"] = True
        else:
            row["family_flagged_for_adjudication"] = False

    flagged_rows = [r for r in rows if r["family_flagged_for_adjudication"]]
    return {
        "schema_version": "overlap-audit-v2",
        "score_name": "heuristic_candidate_score（术语概念+归一化数值 jaccard，启发式）",
        "interpretation": "高分仅作人工语义复核的候选排序依据；不判定派生，不证明独立。全部家族保留语义复核要求。",
        "n_new_questions": len(rows),
        "flagged_families": sorted(flagged_families),
        "n_flagged_families": len(flagged_families),
        "n_flagged_rows": len(flagged_rows),
        "rows": rows,
    }


if __name__ == "__main__":
    rep = overlap_report_v2()
    out = REPO / "benchmark/qa/dataset/pace_conditions_v1/template_overlap_audit_v2.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"flagged families: {rep['flagged_families']} | flagged rows: {rep['n_flagged_rows']}")
    print(f"wrote {out}")
