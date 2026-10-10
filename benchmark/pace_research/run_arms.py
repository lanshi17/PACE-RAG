"""R0 统一多臂运行时：宽候选快照 → 四臂上下文选取 → 共用生成/评分。

四臂（预注册 pace-research-plan.md §4.2）：
- A00：过滤后置、去冗余关闭（现状基线）
- A10：过滤前置、去冗余关闭
- A01：过滤后置、去冗余开启
- A11：过滤前置、去冗余开启

输入：``snapshot_wide_candidates.py`` 产出的 ``retrieval.jsonl``（宽候选快照，
零 LLM 可重建）。每臂从同一快照按处理变量选取 ≤k 条上下文：
- F=前置：先按三值分类剔除 Inapplicable 锚点，再按快照排名截断；
- F=后置：按快照排名截断到 k，再剔除 Inapplicable（不补位，机制的一部分）；
- D=开启：截断时用 ``diverse_top_k``（同 source 限额）；关闭：普通 ``top_k``。
Unknown 恒保留；过滤原因逐条记录（kept/dropped + verdict）。

评分复用 ``prenatal_rag_client.evaluate`` 的 ``score_arm``（同一实现）；
required Judge 失败 = 单元失败（与 unified62 口径一致）。

用法（dry-run 零 token 验证选取差异）：
  uv run python benchmark/pace_research/run_arms.py \
      --snapshot benchmark/results/pace_research/r0/snapshot \
      --out benchmark/results/pace_research/r0/arms_dryrun.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "benchmark" / "baseline" / "libs" / "light_rag"))

from prenatal_rag.applicability import Applicability  # noqa: E402
from prenatal_rag.conditions import classify_text, parse_query_conditions  # noqa: E402
from prenatal_rag.retrieval import diverse_top_k  # noqa: E402

ARMS = ("A00", "A10", "A01", "A11")


def select_arm(
    ranked_rows: list[dict[str, Any]],
    query: Any,
    *,
    arm: str,
    k: int,
    max_per_source: int = 2,
    text_lookup: Any = None,
) -> dict[str, Any]:
    """按臂配置从宽候选排名选取上下文，返回明细（kept/dropped/verdicts）。

    ``ranked_rows`` 为单题单通道已 RRF 合并的候选（调用方先合并三路，
    按融合序排列），行含 ``anchor_id`` 与 ``source_id``。
    """
    prefilter = "1" in arm  # A10/A11
    dedup = "1" in arm[-2:]  # A01/A11（arm 第二位）
    source_of: dict[int, Any] = {
        row["anchor_id"]: row.get("source_id") for row in ranked_rows
    }

    if prefilter:
        verdicts_all = [
            classify_text(text_lookup(row), query) if text_lookup else Applicability.UNKNOWN
            for row in ranked_rows
        ]
        eligible = [
            row
            for row, v in zip(ranked_rows, verdicts_all)
            if v is not Applicability.INAPPLICABLE
        ]
    else:
        eligible = ranked_rows
        verdicts_all = [Applicability.UNKNOWN] * len(ranked_rows)

    order = [row["anchor_id"] for row in eligible]
    if dedup:
        chosen = diverse_top_k(order, k, source_of=source_of, max_per_source=max_per_source)
    else:
        chosen = order[:k]
    chosen_set = set(chosen)

    kept_rows: list[dict[str, Any]] = []
    dropped_rows: list[dict[str, Any]] = []
    for row, verdict in zip(ranked_rows, verdicts_all):
        anchor = row["anchor_id"]
        entry = {"anchor_id": anchor, "source_id": row.get("source_id"), "verdict": verdict.name}
        in_context = anchor in chosen_set
        inapplicable = verdict is Applicability.INAPPLICABLE
        if in_context:
            kept_rows.append(entry)
        elif not inapplicable:
            # 融合序在 k 之外：未入选原因（预算/限额），不算过滤
            entry["reason"] = "out_of_budget"
            dropped_rows.append(entry)
        else:
            entry["reason"] = "inapplicable"
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--k", type=int, default=16)
    parser.add_argument("--max-per-source", type=int, default=2)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅验证四臂选取差异（零 token）；不生成、不评分。",
    )
    args = parser.parse_args()

    snap_dir = args.snapshot
    rows_by_q: dict[str, dict[str, Any]] = {}
    for line in (snap_dir / "retrieval.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        rows_by_q[row["question_id"]] = row
    snap = json.loads((snap_dir / "snapshot.json").read_text(encoding="utf-8"))
    questions = json.loads(
        (REPO / "benchmark" / "qa" / "dataset" / "unified_62_seed42.json").read_text(
            encoding="utf-8"
        )
    )

    # RRF 合并三路（快照已有各路排名；融合序 = 三路 RRF，恒定，不随臂变化）
    from prenatal_rag.retrieval import reciprocal_rank_fusion

    report: dict[str, Any] = {
        "protocol": snap["protocol"],
        "k": args.k,
        "max_per_source": args.max_per_source,
        "questions": {},
    }
    differing = 0
    for q in questions:
        qid = q["question_id"]
        row = rows_by_q.get(qid)
        if row is None:
            continue
        query = parse_query_conditions(q["question"])
        # 融合三路排名（快照的 ranking 已按各路序）；RRF 常数与 unified62 一致
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
        arms_out: dict[str, Any] = {}
        contexts_by_arm: dict[str, list[int]] = {}
        for arm in ARMS:
            detail = select_arm(
                fused_rows,
                query,
                arm=arm,
                k=args.k,
                max_per_source=args.max_per_source,
                text_lookup=None,  # 零 token：Inapplicable 判定需全文，dry-run 全 Unknown
            )
            arms_out[arm] = detail
            contexts_by_arm[arm] = [e["anchor_id"] for e in detail["kept"]]
        distinct = len({tuple(v) for v in contexts_by_arm.values()})
        if distinct > 1:
            differing += 1
        report["questions"][qid] = {
            "fused_n": len(fused_rows),
            "arms": arms_out,
            "n_distinct_contexts": distinct,
        }

    report["n_questions"] = len(report["questions"])
    report["n_questions_with_arm_differences"] = differing
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"wrote {args.out} | questions={report['n_questions']} "
        f"| arms-differ={differing}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
