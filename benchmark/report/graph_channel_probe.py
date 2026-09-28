"""图通道接入 RRF 的真实索引探针（PACE 批次 6）。

零 LLM：在冻结的 LightRAG B0 投影索引 + 证据真值层上，演示 §5.1
"并行召回 → RRF 合并"的双通道（BM25 + 图通道）机制，并如实上报
投影桥接保真度与图通道对候选集的边际贡献。不断言 B1 Δ 收益。

- 桥接保真度：LightRAG 投影 chunk 中有多少映射到真值层锚点、最佳
  重叠 Jaccard 的分布（桥是近似，保真度必须透明）。
- 逐题：BM25 top-16 → 种子 top-8 → 图通道扩展（hop=2）→ RRF 合并
  k=16；记录 merged 相对 BM25 独有候选数、以及两者对 B0 冻结结果
  source 集合的覆盖。

Usage (repo root):
    PYTHONPATH=. .venv/bin/python benchmark/report/graph_channel_probe.py [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from prenatal_rag.conditions import describe, parse_query_conditions
from prenatal_rag.evidence_store import EvidenceStore
from prenatal_rag.retrieval import (
    Bm25Index,
    GraphChannel,
    LightRagChunkGraph,
    OverlapBridge,
    parallel_recall,
)

from benchmark.qa import load_questions

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS = (
    REPO_ROOT / "benchmark/results/light_rag/pace-b0-evaluation-20260914.json"
)
DEFAULT_DATASET = REPO_ROOT / "benchmark/qa/dataset/sample_questions.json"
DEFAULT_OUT_DIR = REPO_ROOT / "benchmark/results/corpus-condition-20260915"
DATA_ROOT = REPO_ROOT / "benchmark/data"
EVIDENCE_STORE_DIR = DATA_ROOT / "evidence_store"
INDEX_NS = (
    DATA_ROOT
    / "light_rag_pace_b0_20260914"
    / "rag_storage"
    / "light_rag_pace_b0_20260914"
)

BM25_K = 16
SEED_K = 8
MERGE_K = 16
HOPS = 2


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 4) if values else 0.0


def _bridge_fidelity(bridge: OverlapBridge, texts: dict[str, str]) -> dict[str, Any]:
    keys = list(texts)
    mapped = [k for k in keys if bridge.chunk_to_anchor(k) is not None]
    jaccards = [bridge.jaccard_for(k) for k in mapped if bridge.jaccard_for(k) is not None]
    return {
        "projection_chunks": len(keys),
        "mapped_to_anchor": len(mapped),
        "mapped_ratio": round(len(mapped) / len(keys), 4) if keys else 0.0,
        "best_jaccard_mean": _mean(jaccards),
        "best_jaccard_median": (
            round(statistics.median(jaccards), 4) if jaccards else 0.0
        ),
        "best_jaccard_min": round(min(jaccards), 4) if jaccards else 0.0,
        "best_jaccard_max": round(max(jaccards), 4) if jaccards else 0.0,
    }


def main(results_path: Path, out_dir: Path) -> None:
    store = EvidenceStore(EVIDENCE_STORE_DIR)
    bm25 = Bm25Index.from_store(store)
    graph = LightRagChunkGraph.from_index_dir(INDEX_NS)
    bridge = OverlapBridge.build(graph.texts, store)

    anchor_source = {c.anchor_id: c.source_id for c in store.iter_chunks()}
    channel = GraphChannel(graph, bridge, hops=HOPS)
    fidelity = _bridge_fidelity(bridge, graph.texts)

    results = json.loads(results_path.read_text(encoding="utf-8"))
    questions = {q.question_id: q for q in load_questions(DEFAULT_DATASET)}

    per_question: list[dict[str, Any]] = []
    for r in results["results"]:
        qid = r["question_id"]
        question = questions.get(qid)
        query = parse_query_conditions(question.question) if question else None
        condition = describe(query) if query else ""
        has_cond = bool(
            query
            and (
                query.gestational_age is not None
                or query.population
                or query.technique
            )
        )

        bm25_anchors = [h.chunk_id for h in bm25.search(r["question"], k=BM25_K)]
        graph_anchors = channel.rank(bm25_anchors[:SEED_K])
        merged = parallel_recall(bm25_anchors, graph_anchors, k=MERGE_K)

        bm25_set = set(bm25_anchors)
        merged_set = set(merged)
        marginal = merged_set - bm25_set

        b0_sources = {c.get("source_id", "") for c in r.get("contexts", [])}
        b0_sources.discard("")
        bm25_sources = {anchor_source[a] for a in bm25_set if a in anchor_source}
        merged_sources = {anchor_source[a] for a in merged_set if a in anchor_source}

        per_question.append(
            {
                "question_id": qid,
                "condition": condition,
                "condition_bearing": has_cond,
                "n_bm25_unique": len(bm25_set),
                "n_graph": len(graph_anchors),
                "n_merged_unique": len(merged_set),
                "n_graph_marginal": len(marginal),
                "b0_source_count": len(b0_sources),
                "bm25_source_cov": (
                    round(len(bm25_sources & b0_sources) / len(b0_sources), 4)
                    if b0_sources
                    else 0.0
                ),
                "merged_source_cov": (
                    round(len(merged_sources & b0_sources) / len(b0_sources), 4)
                    if b0_sources
                    else 0.0
                ),
            }
        )

    def subset(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [p for p in items if p["condition_bearing"]]

    def agg(items: list[dict[str, Any]], key: str) -> float:
        return _mean([float(p[key]) for p in items])

    summary = {
        "bridge_fidelity": fidelity,
        "all": {
            "n": len(per_question),
            "mean_bm25_unique": agg(per_question, "n_bm25_unique"),
            "mean_graph": agg(per_question, "n_graph"),
            "mean_merged_unique": agg(per_question, "n_merged_unique"),
            "mean_graph_marginal": agg(per_question, "n_graph_marginal"),
            "n_questions_with_graph_marginal": sum(
                1 for p in per_question if p["n_graph_marginal"] > 0
            ),
            "mean_bm25_source_cov": agg(per_question, "bm25_source_cov"),
            "mean_merged_source_cov": agg(per_question, "merged_source_cov"),
        },
        "condition_bearing": {
            "n": len(subset(per_question)),
            "mean_bm25_unique": agg(subset(per_question), "n_bm25_unique"),
            "mean_graph": agg(subset(per_question), "n_graph"),
            "mean_merged_unique": agg(subset(per_question), "n_merged_unique"),
            "mean_graph_marginal": agg(subset(per_question), "n_graph_marginal"),
            "n_questions_with_graph_marginal": sum(
                1 for p in subset(per_question) if p["n_graph_marginal"] > 0
            ),
            "mean_bm25_source_cov": agg(subset(per_question), "bm25_source_cov"),
            "mean_merged_source_cov": agg(subset(per_question), "merged_source_cov"),
        },
    }

    print("=== graph channel probe (BM25 + LightRAG projection graph -> RRF) ===")
    print(f"projection chunks: {fidelity['projection_chunks']} "
          f"mapped: {fidelity['mapped_to_anchor']} "
          f"({fidelity['mapped_ratio']})")
    print(f"best-jaccard mean/median: {fidelity['best_jaccard_mean']} / "
          f"{fidelity['best_jaccard_median']}")
    for group in ("all", "condition_bearing"):
        g = summary[group]
        print(
            f"[{group}] n={g['n']} bm25={g['mean_bm25_unique']} "
            f"graph={g['mean_graph']} merged={g['mean_merged_unique']} "
            f"marginal={g['mean_graph_marginal']} "
            f"(marginal>0: {g['n_questions_with_graph_marginal']}) "
            f"src_cov bm25={g['mean_bm25_source_cov']} merged={g['mean_merged_source_cov']}"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "graph_channel_probe.json"
    out_path.write_text(
        json.dumps(
            {"summary": summary, "per_question": per_question},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("wrote:", out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    main(args.results, args.out)
