"""向量通道（第三路召回）真实探针（PACE 批次十一）。

在冻结的 LightRAG B0 投影上，用**真实** 3072 维 chunk 向量与**真实**查询
向量（text-embedding-3-large）演示"BM25 + 图 + 向量 → RRF"三通道并行召回，
并如实上报向量通道的边际贡献与源级覆盖。不断言 B1 Δ 收益。

查询向量只请求一次，写入 ``query_embeddings.json`` 缓存；此后本探针**离线
可复现**（门禁第 6 段即走缓存路径，不触网）。``--refresh-embeddings`` 才会
重新调用 embedding API。

Usage (repo root):
    PYTHONPATH=. .venv/bin/python benchmark/report/embedding_channel_probe.py
    PYTHONPATH=. .venv/bin/python benchmark/report/embedding_channel_probe.py --refresh-embeddings
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

from benchmark.common import load_query_vectors

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS = REPO_ROOT / "benchmark/results/light_rag/pace-b0-evaluation-20260914.json"
DEFAULT_DATASET = REPO_ROOT / "benchmark/qa/dataset/sample_questions.json"
DEFAULT_OUT_DIR = REPO_ROOT / "benchmark/results/corpus-condition-20260915"
DATA_ROOT = REPO_ROOT / "benchmark/data"
EVIDENCE_STORE_DIR = DATA_ROOT / "evidence_store"
INDEX_NS = (
    DATA_ROOT / "light_rag_pace_b0_20260914" / "rag_storage" / "light_rag_pace_b0_20260914"
)
VDB_CHUNKS = INDEX_NS / "vdb_chunks.json"
EMBEDDING_CACHE = DEFAULT_OUT_DIR / "query_embeddings.json"

BM25_K = 16
SEED_K = 8
CHANNEL_K = 16
MERGE_K = 16
HOPS = 2


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 4) if values else 0.0


def main(results_path: Path, out_dir: Path, *, refresh: bool) -> None:
    store = EvidenceStore(EVIDENCE_STORE_DIR)
    bm25 = Bm25Index.from_store(store)
    graph = LightRagChunkGraph.from_index_dir(INDEX_NS)
    bridge = OverlapBridge.build(graph.texts, store)
    index = VectorIndex.from_vdb_json(VDB_CHUNKS)

    graph_channel = GraphChannel(graph, bridge, hops=HOPS)
    embedding_channel = EmbeddingChannel(index, bridge)
    anchor_source = {c.anchor_id: c.source_id for c in store.iter_chunks()}

    results = json.loads(results_path.read_text(encoding="utf-8"))

    queries = [(r["question_id"], r["question"]) for r in results["results"]]
    query_vectors = load_query_vectors(
        EMBEDDING_CACHE, queries, index.dimensions, refresh=refresh
    )

    per_question: list[dict[str, Any]] = []
    for r in results["results"]:
        qid = r["question_id"]
        vector = query_vectors[qid]

        bm25_anchors = [h.chunk_id for h in bm25.search(r["question"], k=BM25_K)]
        graph_anchors = graph_channel.rank(bm25_anchors[:SEED_K])
        embedding_anchors = embedding_channel.rank(vector, k=CHANNEL_K)

        merged_two = parallel_recall(bm25_anchors, graph_anchors, k=MERGE_K)
        merged_three = parallel_recall(
            bm25_anchors, graph_anchors, k=MERGE_K, embedding_ranking=embedding_anchors
        )

        bm25_set = set(bm25_anchors)
        graph_set = set(graph_anchors)
        emb_set = set(embedding_anchors)
        merged_two_set = set(merged_two)
        merged_three_set = set(merged_three)

        b0_sources = {c.get("source_id", "") for c in r.get("contexts", [])}
        b0_sources.discard("")
        top1_source = anchor_source.get(embedding_anchors[0]) if embedding_anchors else None

        def sources(anchors: set[int]) -> set[str]:
            return {anchor_source[a] for a in anchors if a in anchor_source}

        per_question.append(
            {
                "question_id": qid,
                "n_bm25": len(bm25_set),
                "n_graph": len(graph_set),
                "n_embedding": len(emb_set),
                "n_merged_two": len(merged_two_set),
                "n_merged_three": len(merged_three_set),
                "n_emb_marginal_over_bm25_graph": len(emb_set - bm25_set - graph_set),
                "n_merged_three_marginal_over_two": len(merged_three_set - merged_two_set),
                "emb_top1_in_b0": bool(top1_source and top1_source in b0_sources),
                "b0_source_count": len(b0_sources),
                "merged_two_source_cov": (
                    round(len(sources(merged_two_set) & b0_sources) / len(b0_sources), 4)
                    if b0_sources
                    else 0.0
                ),
                "merged_three_source_cov": (
                    round(len(sources(merged_three_set) & b0_sources) / len(b0_sources), 4)
                    if b0_sources
                    else 0.0
                ),
            }
        )

    def agg(key: str) -> float:
        return _mean([float(p[key]) for p in per_question])

    summary = {
        "index": {
            "chunks": len(index),
            "dimensions": index.dimensions,
            "mapped_to_anchor": sum(
                1 for key in index.keys if bridge.chunk_to_anchor(key) is not None
            ),
        },
        "n": len(per_question),
        "mean_n_bm25": agg("n_bm25"),
        "mean_n_graph": agg("n_graph"),
        "mean_n_embedding": agg("n_embedding"),
        "mean_n_merged_two": agg("n_merged_two"),
        "mean_n_merged_three": agg("n_merged_three"),
        "mean_emb_marginal_over_bm25_graph": agg("n_emb_marginal_over_bm25_graph"),
        "n_questions_with_emb_marginal": sum(
            1 for p in per_question if p["n_emb_marginal_over_bm25_graph"] > 0
        ),
        "mean_merged_three_marginal_over_two": agg("n_merged_three_marginal_over_two"),
        "mean_merged_two_source_cov": agg("merged_two_source_cov"),
        "mean_merged_three_source_cov": agg("merged_three_source_cov"),
        "emb_top1_in_b0_rate": round(
            sum(1 for p in per_question if p["emb_top1_in_b0"]) / len(per_question), 4
        ),
    }

    print("=== embedding channel probe (BM25 + graph + vector -> RRF) ===")
    print(
        f"index: {summary['index']['chunks']} chunks × {summary['index']['dimensions']} dims, "
        f"mapped to anchors: {summary['index']['mapped_to_anchor']}"
    )
    print(
        f"n={summary['n']} mean unique: bm25={summary['mean_n_bm25']} "
        f"graph={summary['mean_n_graph']} embedding={summary['mean_n_embedding']} "
        f"merged2={summary['mean_n_merged_two']} merged3={summary['mean_n_merged_three']}"
    )
    print(
        f"embedding marginal over bm25∪graph: {summary['mean_emb_marginal_over_bm25_graph']} "
        f"(>0 in {summary['n_questions_with_emb_marginal']} questions)"
    )
    print(
        f"merged3 marginal over merged2: {summary['mean_merged_three_marginal_over_two']}"
    )
    print(
        f"source coverage vs B0: merged2={summary['mean_merged_two_source_cov']} "
        f"merged3={summary['mean_merged_three_source_cov']}"
    )
    print(f"embedding top-1 inside B0 contexts: {summary['emb_top1_in_b0_rate']}")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "embedding_channel_probe.json"
    out_path.write_text(
        json.dumps({"summary": summary, "per_question": per_question}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("wrote:", out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--refresh-embeddings", action="store_true")
    args = parser.parse_args()
    main(args.results, args.out, refresh=args.refresh_embeddings)
