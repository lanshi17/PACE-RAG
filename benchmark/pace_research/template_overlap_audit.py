"""R2 模板重叠审计：跨语言语义近似检查（中文草案 vs 英文历史题）。

词面 shingle 在跨语言场景恒 0——需要语义级比较。零 token 方案：
用术语级对齐（中英超声术语词典子集）+ 数字/孕周/操作词匹配作为近似。
结论按保守口径记录：词面重叠 0 是语言差异的产物，不能据此声明"无派生关系"；
语义重叠审查列入专家审核必答项。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# 中英对照的超声临床核心术语（子集，覆盖本批 9 家族的主题域）
TERM_MAP = {
    "羊膜腔穿刺": ["amniocentesis"],
    "绒毛膜穿刺": ["chorionic villus sampling", "CVS"],
    "胎儿 MRI": ["fetal MRI", "magnetic resonance"],
    "NIPT": ["NIPT", "cell-free DNA", "cfDNA"],
    "多胎": ["twin", "multiple pregnancy", "chorionicity"],
    "单胎": ["singleton"],
    "宫颈": ["cervix", "cervical length"],
    "生长": ["growth", "biometry", "estimated fetal weight"],
    "心脏": ["cardiac", "heart"],
    "孕周": ["gestational age", "weeks"],
    "膀胱": ["bladder"],
    "报告": ["report"],
}

NUM_RE = re.compile(r"\d+[+＋]?\d*|\b\d+\b")


def _extract_features(q: str) -> set[str]:
    """提取语言无关特征：数字/孕周值 + 术语规范化标记。"""
    feats: set[str] = set()
    for num in NUM_RE.findall(q):
        feats.add(f"num:{num}")
    for zh, ens in TERM_MAP.items():
        if zh in q:
            for e in ens:
                feats.add(f"term:{e.lower()}")
        for e in ens:
            if e.lower() in q.lower():
                feats.add(f"term:{e.lower()}")
    return feats


def overlap_report() -> dict:
    dev = json.loads(
        (REPO / "benchmark/qa/dataset/pace_conditions_v1/dev_families.json").read_text(
            encoding="utf-8"
        )
    )
    hist_files = [
        ("hist50", "benchmark/qa/dataset/sample_questions.json"),
        ("hist12", "benchmark/qa/dataset/preclinical_challenge_draft.json"),
        ("l4safety6", "benchmark/qa/dataset/sample_questions_l4_safety.json"),
    ]
    hist: list[tuple[str, str, str]] = []
    for src, path in hist_files:
        try:
            for q in json.loads((REPO / path).read_text(encoding="utf-8")):
                hist.append((q.get("question_id", "?"), src, q.get("question", "")))
        except FileNotFoundError:
            pass

    rows = []
    flags = []
    for r in dev["records"]:
        for v in r["variants"]:
            feats = _extract_features(v["question"])
            best = (0.0, None, None)
            for hid, hsrc, hq in hist:
                hfeats = _extract_features(hq)
                j = len(feats & hfeats) / len(feats | hfeats) if feats | hfeats else 0.0
                if j > best[0]:
                    best = (j, hid, hsrc)
            rows.append(
                {
                    "draft_question_id": v["draft_question_id"],
                    "family_id": r["scenario_family_id"],
                    "feature_overlap": round(best[0], 3),
                    "closest_hist_id": best[1],
                    "closest_hist_src": best[2],
                }
            )
            if best[0] >= 0.5:
                flags.append(rows[-1])
    high = [r for r in rows if r["feature_overlap"] >= 0.5]
    return {
        "method": "术语+数字特征 jaccard（跨语言近似，保守下界）",
        "n_new": len(rows),
        "n_hist": len(hist),
        "mean_overlap": round(sum(r["feature_overlap"] for r in rows) / len(rows), 3),
        "high_overlap_ge_0_5": high,
        "rows": rows,
    }


if __name__ == "__main__":
    rep = overlap_report()
    out = REPO / "benchmark/qa/dataset/pace_conditions_v1/template_overlap_audit.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"mean overlap: {rep['mean_overlap']} | high(>=0.5): {len(rep['high_overlap_ge_0_5'])}")
    print(f"wrote {out}")
