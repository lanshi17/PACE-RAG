"""三通道检索消融：BM25+图 vs BM25+图+向量（对照冻结 B0）。

零 LLM、零重索引：复用批次十一的 ``EmbeddingChannel`` 与缓存查询向量，在真值层
锚点空间构造两臂候选集，用**与基准同源**的 ``compute_retrieval_metrics``（hybrid
口径 + 来源等价）对数据集金标准打分，给出向量通道在检索质量上的 Δ。

要点（为什么不是"直接接进 B1"）：``prenatal_rag_client`` 的 B1 明确**复用冻结的
B0 上下文、不重跑检索**（见其模块 docstring），故把向量通道"接进 B1"并不改变
任何上下文——真正可测的是**检索层**的 Δ。本探针即做这件事，且不需要跑 judge。

三臂口径差异（如实标注）：

- ``b0_frozen``：LightRAG 投影 chunk 空间（468 个 chunk），**参考臂**；
- ``bm25_graph`` / ``bm25_graph_embedding``：真值层**锚点**空间（341 个锚点），
  两臂同空间、可严格对比；与 ``b0_frozen`` 的分块粒度不同，故只作参照。

Usage (repo root):
    PYTHONPATH=. .venv/bin/python benchmark/report/three_channel_ablation.py [--out PATH]
"""

from __future__ import annotations

import argparse
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

from benchmark.common import load_query_vectors, load_scoring_options, supported_statements
from benchmark.qa import load_questions
from benchmark.qa.scoring import compute_retrieval_metrics

