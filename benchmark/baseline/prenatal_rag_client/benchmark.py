"""prenatal_rag_client CLI：B1 条件约束受控生成评估入口。

用法（仓库根目录）：
    PYTHONPATH=. .venv/bin/python -m benchmark.baseline.prenatal_rag_client.benchmark \
        [--results B0.json] [--dataset sample_questions.json] [--limit N] \
        [--question-ids ID,ID] [--judge-mode off|optional|required] [--out PATH]

默认读取冻结的 B0 检索结果（同检索），对每题复用其上下文做受控重生成，
产出 b0_ctrl 与 b1 双臂对比。生成器可注入（用于无 token 的管道验证）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from benchmark.baseline.prenatal_rag_client.evaluate import run_b1_evaluation
from benchmark.qa import judge_model_from_env, load_questions

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RESULTS = (
    REPO_ROOT / "benchmark/results/light_rag/pace-b0-evaluation-20260914.json"
)
DEFAULT_DATASET = REPO_ROOT / "benchmark/qa/dataset/sample_questions.json"
DEFAULT_OUT = REPO_ROOT / "benchmark/results/corpus-condition-20260915"
DEFAULT_EVIDENCE_STORE = REPO_ROOT / "benchmark/data/evidence_store"

sys.path.insert(0, str(REPO_ROOT))


class FrozenContextsProvider:
    """从冻结的 B0 结果按 question_id 提供检索上下文。"""

    def __init__(self, results_path: Path) -> None:
        data = json.loads(results_path.read_text(encoding="utf-8"))
        self._by_id = {
            item.get("question_id"): list(item.get("contexts", []))
            for item in data.get("results", [])
        }

    def __call__(self, question: Any) -> list[dict[str, str]]:
        return self._by_id.get(question.question_id, [])

    def ids(self) -> set[str]:
        return set(self._by_id)


async def _stub_llm(system_prompt: str, user_prompt: str) -> str:
    # 无 token 管道验证：返回以证据数为签名的确定性答案。
    import re

    n_evidence = len(re.findall(r"\[E\d+\]", user_prompt))
    return f"answer-with-{n_evidence}-evidence-chunks"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--question-ids", type=str, default="")
    parser.add_argument(
        "--judge-mode", choices=["off", "optional", "required"], default="off"
    )
    parser.add_argument("--judge-model", type=str, default=None)
    parser.add_argument(
        "--no-version-check",
        action="store_true",
        help="关闭生成端版本一致性核验（默认开启；零 token 的确定性检查）。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="使用 stub 生成器（零 token），仅验证管道。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    from benchmark.qa import JudgeConfig

    args = build_parser().parse_args(argv)
    provider = FrozenContextsProvider(args.results)
    questions = load_questions(args.dataset)

    if args.question_ids:
        selected = {s for s in args.question_ids.split(",") if s}
        questions = [q for q in questions if q.question_id in selected]
    if args.limit is not None:
        questions = questions[: args.limit]
    if not questions:
        print("no questions selected", file=sys.stderr)
        return 2

    judge_model = args.judge_model or judge_model_from_env()
    judge_config = (
        JudgeConfig(model=judge_model)
        if args.judge_mode != "off" and judge_model
        else None
    )

    version_check = None
    if not args.no_version_check:
        from prenatal_rag.evidence_store import EvidenceStore

        from benchmark.common.versions import build_version_checker

        version_check = build_version_checker(EvidenceStore(DEFAULT_EVIDENCE_STORE))

    report = asyncio.run(
        run_b1_evaluation(
            questions,
            provider,
            llm_func=_stub_llm if args.dry_run else None,
            judge_mode=args.judge_mode,
            judge_config=judge_config,
            judge_model=judge_model,
            version_check=version_check,
        )
    )

    _print_report(report)

    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / "b1_end_to_end_ctrl.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote:", out_path)
    return 0


def _print_report(report: dict[str, Any]) -> None:
    arms = report["arms"]
    print("=== prenatal_rag_client B1 end-to-end (controlled regen) ===")
    print("questions:", report["n_questions"],
          "| split-gen:", report["n_questions_with_dropped_contexts"],
          "| dropped:", report["total_dropped_inapplicable"])
    for name in ("b0_ctrl", "b1"):
        arm = arms[name]
        print(f"  {name:<8} final={arm['final_score']} "
              f"R={arm['mean_retrieval']['recall']} "
              f"P={arm['mean_retrieval']['precision']} "
              f"C={arm['mean_retrieval']['coverage']} "
              f"F={arm['mean_generation']['faithfulness']}")
    for item in report["per_question"]:
        if item["n_dropped_inapplicable"] > 0:
            print("  drop:", item["question_id"], "cond=", item["query_condition"],
                  "drop=", item["n_dropped_inapplicable"],
                  "answers_differ=", item["answers_differ"])
    version_summary = report.get("version_check_summary")
    if version_summary:
        print("version-check (答案是否漏引可得当前版本):")
        for name in ("b0_ctrl", "b1"):
            arm = version_summary[name]
            print(f"  {name:<8} n={arm['n']} stale_only={arm['stale_only']} "
                  f"{arm['status_counts']}")


if __name__ == "__main__":
    raise SystemExit(main())