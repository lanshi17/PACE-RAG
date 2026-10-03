"""统一受控实验汇总：门禁校验 + 配对统计（预注册 §6）。

用法：
  uv run python benchmark/unified62/summarize_unified62.py

输入：benchmark/results/unified62/{graphrag,lightrag,pathrag,kag,hipporag}/evaluation.json
输出：benchmark/results/unified62/summary.json（含门禁记录 + 描述统计 + Friedman +
  Holm 配对 Wilcoxon + 按题 bootstrap CI + 敏感性分析 + 失败率）

口径（预注册 §6）：
- 主分析：50 题成熟子集（unified_62_seed42.json 中 adjudicated=True 或来自
  sample_questions.json 的 50 题），final_score 区组内配对比较。
- 12 草案题只作描述性报告，不进入排序推断。
- Judge 失败单元记失败，不插补；配对比较中该题剔除（listwise within-pair）。
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from benchmark.common.benchmark_protocol import assert_comparable_conditions  # noqa: E402

RESULTS = REPO / "benchmark" / "results" / "unified62"
FRAMEWORKS = ["graphrag", "lightrag", "pathrag", "kag", "hipporag"]
GATE_FIELDS = [
    "dataset_sha256",
    "corpus_fingerprint",
    "scoring_config_sha256",
    "judge_mode",
    "judge_model",
    "completion_model",
    "embedding_model",
    "top_k",
]

N_BOOTSTRAP = 10_000
BOOTSTRAP_SEED = 20260929


def _load(framework: str) -> dict:
    path = RESULTS / framework / "evaluation.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _conditions_gate(products: dict[str, dict]) -> dict:
    """预注册 §2 门禁：GATE_FIELDS 两两一致才放行汇总。"""
    record: dict = {"fields": GATE_FIELDS, "comparisons": [], "passed": True}
    base = FRAMEWORKS[0]
    base_cond = {
        key: products[base]["metadata"]["benchmark_conditions"][key]
        for key in GATE_FIELDS
    }
    for other in FRAMEWORKS[1:]:
        other_cond = {
            key: products[other]["metadata"]["benchmark_conditions"][key]
            for key in GATE_FIELDS
        }
        try:
            assert_comparable_conditions(base_cond, other_cond)
            record["comparisons"].append({"pair": [base, other], "ok": True})
        except ValueError as exc:
            record["passed"] = False
            record["comparisons"].append(
                {"pair": [base, other], "ok": False, "error": str(exc)}
            )
    record["conditions"] = {
        fw: {
            key: products[fw]["metadata"]["benchmark_conditions"][key]
            for key in GATE_FIELDS
        }
        for fw in FRAMEWORKS
    }
    return record


def _per_question(products: dict[str, dict]) -> dict[str, dict[str, dict]]:
    """question_id -> framework -> {final, retrieval..., generation..., failed}."""
    table: dict[str, dict[str, dict]] = {}
    for fw in FRAMEWORKS:
        for row in products[fw]["results"]:
            qid = row["question_id"]
            scoring = row.get("scoring", {})
            failed = bool(row.get("error")) or scoring.get("final_score") is None
            cell: dict = {"failed": failed}
            if not failed:
                cell["final"] = float(scoring["final_score"])
                ret = scoring.get("retrieval", {})
                gen = scoring.get("generation", {})
                cell["recall"] = float(ret.get("context_recall_at_k", float("nan")))
                cell["coverage"] = float(ret.get("coverage_at_k", float("nan")))
                cell["precision"] = float(
                    ret.get("context_precision_at_k", float("nan"))
                )
                cell["faithfulness"] = float(gen.get("faithfulness", float("nan")))
                cell["completeness"] = float(gen.get("completeness", float("nan")))
                cell["correctness"] = float(
                    gen.get("answer_correctness", float("nan"))
                )
            table.setdefault(qid, {})[fw] = cell
    return table


def _mature_ids() -> tuple[set[str], set[str]]:
    """返回 (50 题成熟集 id, 12 题草案集 id)。"""
    base = {
        q["question_id"]
        for q in json.loads(
            (REPO / "benchmark" / "qa" / "dataset" / "sample_questions.json").read_text(
                encoding="utf-8"
            )
        )
    }
    draft = {
        q["question_id"]
        for q in json.loads(
            (
                REPO / "benchmark" / "qa" / "dataset" / "preclinical_challenge_draft.json"
            ).read_text(encoding="utf-8")
        )
    }
    return base, draft


def _describe(ids: list[str], table: dict) -> dict:
    """各框架描述性均值 + 失败率（跳过失败单元）。"""
    out: dict = {}
    for fw in FRAMEWORKS:
        vals: dict[str, list[float]] = {}
        n_fail = 0
        for qid in ids:
            cell = table.get(qid, {}).get(fw)
            if cell is None or cell.get("failed"):
                n_fail += 1
                continue
            for metric in (
                "final",
                "recall",
                "coverage",
                "precision",
                "faithfulness",
                "completeness",
                "correctness",
            ):
                vals.setdefault(metric, []).append(cell[metric])
        out[fw] = {
            metric: (sum(v) / len(v) if v else None) for metric, v in vals.items()
        }
        out[fw]["n"] = len(ids) - n_fail
        out[fw]["n_failed"] = n_fail
    return out


def _friedman(ids: list[str], table: dict) -> dict:
    """Friedman 检验（5 相关组）+ Kendall's W。只用 5 框架全成功的题。"""
    from scipy.stats import friedmanchisquare

    complete = [
        qid
        for qid in ids
        if all(not table.get(qid, {}).get(fw, {}).get("failed") for fw in FRAMEWORKS)
    ]
    if len(complete) < 3:
        return {"error": "complete-case 题数不足", "n_complete": len(complete)}
    samples = [[table[qid][fw]["final"] for qid in complete] for fw in FRAMEWORKS]
    stat, p = friedmanchisquare(*samples)
    k, n = len(FRAMEWORKS), len(complete)
    kendall_w = float(stat / (n * (k - 1))) if n * (k - 1) else 0.0
    return {
        "statistic": float(stat),
        "p_value": float(p),
        "kendalls_w": kendall_w,
        "n_complete": n,
        "n_dropped": len(ids) - n,
    }


