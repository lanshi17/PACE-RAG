"""B1 retrieval-layer ablation on the frozen B0 50-question evaluation.

Zero-LLM, zero-reindex: reads the B0 results (LightRAG, namespace
pac_b0_20260914) plus the dataset, derives each question's query conditions
(GA/population/technique) from the question side, classifies every retrieved
context three-valued, drops the explicitly Inapplicable ones (B1 filtering),
and recomputes retrieval metrics (precision/recall/coverage/miss@16) via the
same `compute_retrieval_metrics` used by the benchmark.

This isolates the *condition-processing* dimension exactly as B1 is defined in
the framework (§8.2: same retrieval, explicit condition filtering), and reports
B0-vs-B1 deltas. It is a retrieval-layer ablation: it cannot change the answer
text (no generation re-run), so faithfulness/completeness are untouched here.

Also reports honestly how condition-differentiated the frozen dataset is
(how many questions yield a query condition), which bounds the ablation's
blast radius until the condition-pair dataset (§8.1, 15 variant groups) lands.

Usage (repo root):
    PYTHONPATH=. .venv/bin/python benchmark/report/b1_retrieval_ablation.py [--results PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from prenatal_rag.applicability import Applicability
from prenatal_rag.conditions import classify_text, describe, parse_query_conditions

from benchmark.common import load_scoring_options, supported_statements
from benchmark.qa import load_questions
from benchmark.qa.scoring import compute_retrieval_metrics

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS = (
    REPO_ROOT / "benchmark/results/light_rag/pace-b0-evaluation-20260914.json"
)
DEFAULT_DATASET = REPO_ROOT / "benchmark/qa/dataset/sample_questions.json"
DEFAULT_OUT_DIR = REPO_ROOT / "benchmark/results/corpus-condition-20260915"
K = 16


def _query_conditions(question: Any) -> Any:
    return parse_query_conditions(question.question)


def main(results_path: Path, out_dir: Path) -> None:
    scoring = load_scoring_options(None)  # hybrid / equivalence from default config
    mode = scoring["source_match_mode"]
    equiv = scoring["source_equivalence"]

    results = json.loads(results_path.read_text(encoding="utf-8"))
    questions = {q.question_id: q for q in load_questions(DEFAULT_DATASET)}

    per_question: list[dict[str, Any]] = []
    n_cd_any = n_cd_ga = n_cd_pop = n_cd_tech = 0
    totals = {"b0": {"prec": [], "recall": [], "cov": [], "miss": []},
              "b1": {"prec": [], "recall": [], "cov": [], "miss": []}}

    for r in results["results"]:
        qid = r["question_id"]
        question = questions.get(qid)
        gold_ids = [s.guide for s in question.gold_sources] if question else []
        must = list(question.must_have_statements) if question else []
        contexts = [c for c in r.get("contexts", [])]
        texts = [c.get("text", "") for c in contexts]
        sources = [c.get("source_id", "") for c in contexts]

        query = _query_conditions(question) if question else None
        verdicts = [classify_text(t, query) for t in texts] if query else []
        has_cond = bool(query and (query.gestational_age is not None or query.population or query.technique))
        if has_cond:
            n_cd_any += 1
            if query.gestational_age is not None:
                n_cd_ga += 1
            if query.population:
                n_cd_pop += 1
            if query.technique:
                n_cd_tech += 1

        supports0 = [supported_statements(t, must) for t in texts]
        m0 = compute_retrieval_metrics(
            sources, gold_ids, must, supports0, k=K,
            source_match_mode=mode, source_equivalence=equiv,
        )

        kept_idx = [i for i, v in enumerate(verdicts) if v is not Applicability.INAPPLICABLE]
        dropped_idx = [i for i, v in enumerate(verdicts) if v is Applicability.INAPPLICABLE]
        sources1 = [sources[i] for i in kept_idx]
        supports1 = [supports0[i] for i in kept_idx]
        m1 = compute_retrieval_metrics(
            sources1, gold_ids, must, supports1, k=K,
            source_match_mode=mode, source_equivalence=equiv,
        )

        for group, m in (("b0", m0), ("b1", m1)):
            totals[group]["prec"].append(m.context_precision_at_k)
            totals[group]["recall"].append(m.context_recall_at_k)
            totals[group]["cov"].append(m.coverage_at_k)
            totals[group]["miss"].append(m.miss_at_k)

        per_question.append({
            "question_id": qid,
            "condition": describe(query) if query else "",
            "condition_bearing": has_cond,
            "n_contexts": len(contexts),
            "n_dropped_inapplicable": len(dropped_idx),
            "verdicts": {
                "applicable": sum(1 for v in verdicts if v is Applicability.APPLICABLE),
                "unknown": sum(1 for v in verdicts if v is Applicability.UNKNOWN),
                "inapplicable": len(dropped_idx),
            },
            "b0": {"precision": m0.context_precision_at_k, "recall": m0.context_recall_at_k,
                   "coverage": m0.coverage_at_k, "miss": m0.miss_at_k,
                   "n_sources": len(sources)},
            "b1": {"precision": m1.context_precision_at_k, "recall": m1.context_recall_at_k,
                   "coverage": m1.coverage_at_k, "miss": m1.miss_at_k,
                   "n_sources": len(sources1)},
        })

    def agg(group: str, key: str) -> float:
        vals = totals[group][key]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    summary = {}
    for group in ("b0", "b1"):
        summary[group] = {
            "precision@16": agg(group, "prec"),
            "recall@16": agg(group, "recall"),
            "coverage@16": agg(group, "cov"),
            "miss@16": agg(group, "miss"),
        }
    summary["condition_differentiation"] = {
        "total_questions": len(per_question),
        "n_with_any_condition": n_cd_any,
        "n_with_ga": n_cd_ga,
        "n_with_population": n_cd_pop,
        "n_with_technique": n_cd_tech,
    }
    total_dropped = sum(p["n_dropped_inapplicable"] for p in per_question)
    summary["total_contexts_dropped_inapplicable"] = total_dropped
    summary["dropped_contexts_with_condition_query"] = sum(
        p["n_dropped_inapplicable"] for p in per_question if p["condition_bearing"]
    )

    print("=== B1 retrieval-layer ablation on frozen B0 (50 questions) ===")
    cond_bearing = [p for p in per_question if p["condition_bearing"]]
    for q in cond_bearing:
        print(f"  {q['question_id']:<10} cond={q['condition']} ctx={q['n_contexts']} "
              f"drop={q['n_dropped_inapplicable']} "
              f"R0={q['b0']['recall']} R1={q['b1']['recall']} "
              f"C0={q['b0']['coverage']} C1={q['b1']['coverage']}")
    print(f"\ncondition_bearing questions: {summary['condition_differentiation']['n_with_any_condition']}/{len(per_question)}")
    print("  GA:", n_cd_ga, "| population:", n_cd_pop, "| technique:", n_cd_tech)
    print(f"all 50: B0 {summary['b0']}")
    print(f"        B1 {summary['b1']}")
    if cond_bearing:
        sub = [p for p in per_question if p["condition_bearing"]]
        def sub_agg(group, key):
            vals = [p[group][key] for p in sub]
            return round(sum(vals)/len(vals), 4)
        print(f"condition-bearing subset ({len(sub)}): "
              f"B0 R={sub_agg('b0','recall')} C={sub_agg('b0','coverage')} mis={sub_agg('b0','miss')} | "
              f"B1 R={sub_agg('b1','recall')} C={sub_agg('b1','coverage')} mis={sub_agg('b1','miss')}")
    print(f"total inapplicable contexts dropped: {total_dropped} "
          f"(among condition-queried questions: {summary['dropped_contexts_with_condition_query']})")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "b1_retrieval_ablation_b0frozen.json"
    out_path.write_text(
        json.dumps({"summary": summary, "per_question": per_question},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("wrote:", out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    main(args.results, args.out)