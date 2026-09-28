"""SUPERSEDES 版本门控真实探针（PACE 批次 8，零 LLM）。

在证据真值层 + 指南注册表上构建 source_id 替代图，然后对真实检索集演示：
同一指南的多个版本被同时召回时，**被替代版本不得承担直接支持**——
`select_evidence(supersession=...)` 把它们从 `primary_support` 降级到
`comparative`（版本比较材料），仅当前版本保留直接支持。

诚实口径：这是机制演示。版本门控的触发依赖"旧版被检索到"；即使当前版本
未被召回，只要真值层知道其存在（图由语料 DOI 构建），降级仍然生效。MRI
版本链在本 50 题集中无对应问题，如实报告为"未被执行"。

Usage (repo root):
    PYTHONPATH=. .venv/bin/python benchmark/report/supersedes_probe.py [--out PATH]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from prenatal_rag.conditions import classify_text, parse_query_conditions
from prenatal_rag.evidence import EvidenceCandidate, EvidenceRole, SupersessionGraph, select_evidence
from prenatal_rag.evidence_store import EvidenceStore
from prenatal_rag.retrieval import (
    Bm25Index,
    GraphChannel,
    LightRagChunkGraph,
    OverlapBridge,
    parallel_recall,
)

from benchmark.common.versions import load_supersession_graph
from benchmark.qa import load_questions

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = REPO_ROOT / "benchmark/qa/dataset/sample_questions.json"
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
_ROLES = frozenset({EvidenceRole.GUIDELINE})


def _buckets(
    candidates: list[EvidenceCandidate],
    supersession: SupersessionGraph | None,
    as_of_year: int | None = None,
) -> dict[str, list[str]]:
    sel = select_evidence(
        candidates,
        required_roles=_ROLES,
        supersession=supersession,
        as_of_year=as_of_year,
    )
    return {
        "primary_support": list(sel.primary_support),
        "comparative": list(sel.comparative),
        "applicability_unknown": list(sel.applicability_unknown),
        "background": list(sel.background),
    }


AS_OF_YEARS = (2010, 2016, 2024)


def main(out_dir: Path) -> None:
    store = EvidenceStore(EVIDENCE_STORE_DIR)
    graph = load_supersession_graph(store)
    bm25 = Bm25Index.from_store(store)
    chunk_graph = LightRagChunkGraph.from_index_dir(INDEX_NS)
    bridge = OverlapBridge.build(chunk_graph.texts, store)
    channel = GraphChannel(chunk_graph, bridge, hops=HOPS)

    chunks = list(store.iter_chunks())
    anchor_source = {c.anchor_id: c.source_id for c in chunks}
    anchor_text = {c.anchor_id: c.text for c in chunks}

    print("=== SUPERSEDES version graph (from registry + corpus DOI) ===")
    for src in sorted(graph.superseded_sources()):
        print(f"  {graph.chain(src)[0]} -> ... -> {graph.current_version(src)}")
    print(f"  edges={len(graph.edges)} superseded_sources={len(graph.superseded_sources())}")

    per_question: list[dict[str, Any]] = []
    for question in load_questions(DEFAULT_DATASET):
        anchors = [h.chunk_id for h in bm25.search(question.question, k=K)]
        merged = parallel_recall(anchors, channel.rank(anchors[:SEED_K]), k=K)
        retrieved = [a for a in merged if a in anchor_source]
        sources = [anchor_source[a] for a in retrieved]
        touched = sorted({s for s in sources if graph.is_superseded(s)})
        if not touched:
            continue  # 只报告真正召回旧版的问题

        query = parse_query_conditions(question.question)
        candidates = [
            EvidenceCandidate(
                id=str(a),
                verdict=classify_text(anchor_text[a], query),
                roles=_ROLES,
                source_id=anchor_source[a],
            )
            for a in retrieved
        ]
        before = _buckets(candidates, None)
        after = _buckets(candidates, graph)
        demoted = [c for c in before["primary_support"] if c not in after["primary_support"]]
        # as-of 时点：不同年份"当前版本"不同（2006→2013→2023）。
        as_of: dict[str, Any] = {}
        for year in AS_OF_YEARS:
            buckets = _buckets(candidates, graph, year)
            as_of[str(year)] = {
                "n_primary": len(buckets["primary_support"]),
                "n_comparative": len(buckets["comparative"]),
                "primary_sources": sorted(
                    {anchor_source[int(cid)] for cid in buckets["primary_support"]}
                ),
            }
        per_question.append(
            {
                "question_id": question.question_id,
                "question": question.question,
                "n_retrieved": len(sources),
                "superseded_sources_retrieved": touched,
                "current_versions_retrieved": sorted(
                    {graph.current_version(s) for s in touched}
                ),
                "n_demoted_from_primary": len(demoted),
                "before": before,
                "after": after,
                "as_of": as_of,
            }
        )

    total_demoted = sum(p["n_demoted_from_primary"] for p in per_question)
    summary = {
        "graph": {
            "n_edges": len(graph.edges),
            "chains": {s: list(graph.chain(s)) for s in sorted(graph.superseded_sources())},
        },
        "questions_touching_superseded_sources": len(per_question),
        "total_demoted_from_primary": total_demoted,
        "mri_chain_exercised": any(
            "magnetic-resonance" in s
            for p in per_question
            for s in p["superseded_sources_retrieved"]
        ),
        "as_of_primary_totals": {
            str(year): sum(p["as_of"][str(year)]["n_primary"] for p in per_question)
            for year in AS_OF_YEARS
        },
    }

    print(f"\nquestions touching superseded sources: {len(per_question)}")
    for p in per_question:
        print(
            f"  {p['question_id']:<10} retrieved={p['n_retrieved']} "
            f"old={len(p['superseded_sources_retrieved'])} "
            f"demoted_from_primary={p['n_demoted_from_primary']} "
            f"| primary {len(p['before']['primary_support'])}->{len(p['after']['primary_support'])}"
        )
    print(f"total demoted from primary_support: {total_demoted}")

    print("\n=== as-of 时点语义（当前版本随时点变化）===")
    for src in sorted(graph.superseded_sources()):
        timeline = " | ".join(
            f"{year}->{graph.current_version_at(src, year)}" for year in AS_OF_YEARS
        )
        print(f"  {src}\n    {timeline}")
    print(f"  primary_support 总数 by as-of: {summary['as_of_primary_totals']}")
    if per_question:
        demo = per_question[0]
        for year in AS_OF_YEARS:
            entry = demo["as_of"][str(year)]
            print(
                f"  demo {demo['question_id']} @{year}: "
                f"primary={entry['n_primary']} comparative={entry['n_comparative']}"
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "supersedes_probe.json"
    out_path.write_text(
        json.dumps({"summary": summary, "per_question": per_question},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("wrote:", out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    main(args.out)