EMBEDDING_CACHE = (
    Path(__file__).resolve().parents[2]
    / "benchmark/results/corpus-condition-20260915/query_embeddings.json"
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = REPO_ROOT / "benchmark/qa/dataset/sample_questions.json"
DEFAULT_OUT_DIR = REPO_ROOT / "benchmark/results/corpus-condition-20260915"
ARMS = ("b0_frozen", "bm25_graph", "bm25_graph_embedding")

DEFAULT_RESULTS = REPO_ROOT / "benchmark/results/light_rag/pace-b0-evaluation-20260914.json"
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


def _score(
    sources: list[str],
    supports: list[set[str]],
    gold_ids: list[str],
    must: list[str],
    mode: str,
    equiv: dict[str, list[str]] | None,
) -> dict[str, float]:
    """按 ``compute_retrieval_metrics`` 的口径打分。

    契约：``sources`` 与 ``supports`` **必须等长**（打分器的 precision 是
    ``relevant / len(sources)``，而 relevant 按片段计）。因此这里不按来源去重，
    与 ``evaluate.py::score_arm`` 的用法一致。
    """
    metrics = compute_retrieval_metrics(
        sources, gold_ids, must, supports, k=MERGE_K,
        source_match_mode=mode, source_equivalence=equiv,
    )
    return {
        "precision": round(metrics.context_precision_at_k, 4),
        "recall": round(metrics.context_recall_at_k, 4),
        "coverage": round(metrics.coverage_at_k, 4),
        "miss": round(metrics.miss_at_k, 4),
        "n_sources": len(sources),
    }


def main(results_path: Path, out_dir: Path) -> None:
    scoring = load_scoring_options(None)
    mode = scoring["source_match_mode"]
    equiv = scoring["source_equivalence"]

    store = EvidenceStore(EVIDENCE_STORE_DIR)
    bm25 = Bm25Index.from_store(store)
    graph = LightRagChunkGraph.from_index_dir(INDEX_NS)
    bridge = OverlapBridge.build(graph.texts, store)
    index = VectorIndex.from_vdb_json(VDB_CHUNKS)
    graph_channel = GraphChannel(graph, bridge, hops=HOPS)
    embedding_channel = EmbeddingChannel(index, bridge)
    anchor_source = {c.anchor_id: c.source_id for c in store.iter_chunks()}
    anchor_text = {c.anchor_id: c.text for c in store.iter_chunks()}

    results = json.loads(results_path.read_text(encoding="utf-8"))
    questions = {q.question_id: q for q in load_questions(DEFAULT_DATASET)}
    queries = [(r["question_id"], r["question"]) for r in results["results"]]
    query_vectors = load_query_vectors(
        EMBEDDING_CACHE, queries, index.dimensions, refresh=False
    )

    per_question: list[dict[str, Any]] = []
    totals: dict[str, dict[str, list[float]]] = {
        arm: {key: [] for key in ("precision", "recall", "coverage", "miss")}
        for arm in ARMS
    }

    for r in results["results"]:
        qid = r["question_id"]
        question = questions.get(qid)
        gold_ids = [s.guide for s in question.gold_sources] if question else []
        must = list(question.must_have_statements) if question else []
        contexts = list(r.get("contexts", []))

        bm25_anchors = [h.chunk_id for h in bm25.search(r["question"], k=BM25_K)]
        graph_anchors = graph_channel.rank(bm25_anchors[:SEED_K])
        embedding_anchors = embedding_channel.rank(query_vectors[qid], k=CHANNEL_K)
        merged_two = parallel_recall(bm25_anchors, graph_anchors, k=MERGE_K)
        merged_three = parallel_recall(
            bm25_anchors, graph_anchors, k=MERGE_K, embedding_ranking=embedding_anchors
        )

        scored: dict[str, dict[str, float]] = {}
        scored["b0_frozen"] = _score(
            [str(c.get("source_id", "")) for c in contexts],
            [supported_statements(str(c.get("text", "")), must) for c in contexts],
            gold_ids, must, mode, equiv,
        )
        for arm, anchors in (("bm25_graph", merged_two), ("bm25_graph_embedding", merged_three)):
            pairs = [
                (anchor_source[a], supported_statements(anchor_text[a], must))
                for a in anchors
                if a in anchor_source
            ]
            scored[arm] = _score(
                [source for source, _ in pairs],
                [supports for _, supports in pairs],
                gold_ids, must, mode, equiv,
            )

        for arm in ARMS:
            for key in ("precision", "recall", "coverage", "miss"):
                totals[arm][key].append(scored[arm][key])

        per_question.append(
            {
                "question_id": qid,
                "gold_sources": gold_ids,
                "b0_frozen": scored["b0_frozen"],
                "bm25_graph": scored["bm25_graph"],
                "bm25_graph_embedding": scored["bm25_graph_embedding"],
                "delta_recall": round(
                    scored["bm25_graph_embedding"]["recall"] - scored["bm25_graph"]["recall"], 4
                ),
                "delta_coverage": round(
                    scored["bm25_graph_embedding"]["coverage"] - scored["bm25_graph"]["coverage"], 4
                ),
            }
        )

    def agg(arm: str, key: str) -> float:
        values = totals[arm][key]
        return round(statistics.fmean(values), 4) if values else 0.0

    summary: dict[str, Any] = {
        arm: {
            "precision@16": agg(arm, "precision"),
            "recall@16": agg(arm, "recall"),
            "coverage@16": agg(arm, "coverage"),
            "miss@16": agg(arm, "miss"),
        }
        for arm in ARMS
    }
    summary["paired_two_vs_three"] = {
        "mean_delta_recall": round(
            statistics.fmean([p["delta_recall"] for p in per_question]), 4
        ),
        "mean_delta_coverage": round(
            statistics.fmean([p["delta_coverage"] for p in per_question]), 4
        ),
        "n_recall_improved": sum(1 for p in per_question if p["delta_recall"] > 0),
        "n_recall_degraded": sum(1 for p in per_question if p["delta_recall"] < 0),
        "n_coverage_improved": sum(1 for p in per_question if p["delta_coverage"] > 0),
        "n_coverage_degraded": sum(1 for p in per_question if p["delta_coverage"] < 0),
    }
    summary["n"] = len(per_question)

    print("=== three-channel retrieval ablation (gold-scored, k=16) ===")
    for arm in ARMS:
        print(f"  {arm:<20} {summary[arm]}")
    paired = summary["paired_two_vs_three"]
    print(
        f"  paired Δ(three - two): recall={paired['mean_delta_recall']} "
        f"(+{paired['n_recall_improved']}/-{paired['n_recall_degraded']}) "
        f"coverage={paired['mean_delta_coverage']} "
        f"(+{paired['n_coverage_improved']}/-{paired['n_coverage_degraded']})"
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "three_channel_ablation.json"
    out_path.write_text(
        json.dumps({"summary": summary, "per_question": per_question}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("wrote:", out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    main(args.results, args.out)
