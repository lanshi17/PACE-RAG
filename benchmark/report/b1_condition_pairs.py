"""B1 显式条件过滤在条件配对题集上的检索层消融（PACE 批次 7）。

在 `condition_pairs.json`（§8.1，15 组 × matched/mismatched 两个 GA 变体）上
演示"同一检索、显式条件过滤"（B1）的可见 Δ。零 LLM、确定性管道：
BM25 + LightRAG 投影图通道 → RRF 合并 top-16 → 对每个检索锚点做三值适用性 →
B1 仅丢弃明确 Inapplicable（Unknown 永不丢）。

设计意图：冻结 B0 评测只剔了 6 个上下文（弱信号）；本题集把查询孕周做成
条件判别变体，使 B1 的过滤**可见**。诚实口径：检索层只能演示"候选集被条件
过滤如何改变"；生成端收益（不引用不适用证据）仍需 judge 评测（需 token，出范围）。

同时如实报告轴依赖：全 GA 轴设计；人群/技术轴在本语料大量 Unknown
（未标注 → 永不丢弃），过滤近乎不触发——作为框架行为的诚实发现。

Usage (repo root):
    PYTHONPATH=. .venv/bin/python benchmark/report/b1_condition_pairs.py [--out PATH]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from prenatal_rag.applicability import Applicability
from prenatal_rag.conditions import classify_text, describe, parse_query_conditions
from prenatal_rag.evidence_store import EvidenceStore
from prenatal_rag.retrieval import (
    Bm25Index,
    GraphChannel,
    LightRagChunkGraph,
    OverlapBridge,
    parallel_recall,
)

from benchmark.common import load_scoring_options, supported_statements
from benchmark.qa.models import Question
from benchmark.qa.scoring import compute_retrieval_metrics

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = REPO_ROOT / "benchmark/qa/dataset/condition_pairs.json"
DEFAULT_OUT_DIR = REPO_ROOT / "benchmark/results/corpus-condition-20260915"
EVIDENCE_STORE_DIR = REPO_ROOT / "benchmark/data/evidence_store"
INDEX_NS = (
    REPO_ROOT
    / "benchmark/data/light_rag_pace_b0_20260914"
    / "rag_storage"
    / "light_rag_pace_b0_20260914"
)
K = 16
SEED_K = 8
HOPS = 2


def main(out_dir: Path) -> None:
    scoring = load_scoring_options(None)
    mode = scoring["source_match_mode"]
    equiv = scoring["source_equivalence"]

    raw_variants = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
    store = EvidenceStore(EVIDENCE_STORE_DIR)
    bm25 = Bm25Index.from_store(store)
    graph = LightRagChunkGraph.from_index_dir(INDEX_NS)
    bridge = OverlapBridge.build(graph.texts, store)
    channel = GraphChannel(graph, bridge, hops=HOPS)

    anchor_source = {c.anchor_id: c.source_id for c in store.iter_chunks()}
    anchor_text = {c.anchor_id: c.text for c in store.iter_chunks()}
    corpus_sources = set(anchor_source.values())

    # ── 数据集运行时自检（与生成器同断言，防下游篡改/漂移）─────────
    groups = sorted({v["variant_group"] for v in raw_variants})
    assert len(groups) == 15, f"组数应为 15，实际 {len(groups)}"
    for gid in groups:
        assert sum(1 for v in raw_variants if v["variant_group"] == gid) == 2, gid
    for v in raw_variants:
        q = parse_query_conditions(v["question"])
        assert q.gestational_age is not None, v["question_id"]
        for s in v.get("gold_sources", []):
            assert s.get("guide", "") in corpus_sources, v["question_id"]

    per_variant: list[dict[str, Any]] = []
    for v in raw_variants:
        question = Question.from_dict(v)
        gold_ids = [s.guide for s in question.gold_sources]
        must = list(question.must_have_statements)
        query = parse_query_conditions(question.question)

        anchors = [h.chunk_id for h in bm25.search(question.question, k=K)]
        merged = parallel_recall(anchors, channel.rank(anchors[:SEED_K]), k=K)

        verdicts = [classify_text(anchor_text[a], query) for a in merged if a in anchor_text]
        sources0 = [anchor_source[a] for a in merged if a in anchor_text]
        supports0 = [
            supported_statements(anchor_text[a], must) for a in merged if a in anchor_text
        ]
        m0 = compute_retrieval_metrics(
            sources0, gold_ids, must, supports0, k=K,
            source_match_mode=mode, source_equivalence=equiv,
        )

        kept = [i for i, vv in enumerate(verdicts) if vv is not Applicability.INAPPLICABLE]
        sources1 = [sources0[i] for i in kept]
        supports1 = [supports0[i] for i in kept]
        m1 = compute_retrieval_metrics(
            sources1, gold_ids, must, supports1, k=K,
            source_match_mode=mode, source_equivalence=equiv,
        )

        per_variant.append(
            {
                "question_id": question.question_id,
                "variant_group": v["variant_group"],
                "variant_role": v["variant_role"],
                "window_label": v["window_label"],
                "condition_note": v["condition_note"],
                "condition": describe(query),
                "n_retrieved": len(verdicts),
                "verdicts": {
                    "applicable": sum(1 for vv in verdicts if vv is Applicability.APPLICABLE),
                    "unknown": sum(1 for vv in verdicts if vv is Applicability.UNKNOWN),
                    "inapplicable": sum(1 for vv in verdicts if vv is Applicability.INAPPLICABLE),
                },
                "n_dropped_inapplicable": len(verdicts) - len(kept),
                "n_kept": len(kept),
                "b0": {"precision": m0.context_precision_at_k,
                       "recall": m0.context_recall_at_k,
                       "coverage": m0.coverage_at_k,
                       "miss": m0.miss_at_k, "n_sources": len(sources0)},
                "b1": {"precision": m1.context_precision_at_k,
                       "recall": m1.context_recall_at_k,
                       "coverage": m1.coverage_at_k,
                       "miss": m1.miss_at_k, "n_sources": len(sources1)},
            }
        )

    # 聚合：matched 与 mismatched 分桶对比 + 分组级"对比是否触发"
    def metric(sub: list[dict[str, Any]], group: str, key: str) -> float:
        return round(sum(p[group][key] for p in sub) / len(sub), 4) if sub else 0.0

    matched = [p for p in per_variant if p["variant_role"] == "matched"]
    mismatched = [p for p in per_variant if p["variant_role"] == "mismatched"]
    contrast_fired = sum(
        1
        for gid in groups
        if next(p for p in per_variant if p["variant_group"] == gid and p["variant_role"] == "mismatched")[
            "n_dropped_inapplicable"
        ]
        > next(p for p in per_variant if p["variant_group"] == gid and p["variant_role"] == "matched")[
            "n_dropped_inapplicable"
        ]
    )

    def stats(sub: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "n": len(sub),
            "mean_dropped": round(sum(p["n_dropped_inapplicable"] for p in sub) / len(sub), 4),
            "total_dropped": sum(p["n_dropped_inapplicable"] for p in sub),
            "mean_unknown": round(sum(p["verdicts"]["unknown"] for p in sub) / len(sub), 4),
            "b0": {k: metric(sub, "b0", k) for k in ("precision", "recall", "coverage", "miss")},
            "b1": {k: metric(sub, "b1", k) for k in ("precision", "recall", "coverage", "miss")},
        }

    summary = {
        "dataset": {
            "groups": len(groups),
            "variants": len(per_variant),
            "axis": "gestational_age",
        },
        "matched": stats(matched),
        "mismatched": stats(mismatched),
        "contrast_fired_groups": contrast_fired,
        "n_groups": len(groups),
    }

    print("=== B1 retrieval-layer ablation on condition-pair dataset (15 groups x2) ===")
    for p in per_variant:
        print(
            f"  {p['question_id']:<20} {p['variant_role']:9s} "
            f"{p['window_label']:10s} cond={p['condition']:>28s} "
            f"drop={p['n_dropped_inapplicable']} kept={p['n_kept']} "
            f"R0={p['b0']['recall']} R1={p['b1']['recall']} "
            f"C0={p['b0']['coverage']} C1={p['b1']['coverage']}"
        )
    print(f"\nmatched   {summary['matched']}")
    print(f"mismatched {summary['mismatched']}")
    print(f"contrast fired in {contrast_fired}/{len(groups)} groups "
          f"(mismatched drops > matched drops)")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "b1_condition_pairs.json"
    out_path.write_text(
        json.dumps({"summary": summary, "per_variant": per_variant},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("wrote:", out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    main(args.out)
