"""运行时三通道检索臂的端到端对比（PACE 批次十二）。

**为什么需要这条臂**：`prenatal_rag_client` 的 B1 复用**冻结**的 B0 上下文、
不重跑检索，因此它无法反映检索侧的任何改动。要把批次十一在**检索层**观察到的
Δ（recall 0.94 → 0.98）传递到**答案层**，必须真的按通道重检索再生成。

**实验设计（只差一个变量）**：同一批 50 题、同一证据真值层、同一个 k=16、同一个
生成器与同一套提示词、同一个 judge，唯一差别是 RRF 的通道列表：

- ``two_channel``：BM25 + 图通道；
- ``three_channel``：BM25 + 图通道 + **向量通道**。

两臂同在真值层锚点空间，故是**严格配对**对比；不做跨检索栈的结论。

Usage (repo root):
    PYTHONPATH=. .venv/bin/python benchmark/report/three_channel_end_to_end.py \
        [--limit N] [--judge-mode off|optional|required] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from pathlib import Path
from typing import Any

from prenatal_rag.evidence_store import EvidenceStore
from prenatal_rag.retrieval import (
    Bm25Index,
    EmbeddingChannel,
    GraphChannel,
    LightRagChunkGraph,
    OverlapBridge,
    VectorIndex,
    parallel_recall,
)

from benchmark.baseline.prenatal_rag_client import a_generate, arm_score, score_arm
from benchmark.common import load_query_vectors, load_scoring_options
from benchmark.qa import judge_model_from_env, load_questions

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS = REPO_ROOT / "benchmark/results/light_rag/pace-b0-evaluation-20260914.json"
DEFAULT_DATASET = REPO_ROOT / "benchmark/qa/dataset/sample_questions.json"
DEFAULT_OUT_DIR = REPO_ROOT / "benchmark/results/corpus-condition-20260915"
EMBEDDING_CACHE = DEFAULT_OUT_DIR / "query_embeddings.json"
DATA_ROOT = REPO_ROOT / "benchmark/data"
EVIDENCE_STORE_DIR = DATA_ROOT / "evidence_store"
INDEX_NS = (
    DATA_ROOT / "light_rag_pace_b0_20260914" / "rag_storage" / "light_rag_pace_b0_20260914"
)
VDB_CHUNKS = INDEX_NS / "vdb_chunks.json"

BM25_K = 16
SEED_K = 8
CHANNEL_K = 16
MERGE_K = 16
HOPS = 2
ARMS = ("two_channel", "three_channel")
SCORE_KEYS = (
    "final_score",
    "retrieval_precision",
    "retrieval_recall",
    "coverage",
    "miss",
    "faithfulness",
    "completeness",
    "answer_correctness",
)


async def _stub_llm(system_prompt: str, user_prompt: str) -> str:
    import re

    n_evidence = len(re.findall(r"\[E\d+\]", user_prompt))
    return f"answer-with-{n_evidence}-evidence-chunks"


def _contexts(anchors: list[int], source_of: dict[int, str], text_of: dict[int, str]) -> list[dict[str, str]]:
    return [
        {"source_id": source_of[anchor], "text": text_of[anchor]}
        for anchor in anchors
        if anchor in source_of
    ]


async def run(
    questions: list[Any],
    *,
    results_path: Path,
    judge_mode: str,
    judge_model: str | None,
    llm_func: Any,
    limit: int | None,
) -> dict[str, Any]:
    from benchmark.qa import JudgeConfig

    store = EvidenceStore(EVIDENCE_STORE_DIR)
    bm25 = Bm25Index.from_store(store)
    graph = LightRagChunkGraph.from_index_dir(INDEX_NS)
    bridge = OverlapBridge.build(graph.texts, store)
    index = VectorIndex.from_vdb_json(VDB_CHUNKS)
    graph_channel = GraphChannel(graph, bridge, hops=HOPS)
    embedding_channel = EmbeddingChannel(index, bridge)

    source_of = {c.anchor_id: c.source_id for c in store.iter_chunks()}
    text_of = {c.anchor_id: c.text for c in store.iter_chunks()}

    results = json.loads(results_path.read_text(encoding="utf-8"))
    question_text = {r["question_id"]: r["question"] for r in results["results"]}
    if limit is not None:
        questions = questions[:limit]
    query_vectors = load_query_vectors(
        EMBEDDING_CACHE,
        [(q.question_id, question_text.get(q.question_id, q.question)) for q in questions],
        index.dimensions,
    )

    scoring = load_scoring_options(None)
    mode = scoring["source_match_mode"]
    equivalences = scoring["source_equivalence"]
    judge_config = (
        JudgeConfig(model=judge_model) if judge_mode != "off" and judge_model else None
    )

    per_question: list[dict[str, Any]] = []
    totals: dict[str, dict[str, list[float]]] = {
        arm: {key: [] for key in SCORE_KEYS} for arm in ARMS
    }

    for question in questions:
        text = question_text.get(question.question_id, question.question)
        bm25_anchors = [h.chunk_id for h in bm25.search(text, k=BM25_K)]
        graph_anchors = graph_channel.rank(bm25_anchors[:SEED_K])
        embedding_anchors = embedding_channel.rank(
            query_vectors[question.question_id], k=CHANNEL_K
        )
        ranked = {
            "two_channel": parallel_recall(bm25_anchors, graph_anchors, k=MERGE_K),
            "three_channel": parallel_recall(
                bm25_anchors,
                graph_anchors,
                k=MERGE_K,
                embedding_ranking=embedding_anchors,
            ),
        }

        entry: dict[str, Any] = {"question_id": question.question_id, "answers": {}}
        for arm in ARMS:
            contexts = _contexts(ranked[arm], source_of, text_of)
            answer = await a_generate(question, contexts, llm_func=llm_func)
            result = score_arm(
                question,
                answer,
                contexts,
                judge_mode=judge_mode,
                judge_config=judge_config,
                judge_model=judge_model,
                k=MERGE_K,
                source_match_mode=mode,
                source_equivalence=equivalences,
            )
            scores = arm_score(result)
            for key in SCORE_KEYS:
                totals[arm][key].append(float(scores[key]))
            entry["answers"][arm] = answer
            entry[arm] = {**scores, "n_contexts": len(contexts)}
        entry["answers_differ"] = entry["answers"]["two_channel"] != entry["answers"]["three_channel"]
        per_question.append(entry)
        print(
            f"  {question.question_id:<10} "
            f"final {entry['two_channel']['final_score']} -> "
            f"{entry['three_channel']['final_score']} "
            f"R {entry['two_channel']['retrieval_recall']} -> "
            f"{entry['three_channel']['retrieval_recall']}",
            flush=True,
        )

    def mean(arm: str, key: str) -> float:
        values = totals[arm][key]
        return round(statistics.fmean(values), 4) if values else 0.0

    summary: dict[str, Any] = {
        arm: {key: mean(arm, key) for key in SCORE_KEYS} for arm in ARMS
    }
    summary["paired_delta"] = {
        "n": len(per_question),
        "n_answers_differ": sum(1 for p in per_question if p["answers_differ"]),
    }
    for key in ("final_score", "faithfulness", "completeness", "answer_correctness"):
        deltas = [
            round(p["three_channel"][key] - p["two_channel"][key], 4) for p in per_question
        ]
        summary["paired_delta"][f"mean_delta_{key}"] = (
            round(statistics.fmean(deltas), 4) if deltas else 0.0
        )
        summary["paired_delta"][f"n_{key}_improved"] = sum(1 for d in deltas if d > 0)
        summary["paired_delta"][f"n_{key}_degraded"] = sum(1 for d in deltas if d < 0)
    summary["judge_mode"] = judge_mode
    summary["judge_model"] = judge_model or ""
    return {"summary": summary, "per_question": per_question}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--judge-mode", choices=["off", "optional", "required"], default="off"
    )
    parser.add_argument("--judge-model", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true", help="stub 生成器（零 token）")
    args = parser.parse_args(argv)

    questions = load_questions(args.dataset)
    judge_model = args.judge_model or judge_model_from_env()
    report = asyncio.run(
        run(
            questions,
            results_path=args.results,
            judge_mode=args.judge_mode,
            judge_model=judge_model,
            llm_func=_stub_llm if args.dry_run else None,
            limit=args.limit,
        )
    )

    summary = report["summary"]
    print("=== three-channel end-to-end (runtime retrieval, k=16) ===")
    for arm in ARMS:
        print(f"  {arm:<14} {summary[arm]}")
    paired = summary["paired_delta"]
    print(
        f"  paired Δ(three - two): final={paired['mean_delta_final_score']} "
        f"(+{paired['n_final_score_improved']}/-{paired['n_final_score_degraded']}) "
        f"faithfulness={paired['mean_delta_faithfulness']} "
        f"completeness={paired['mean_delta_completeness']} "
        f"correctness={paired['mean_delta_answer_correctness']} "
        f"| answers_differ={paired['n_answers_differ']}/{paired['n']}"
    )

    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / "three_channel_end_to_end.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote:", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
