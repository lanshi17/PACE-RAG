"""R1 四臂端到端：宽候选快照 → 四臂上下文选取 → 生成 → 评分 → 主效应/交互。

用法（需网关配额）：
  uv run python benchmark/pace_research/run_r1_ablation.py \
      --snapshot benchmark/results/pace_research/r0/snapshot \
      --out benchmark/results/pace_research/r1 \
      --repeats 3 [--limit N]

预算：50 题 × 4 臂 × 3 重复 = 600 生成 + 600 Judge（约 1200 调用）。
评分复用 ``score_arm``（与 unified62 同一实现）；安全 verdict 走 judge_safety。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "benchmark" / "baseline" / "libs" / "light_rag"))

from benchmark.baseline.prenatal_rag_client.evaluate import score_arm  # noqa: E402
from benchmark.baseline.prenatal_rag_client.generator import a_generate  # noqa: E402
from benchmark.common import load_scoring_options  # noqa: E402
from prenatal_rag.conditions import classify_text, parse_query_conditions  # noqa: E402
from prenatal_rag.evidence_store import EvidenceStore  # noqa: E402
from prenatal_rag.retrieval import reciprocal_rank_fusion  # noqa: E402

ARMS = ("A00", "A10", "A01", "A11")


def select_arm(
    ranked_rows: list[dict[str, Any]],
    query: Any,
    *,
    arm: str,
    k: int,
    max_per_source: int,
    anchor_text: dict[int, str],
) -> dict[str, Any]:
    prefilter = arm in ("A10", "A11")
    dedup = arm in ("A01", "A11")
    source_of: dict[int, Any] = {
        row["anchor_id"]: row.get("source_id") for row in ranked_rows
    }
    if prefilter:
        verdicts_all = [
            classify_text(anchor_text.get(row["anchor_id"], ""), query)
            for row in ranked_rows
        ]
        eligible = [
            row
            for row, v in zip(ranked_rows, verdicts_all)
            if v is not Applicability_INAPPLICABLE()
        ]
    else:
        eligible = ranked_rows
        verdicts_all = [Applicability_UNKNOWN()] * len(ranked_rows)

    order = [row["anchor_id"] for row in eligible]
    if dedup:
        from prenatal_rag.retrieval import diverse_top_k

        chosen = diverse_top_k(
            order, k, source_of=source_of, max_per_source=max_per_source
        )
    else:
        chosen = order[:k]
    chosen_set = set(chosen)

    kept_rows: list[dict[str, Any]] = []
    dropped_rows: list[dict[str, Any]] = []
    for row, verdict in zip(ranked_rows, verdicts_all):
        anchor = row["anchor_id"]
        entry = {
            "anchor_id": anchor,
            "source_id": row.get("source_id"),
            "verdict": verdict.name,
        }
        in_context = anchor in chosen_set
        inapplicable = verdict.name == "INAPPLICABLE"
        if in_context:
            kept_rows.append(entry)
        elif inapplicable:
            entry["reason"] = "inapplicable"
            dropped_rows.append(entry)
        else:
            entry["reason"] = "out_of_budget"
            dropped_rows.append(entry)
    return {
        "arm": arm,
        "kept": kept_rows,
        "dropped": dropped_rows,
        "n_context": len(kept_rows),
        "n_inapplicable_dropped": sum(
            1 for d in dropped_rows if d.get("reason") == "inapplicable"
        ),
    }


def Applicability_INAPPLICABLE():
    from prenatal_rag.applicability import Applicability

    return Applicability.INAPPLICABLE


def Applicability_UNKNOWN():
    from prenatal_rag.applicability import Applicability

    return Applicability.UNKNOWN


async def run_r1(
    snapshot_dir: Path,
    out_dir: Path,
    *,
    repeats: int,
    k: int,
    max_per_source: int,
    limit: int | None,
) -> dict[str, Any]:
    from benchmark.qa import (
        DatasetScoringReport,
        JudgeConfig,
        judge_model_from_env,
        judge_safety,
    )

    rows_by_q: dict[str, dict[str, Any]] = {}
    for line in (snapshot_dir / "retrieval.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        rows_by_q[row["question_id"]] = row
    from benchmark.qa import load_questions

    questions = load_questions(
        REPO / "benchmark" / "qa" / "dataset" / "unified_62_seed42.json"
    )
    if limit is not None:
        questions = questions[:limit]

    store = EvidenceStore(REPO / "benchmark" / "data" / "evidence_store")
    anchor_text = {c.anchor_id: c.text for c in store.iter_chunks()}
    scoring_options = load_scoring_options(None)
    mode = scoring_options["source_match_mode"]
    equivalence = scoring_options["source_equivalence"]
    judge_model = judge_model_from_env()
    judge_config = JudgeConfig(model=judge_model) if judge_model else None

    report: dict[str, Any] = {
        "protocol": {
            "snapshot": str(snapshot_dir),
            "repeats": repeats,
            "k": k,
            "max_per_source": max_per_source,
            "arms": list(ARMS),
            "judge_mode": "required",
            "judge_model": judge_model,
        },
        "per_question": [],
    }
    reports_by_arm = {arm: DatasetScoringReport() for arm in ARMS}

    n = 0
    started = time.monotonic()
    for question in questions:
        qid = question.question_id
        row = rows_by_q.get(qid)
        if row is None:
            continue
        query_conditions = parse_query_conditions(question.question)
        fused = reciprocal_rank_fusion(
            [row["bm25"]["ranking"], row["graph"]["ranking"], row["vector"]["ranking"]]
        )
        anchor_to_source = {
            s["anchor_id"]: s.get("source_id")
            for channel in ("bm25", "graph", "vector")
            for s in row[channel]["scored"]
        }
        fused_rows = [
            {"anchor_id": a, "source_id": anchor_to_source.get(a)} for a in fused
        ]

        arms_context: dict[str, list[dict[str, str]]] = {}
        arms_detail: dict[str, Any] = {}
        for arm in ARMS:
            detail = select_arm(
                fused_rows,
                query_conditions,
                arm=arm,
                k=k,
                max_per_source=max_per_source,
                anchor_text=anchor_text,
            )
            arms_detail[arm] = detail
            # 上下文需要全文：从真值层取 kept 锚点文本，构造 contexts 记录
            contexts = []
            for entry in detail["kept"]:
                anchor = entry["anchor_id"]
                contexts.append(
                    {
                        "anchor_id": anchor,
                        "source_id": entry["source_id"],
                        "text": anchor_text.get(anchor, ""),
                    }
                )
            arms_context[arm] = contexts

        entry_q: dict[str, Any] = {
            "question_id": qid,
            "arms": {},
        }
        for repeat in range(repeats):
            for arm in ARMS:
                contexts = arms_context[arm]
                answer = await a_generate(question, contexts)
                safety_verdict = None
                if question.difficulty == "L4" and judge_config is not None:
                    safety_verdict = judge_safety(
                        question=question.question,
                        answer=answer,
                        safety_flags=question.safety_flags,
                        config=judge_config,
                    )
                result = score_arm(
                    question,
                    answer,
                    contexts,
                    judge_mode="required",
                    judge_config=judge_config,
                    judge_model=judge_model,
                    k=k,
                    source_match_mode=mode,
                    source_equivalence=equivalence,
                    safety_verdict=safety_verdict,
                )
                reports_by_arm[arm].add(result)
                entry_q["arms"].setdefault(arm, {})[f"repeat_{repeat}"] = {
                    "answer": answer,
                    "final_score": result.final_score,
                }
        entry_q["arm_detail"] = arms_detail
        report["per_question"].append(entry_q)
        n += 1
        if n % 10 == 0:
            print(f"  {n} questions done, {round(time.monotonic() - started)}s", flush=True)

    summary: dict[str, Any] = {"n_questions": n, "repeats": repeats, "arms": {}}
    for arm in ARMS:
        rep = reports_by_arm[arm]
        s = rep.summary()
        summary["arms"][arm] = {
            "final_score": s.get("final_score"),
            "retrieval": s.get("retrieval"),
            "generation": s.get("generation"),
            "safety": s.get("safety"),
            "n": s.get("n_questions"),
        }

    # 主效应与交互（50 题口径按 mature 过滤留给调用方；此处全集配对均值）
    effects: dict[str, Any] = {}
    for repeat in range(repeats):
        pairs = {}
        for q in report["per_question"]:
            qid = q["question_id"]
            vals = {}
            for arm in ARMS:
                v = q["arms"][arm].get(f"repeat_{repeat}")
                if v:
                    vals[arm] = v["final_score"]
            if len(vals) == len(ARMS):
                pairs[qid] = vals
        if len(pairs) < 3:
            continue
        y00 = sum(v["A00"] for v in pairs.values()) / len(pairs)
        y10 = sum(v["A10"] for v in pairs.values()) / len(pairs)
        y01 = sum(v["A01"] for v in pairs.values()) / len(pairs)
        y11 = sum(v["A11"] for v in pairs.values()) / len(pairs)
        effects[f"repeat_{repeat}"] = {
            "n": len(pairs),
            "prefilter_effect": round(((y10 - y00) + (y11 - y01)) / 2, 6),
            "dedup_effect": round(((y01 - y00) + (y11 - y10)) / 2, 6),
            "interaction": round(y11 - y10 - y01 + y00, 6),
            "means": {"A00": round(y00, 6), "A10": round(y10, 6), "A01": round(y01, 6), "A11": round(y11, 6)},
        }
    summary["factor_effects"] = effects
    report["summary"] = summary

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "r1_ablation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {out_dir / 'r1_ablation.json'} | questions={n} | elapsed={round(time.monotonic() - started)}s")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--k", type=int, default=16)
    parser.add_argument("--max-per-source", type=int, default=2)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(
        run_r1(
            args.snapshot,
            args.out,
            repeats=args.repeats,
            k=args.k,
            max_per_source=args.max_per_source,
            limit=args.limit,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