def _holm_wilcoxon(ids: list[str], table: dict) -> dict:
    """10 对配对 Wilcoxon + Holm 校正 + 配对中位数差（Hodges-Lehmann 近似用中位数差）。"""
    from scipy.stats import wilcoxon

    pairs = []
    for a, b in itertools.combinations(FRAMEWORKS, 2):
        diffs = []
        for qid in ids:
            ca = table.get(qid, {}).get(a, {})
            cb = table.get(qid, {}).get(b, {})
            if ca.get("failed") or cb.get("failed"):
                continue
            diffs.append(ca["final"] - cb["final"])
        if len(diffs) < 6:
            pairs.append({"pair": [a, b], "error": "配对数不足", "n": len(diffs)})
            continue
        try:
            res = wilcoxon(diffs, alternative="two-sided")
            p = float(getattr(res, "pvalue"))
        except Exception as exc:  # noqa: BLE001 - 零差等退化情形如实记录
            pairs.append({"pair": [a, b], "error": str(exc)[:120], "n": len(diffs)})
            continue
        diffs_sorted = sorted(diffs)
        median_diff = float(
            diffs_sorted[len(diffs_sorted) // 2]
            if len(diffs_sorted) % 2
            else (diffs_sorted[len(diffs_sorted) // 2 - 1] + diffs_sorted[len(diffs_sorted) // 2]) / 2
        )
        pairs.append(
            {
                "pair": [a, b],
                "n": len(diffs),
                "median_diff": median_diff,
                "mean_diff": float(sum(diffs) / len(diffs)),
                "p_raw": p,
            }
        )
    # Holm 校正
    testable = [p for p in pairs if "p_raw" in p]
    ordered = sorted(testable, key=lambda p: p["p_raw"])
    m = len(ordered)
    for rank, p in enumerate(ordered):
        p["p_holm"] = min(1.0, p["p_raw"] * (m - rank))
    return {"pairs": pairs, "m_tests": m}


def _bootstrap_ci(ids: list[str], table: dict) -> dict:
    """按题 bootstrap（seed 固定）：框架均值差的 95% CI。只用全成功题。"""
    import random

    complete = [
        qid
        for qid in ids
        if all(not table.get(qid, {}).get(fw, {}).get("failed") for fw in FRAMEWORKS)
    ]
    rng = random.Random(BOOTSTRAP_SEED)
    out: dict = {}
    for a, b in itertools.combinations(FRAMEWORKS, 2):
        base = [table[q][a]["final"] - table[q][b]["final"] for q in complete]
        reps = []
        for _ in range(N_BOOTSTRAP):
            sample = [base[rng.randrange(len(base))] for _ in range(len(base))]
            reps.append(sum(sample) / len(sample))
        reps.sort()
        lo = reps[int(0.025 * N_BOOTSTRAP)]
        hi = reps[int(0.975 * N_BOOTSTRAP) - 1]
        out[f"{a}_minus_{b}"] = {
            "mean_diff": float(sum(base) / len(base)),
            "ci95": [float(lo), float(hi)],
            "n": len(base),
        }
    out["n_bootstrap"] = N_BOOTSTRAP
    out["seed"] = BOOTSTRAP_SEED
    return out


def main() -> int:
    products = {fw: _load(fw) for fw in FRAMEWORKS}
    gate = _conditions_gate(products)
    table = _per_question(products)
    mature, draft = _mature_ids()
    all_ids = sorted(table)
    mature_ids = sorted(set(all_ids) & mature)
    draft_ids = sorted(set(all_ids) & draft)

    summary: dict = {
        "preregistration": "docs/2026-09-29/unified62-preregistration.md",
        "gate": gate,
        "n_questions_total": len(all_ids),
        "n_mature": len(mature_ids),
        "n_draft": len(draft_ids),
        "descriptive_mature50": _describe(mature_ids, table),
        "descriptive_draft12": _describe(draft_ids, table),
        "descriptive_all62": _describe(all_ids, table),
    }
    if gate["passed"]:
        summary["friedman_mature50"] = _friedman(mature_ids, table)
        summary["holm_wilcoxon_mature50"] = _holm_wilcoxon(mature_ids, table)
        summary["bootstrap_ci_mature50"] = _bootstrap_ci(mature_ids, table)
        # 敏感性：62 全集重跑主分析
        summary["sensitivity_all62"] = {
            "friedman": _friedman(all_ids, table),
            "holm_wilcoxon": _holm_wilcoxon(all_ids, table),
        }
        # 敏感性：剔除缺源题（语料锁定的 recall 上限题）
        locked = {"PU-L4-001", "PU-L4-002", "PU-L4-003", "PU-L3-024", "PU-L3-027"}
        kept = [qid for qid in mature_ids if qid not in locked]
        summary["sensitivity_mature_excluding_source_locked"] = {
            "excluded": sorted(locked & set(mature_ids)),
            "n_kept": len(kept),
            "friedman": _friedman(kept, table),
            "holm_wilcoxon": _holm_wilcoxon(kept, table),
        }
    else:
        summary["note"] = "门禁未通过，不做推断统计，只保留描述性统计。"

    out = RESULTS / "summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out} (gate_passed={gate['passed']})")
    return 0 if gate["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
