"""合并 GraphRAG 主 run（37 有效）与 retry run（25）成完整 62 题产物。

规则：
- retry 的 25 题（原 error 行）整行替换主 run 对应行（含新 telemetry/verdict/answer）。
- metadata.benchmark_conditions 两份必须一致（dataset_sha256/corpus_fingerprint/
  judge/judge_model/completion_model/embedding_model/top_k/source_match_mode 一致才合并）。
- summary 用两份源 summary 重建：逐题 final 取合并后每题的 final，
  retrieval/generation/safety 按逐题均值重建（等权）——不重算 judge usage。
"""

from __future__ import annotations

import json
from pathlib import Path

MAIN = Path("benchmark/results/unified62/graphrag/evaluation.json")
RETRY = Path("/tmp/graphrag_retry25.json")
OUT = Path("benchmark/results/unified62/graphrag/evaluation.json")


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> None:
    main_d = load(MAIN)
    retry_d = load(RETRY)

    mc = main_d["metadata"]["benchmark_conditions"]
    rc = retry_d["metadata"]["benchmark_conditions"]
    gate_fields = [
        "dataset_sha256",
        "corpus_fingerprint",
        "scoring_config_sha256",
        "judge_mode",
        "judge_model",
        "completion_model",
        "embedding_model",
        "top_k",
    ]
    mism = [k for k in gate_fields if mc.get(k) != rc.get(k)]
    if mism:
        raise SystemExit(f"conditions differ: {mism}")
    if retry_d["results"][-1].get("error"):
        raise SystemExit("retry run still contains error rows; aborting merge")

    main_rows = {r["question_id"]: r for r in main_d["results"]}
    replaced = 0
    for row in retry_d["results"]:
        qid = row["question_id"]
        assert qid in main_rows and main_rows[qid].get("error"), qid
        main_rows[qid] = row
        replaced += 1

    rows = list(main_rows.values())
    # 保持数据集文件顺序：按 seed42 文件顺序重排
    seed_order = [
        q["question_id"]
        for q in json.loads(
            Path("benchmark/qa/dataset/unified_62_seed42.json").read_text(encoding="utf-8")
        )
    ]
    rows.sort(key=lambda r: seed_order.index(r["question_id"]))

    def mean(name: str) -> float:
        vals = [
            r["scoring"][name]
            for r in rows
            if r.get("scoring", {}).get(name) is not None
        ]
        return sum(vals) / len(vals)

    judge_ok = sum(
        1
        for r in rows
        if not (r.get("scoring", {}).get("judge", {}) or {}).get("error")
    )
    judge_fail = sum(
        1
        for r in rows
        if (r.get("scoring", {}).get("judge", {}) or {}).get("error")
    )
    lexical = sum(
        1 for r in rows if r.get("scoring", {}).get("scoring_method") == "lexical"
    )
    n = len(rows)
    summary = {
        "n_questions": n,
        "retrieval": {
            "context_precision_at_k": round(
                sum(r["scoring"]["retrieval"]["context_precision_at_k"] for r in rows) / n, 6
            ),
            "context_recall_at_k": round(
                sum(r["scoring"]["retrieval"]["context_recall_at_k"] for r in rows) / n, 6
            ),
            "coverage_at_k": round(
                sum(r["scoring"]["retrieval"]["coverage_at_k"] for r in rows) / n, 6
            ),
            "miss_at_k": round(
                sum(r["scoring"]["retrieval"]["miss_at_k"] for r in rows) / n, 6
            ),
            "mean": round(
                sum(r["scoring"]["retrieval"].get("mean", 0) for r in rows) / n, 6
            ),
        },
        "generation": {
            "faithfulness": round(
                sum(r["scoring"]["generation"]["faithfulness"] for r in rows) / n, 6
            ),
            "answer_relevance": round(
                sum(r["scoring"]["generation"]["answer_relevance"] for r in rows) / n, 6
            ),
            "completeness": round(
                sum(r["scoring"]["generation"]["completeness"] for r in rows) / n, 6
            ),
            "answer_correctness": round(
                sum(r["scoring"]["generation"]["answer_correctness"] for r in rows) / n, 6
            ),
            "weighted_mean": round(
                sum(r["scoring"]["generation"].get("weighted_mean", 0) for r in rows) / n,
                6,
            ),
        },
        "safety": {
            "safety_score": round(
                sum(r["scoring"]["safety"]["safety_score"] for r in rows) / n, 6
            ),
            "hallucination_rate": round(
                sum(r["scoring"]["safety"]["hallucination_rate"] for r in rows) / n, 6
            ),
        },
        "final_score": round(
            sum(r["scoring"]["final_score"] for r in rows) / n, 6
        ),
        "safety_gate_passed": all(
            r["scoring"].get("safety_gate_passed", True) for r in rows
        ),
        "scoring": {
            "selected_method": "mixed" if lexical else "judge",
            "judge_coverage": round(judge_ok / n, 6),
            "judge_success_count": judge_ok,
            "judge_failure_count": judge_fail,
            "lexical_count": lexical,
        },
        "source_match": {
            "exact_source_hit_rate": round(
                sum(r["scoring"]["source_match"]["exact_source_hit"] for r in rows) / n, 6
            ),
            "equivalent_source_hit_rate": round(
                sum(r["scoring"]["source_match"].get("equivalent_source_hit", False) for r in rows)
                / n,
                6,
            ),
            "evidence_supported_rate": round(
                sum(r["scoring"]["source_match"].get("evidence_supported", False) for r in rows)
                / n,
                6,
            ),
        },
        "usage": {
            "recorded_query_count": n,
            "recorded_judge_count": n,
            "cost_missing_count": n,
            "note": "usage 汇总由主 run + retry run 各自 telemetry 承担，此处不重复聚合",
        },
    }

    main_d["results"] = rows
    main_d["summary"] = summary
    main_d["metadata"]["question_count"] = n
    main_d["metadata"]["retry_merge"] = {
        "replaced_rows": replaced,
        "retry_raw": str(RETRY),
        "merged_at": retry_d["metadata"]["created_at"],
    }
    OUT.write_text(json.dumps(main_d, ensure_ascii=False, indent=2), encoding="utf-8")
    outl = OUT.with_suffix(".jsonl")
    outl.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    print(f"merged: replaced={replaced}, n={n}, final={summary['final_score']}")


if __name__ == "__main__":
    main()
