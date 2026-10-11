"""C1/C2 base-gap 对照探针（预注册 pace-research-plan.md §4.1/§4.2）。

C1: LR 原生上下文（LightRAG hybrid 检索）+ PACE prompt → final
C2: LR 原生上下文 + LR 原生 prompt（= unified62 LightRAG 臂复跑）→ final
已有: LR native（unified62）final 0.9193；R1 A00（RRF 融合 + PACE prompt）0.9064。

用途：把 base 差距（0.9193 − ~0.91）归因为上下文组成 vs prompt。
预算：每对照 50 题 × 1 重复 ≈ 50 生成 + 50 Judge。

用法：
  uv run python benchmark/pace_research/probe_c1.py [--limit N] [--arm c1|c2]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "benchmark" / "baseline" / "libs" / "light_rag"))

from benchmark.baseline.light_rag_client import LightRAGClient  # noqa: E402
from benchmark.baseline.prenatal_rag_client.generator import a_generate  # noqa: E402
from benchmark.baseline.prenatal_rag_client.evaluate import score_arm  # noqa: E402
from benchmark.common import load_scoring_options  # noqa: E402
from benchmark.qa import JudgeConfig, load_questions  # noqa: E402

DEFAULT_LIGHT_RAG = REPO / "benchmark" / "data" / "light_rag_unified62"
DEFAULT_DATASET = REPO / "benchmark" / "qa" / "dataset" / "unified_62_seed42.json"


async def run_probe(out: Path, *, arm: str, limit: int | None) -> dict[str, Any]:
    from benchmark.qa import DatasetScoringReport
    from benchmark.qa import judge_model_from_env

    questions = load_questions(DEFAULT_DATASET)
    if limit is not None:
        questions = questions[:limit]
    client = LightRAGClient(DEFAULT_LIGHT_RAG)
    scoring_options = load_scoring_options(None)
    mode = scoring_options["source_match_mode"]
    equivalence = scoring_options["source_equivalence"]
    judge_model = judge_model_from_env()
    judge_config = JudgeConfig(model=judge_model) if judge_model else None
    report = DatasetScoringReport()
    per_q: list[dict[str, Any]] = []
    try:
        for question in questions:
            qr = client.search(
                question.question, "mix", top_k=40, chunk_top_k=40
            )
            raw_contexts = qr.context_data.get("chunks", [])
            contexts = []
            for i, item in enumerate(raw_contexts[:40], 1):
                text = str(item.get("content", "") or item.get("text", "")).strip()
                if not text:
                    continue
                contexts.append(
                    {
                        "anchor_id": f"c1-{i}",
                        "source_id": str(item.get("source_id") or item.get("file_path") or "?"),
                        "text": text,
                    }
                )
            if arm == "c1":
                # C1: LR 原生上下文 + PACE prompt（[E1..En]）
                answer = await a_generate(question, contexts)
            else:
                # C2: LR 原生上下文 + LR 原生 prompt = 直接用 LR 的回答
                answer = qr.response
            result = score_arm(
                question,
                answer,
                contexts,
                judge_mode="required",
                judge_config=judge_config,
                judge_model=judge_model,
                k=16,
                source_match_mode=mode,
                source_equivalence=equivalence,
            )
            report.add(result)
            per_q.append(
                {
                    "question_id": question.question_id,
                    "n_context": len(contexts),
                    "final_score": result.final_score,
                    "answer": answer[:500],
                }
            )
    finally:
        client.close()

    s = report.summary()
    return {
        "arm": arm,
        "n": len(per_q),
        "final_score": s.get("final_score"),
        "retrieval": s.get("retrieval"),
        "generation": s.get("generation"),
        "per_question": per_q,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--arm", choices=("c1", "c2"), required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    result = asyncio.run(run_probe(args.out, arm=args.arm, limit=args.limit))
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.out} | arm={args.arm} n={result['n']} final={result['final_score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
