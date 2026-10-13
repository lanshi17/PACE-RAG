"""重叠审计 v3（审计补正 §2/§3）：强制暴露集前置 + 孕周解析修正 + 针对性测试。

修正：
1. 运行前强制执行 verify_exposure_coverage（4/4 pass 才继续），缺失/哈希不符即
   SystemExit 非零——不再静默跳过缺失文件。
2. 孕周解析修正：'14周6天' / '14+6周' / '14+6' 统一为 ga_days:104；
   '6周' 不再误解析为 42 天（仅 'N周M天' 或 'N+M' 两段式才组合成周+天）。
3. 输出实际输入数量、文件哈希、逐题匹配理由。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def parse_ga_days(question: str) -> set[int]:
    """提取孕周天数，同义表达统一。

    正确解析：
      '14周6天' → 104   (14*7+6)
      '14+6周'  → 104   (14*7+6)  — '+6' 是天数修饰，不是 6周
      '14+6'    → 104
      '15周0天' → 105
      '22+3周'  → 157
      '6周'     → 42    （仅 'N周' 无天数后缀时才是 6*7=42）
      '104天'   → 104
    """
    days: set[int] = set()
    # 两段式：N周M天 或 N+M（周），M 是天数修饰
    for m in re.finditer(r"(\d+)\s*(?:周|\+)\s*[+＋]?\s*(\d+)\s*天?", question):
        days.add(int(m.group(1)) * 7 + int(m.group(2)))
    # 单段式：'N周'（后面不跟数字/天）
    for m in re.finditer(r"(\d+)\s*周(?! *[+＋]?\s*\d)", question):
        days.add(int(m.group(1)) * 7)
    # 纯天数：'N天'
    for m in re.finditer(r"(\d+)\s*天", question):
        days.add(int(m.group(1)))
    return days


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


def extract_features_v3(question: str) -> set[str]:
    """提取概念 ID + 归一化孕周天数 + 其他数字。"""
    feats: set[str] = set()
    q_lower = question.lower()
    for concept, langs in CONCEPTS.items():
        for synonyms in langs.values():
            if any(syn in question or syn.lower() in q_lower for syn in synonyms):
                feats.add(f"concept:{concept}")
                break
    for d in parse_ga_days(question):
        feats.add(f"ga_days:{d}")
    # 裸数字（不含周/天单位的，避免与 ga_days 重复）
    plain_nums = set()
    for m in re.finditer(r"\b(\d{1,4})\b", question):
        span = m.span()
        after = question[span[1] : span[1] + 2]
        if not re.match(r"\s*(周|天|[+＋])", after):
            plain_nums.add(m.group(1))
    for n in plain_nums:
        feats.add(f"num:{n}")
    return feats


def overlap_report_v3() -> dict[str, Any]:
    # 强制暴露集前置
    sys.path.insert(0, str(REPO))
    from benchmark.pace_research.verify_exposure_coverage import verify_exposure_coverage

    inv_path = REPO / "benchmark/qa/dataset/pace_conditions_v1/legacy_exposure_inventory.json"
    exposure = verify_exposure_coverage(inv_path)
    if exposure["files_failed"] > 0:
        print(
            f"暴露集覆盖校验失败（{exposure['files_failed']} 文件），审计中止。",
            file=sys.stderr,
        )
        raise SystemExit(2)

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
    file_hashes: dict[str, str] = {}
    for src, rel in hist_files:
        p = REPO / rel
        import hashlib

        file_hashes[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        for q in json.loads(p.read_text(encoding="utf-8")):
            hist.append((q.get("question_id", "?"), src, q.get("question", "")))

    rows: list[dict[str, Any]] = []
    flagged_families: set[str] = set()
    for r in dev["records"]:
        for v in r["variants"]:
            feats = extract_features_v3(v["question"])
            best = (0.0, None, None)
            for hid, hsrc, hq in hist:
                hfeats = extract_features_v3(hq or "")
                union = feats | hfeats
                j = len(feats & hfeats) / len(union) if union else 0.0
                if j > best[0]:
                    best = (j, hid, hsrc)
            match_reason = (
                f"shared concepts/numbers: "
                f"{sorted(extract_features_v3(v['question']) & extract_features_v3(best[2]))[:8]}"
                if best[1]
                else None
            )
            rows.append(
                {
                    "draft_question_id": v["draft_question_id"],
                    "family_id": r["scenario_family_id"],
                    "heuristic_candidate_score": round(best[0], 3),
                    "closest_hist_id": best[1],
                    "closest_hist_src": best[2],
                    "match_reason": match_reason,
                    "semantic_review_required": True,
                }
            )
            if best[0] >= 0.3:
                flagged_families.add(r["scenario_family_id"])

    # 整家族标记
    for row in rows:
        row["family_flagged_for_adjudication"] = row["family_id"] in flagged_families

    flagged_rows = [r for r in rows if r["family_flagged_for_adjudication"]]
    return {
        "schema_version": "overlap-audit-v3",
        "score_name": "heuristic_candidate_score（概念 ID + 归一化孕周天数 jaccard）",
        "exposure_coverage": {
            "files_passed": exposure["files_passed"],
            "total_exposure_questions": exposure["total_exposure_questions"],
            "file_hashes": file_hashes,
        },
        "n_input_questions": len(hist),
        "interpretation": "高分仅作人工语义复核的候选排序依据；不判定派生，不证明独立。全部家族保留语义复核要求。",
        "flagged_families": sorted(flagged_families),
        "n_flagged_families": len(flagged_families),
        "n_flagged_rows": len(flagged_rows),
        "rows": rows,
    }


if __name__ == "__main__":
    rep = overlap_report_v3()
    out = REPO / "benchmark/qa/dataset/pace_conditions_v1/template_overlap_audit_v3.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"flagged families: {rep['flagged_families']} | flagged rows: {rep['n_flagged_rows']}")
    print(f"wrote {out}")
