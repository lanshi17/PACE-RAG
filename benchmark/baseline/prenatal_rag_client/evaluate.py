"""B1 端到端评估核心：对每道题生成 b0_ctrl 与 b1 两臂并评分。

复用冻结的 B0 检索上下文（由 ``contexts_provider`` 提供），不重跑索引/检索；
两臂差异仅在于是否应用条件过滤，从而把条件处理对生成的效应隔离出来。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from benchmark.baseline.prenatal_rag_client.b1_filter import (
    filter_contexts,
    query_for_question,
)
from benchmark.baseline.prenatal_rag_client.generator import LlmFunc, a_generate
from benchmark.common import empty_usage, load_scoring_options, safety_actions, supported_statements

ContextsProvider = Callable[[Any], list[dict[str, str]]]

_AWAITABLE = (Awaitable,)


async def run_b1_evaluation(
    questions: list[Any],
    contexts_provider: ContextsProvider,
    *,
    llm_func: LlmFunc | None = None,
    judge_mode: str = "off",
    judge_config: Any = None,
    judge_model: str | None = None,
    k: int | None = None,
    source_match_mode: str | None = None,
    scoring_config_path: Path | None = None,
    version_check: Callable[[str, list[dict[str, str]]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """执行 B1 双臂评估，返回汇总与每题明细。

    ``version_check`` 为可选的生成端版本一致性核验器（答案, 上下文）-> 结论字典；
    提供时会持久化每题答案并记录两臂的核验结论（批次十：答案须引当前版本）。
    """
    from benchmark.qa import DatasetScoringReport

    scoring_options = load_scoring_options(scoring_config_path)
    mode = source_match_mode or scoring_options["source_match_mode"]
    equivalence = scoring_options["source_equivalence"]

    report_ctrl = DatasetScoringReport()
    report_b1 = DatasetScoringReport()
    per_question: list[dict[str, Any]] = []
    version_statuses: dict[str, list[str]] = {"b0_ctrl": [], "b1": []}

    for question in questions:
        contexts = contexts_provider(question)
        query = query_for_question(question)
        filtered = filter_contexts(contexts, query)
        drop_questions = filtered.n_inapplicable > 0

        answer_ctrl = await a_generate(question, contexts, llm_func=llm_func)
        answer_b1 = (
            await a_generate(question, filtered.kept, llm_func=llm_func)
            if drop_questions
            else answer_ctrl
        )
        ctrl_check = (
            version_check(answer_ctrl, contexts) if version_check is not None else None
        )
        b1_check = (
            version_check(answer_b1, filtered.kept)
            if version_check is not None
            else None
        )

        # 评分：b0_ctrl 使用全部上下文，b1 使用保留上下文。
        result_ctrl = score_arm(
            question, answer_ctrl, contexts, judge_mode=judge_mode,
            judge_config=judge_config, judge_model=judge_model,
            k=k, source_match_mode=mode, source_equivalence=equivalence,
        )
        result_b1 = score_arm(
            question, answer_b1, filtered.kept, judge_mode=judge_mode,
            judge_config=judge_config, judge_model=judge_model,
            k=k, source_match_mode=mode, source_equivalence=equivalence,
        )
        report_ctrl.add(result_ctrl)
        report_b1.add(result_b1)

        per_question.append({
            "question_id": question.question_id,
            "query_condition": _describe_query(query),
            "n_contexts": len(contexts),
            "n_dropped_inapplicable": filtered.n_inapplicable,
            "n_applicable": filtered.n_applicable,
            "n_unknown": filtered.n_unknown,
            "split_generation": drop_questions,
            "answers_differ": answer_ctrl != answer_b1,
            "answers": {"b0_ctrl": answer_ctrl, "b1": answer_b1},
            "version_check": {
                "b0_ctrl": ctrl_check,
                "b1": b1_check,
            },
            "b0_ctrl": arm_score(result_ctrl),
            "b1": arm_score(result_b1),
        })
        for arm, check in (("b0_ctrl", ctrl_check), ("b1", b1_check)):
            if check is not None:
                version_statuses[arm].append(str(check.get("status", "")))

    report: dict[str, Any] = {
        "arms": {
            "b0_ctrl": arm_summary(report_ctrl),
            "b1": arm_summary(report_b1),
        },
        "n_questions": len(per_question),
        "n_questions_with_dropped_contexts": sum(
            1 for item in per_question if item["n_dropped_inapplicable"] > 0
        ),
        "total_dropped_inapplicable": sum(
            item["n_dropped_inapplicable"] for item in per_question
        ),
        "per_question": per_question,
    }
    if version_check is not None:
        report["version_check_summary"] = {
            arm: {
                "n": len(statuses),
                "status_counts": {
                    status: statuses.count(status)
                    for status in sorted(set(statuses))
                },
                "stale_only": version_statuses[arm].count("stale_only"),
            }
            for arm, statuses in version_statuses.items()
        }
    return report


def score_arm(
    question: Any,
    answer: str,
    contexts: list[dict[str, str]],
    *,
    judge_mode: str,
    judge_config: Any,
    judge_model: str | None,
    k: int | None,
    source_match_mode: str,
    source_equivalence: dict[str, list[str]],
) -> Any:
    from benchmark.qa import judge_answer, score_question

    retrieved_sources = [item.get("source_id", "") for item in contexts]
    retrieved_context = "\n\n".join(str(item.get("text", "")) for item in contexts)
    retrieved_supports = [
        supported_statements(str(item.get("text", "")), question.must_have_statements)
        for item in contexts
    ]
    refused, referred = safety_actions(answer)
    judge_result: dict[str, Any] | None = None
    if judge_mode != "off":
        if judge_config is None:
            judge_result = {
                "model": judge_model or "",
                "error": "no --judge-model or JUDGE_COMPLETION_MODEL provided, fell back to lexical",
                "usage": {**empty_usage(), "failed_request_count": 1},
            }
        else:
            judge_result = judge_answer(
                question=question.question,
                answer=answer,
                context=retrieved_context,
                gold_answer=question.gold_answer,
                must_have_statements=question.must_have_statements,
                config=judge_config,
            )
    return score_question(
        question=question,
        answer=answer,
        retrieved_sources=retrieved_sources,
        retrieved_context=retrieved_context,
        retrieved_supports=retrieved_supports,
        refused=refused,
        referred=referred,
        k=k,
        source_match_mode=source_match_mode,
        source_equivalence=source_equivalence,
        judge_result=judge_result,
    )


def arm_score(result: Any) -> dict[str, float]:
    ret = result.retrieval
    gen = result.generation
    return {
        "final_score": round(result.final_score, 4),
        "retrieval_precision": round(ret.context_precision_at_k, 4),
        "retrieval_recall": round(ret.context_recall_at_k, 4),
        "coverage": round(ret.coverage_at_k, 4),
        "miss": round(ret.miss_at_k, 4),
        "faithfulness": round(gen.faithfulness, 4),
        "completeness": round(gen.completeness, 4),
        "answer_correctness": round(gen.answer_correctness, 4),
    }


def arm_summary(report: Any) -> dict[str, Any]:
    return {
        "final_score": round(report.final_score, 4),
        "mean_retrieval": {
            "precision": round(report.mean_retrieval.context_precision_at_k, 4),
            "recall": round(report.mean_retrieval.context_recall_at_k, 4),
            "coverage": round(report.mean_retrieval.coverage_at_k, 4),
            "miss": round(report.mean_retrieval.miss_at_k, 4),
        },
        "mean_generation": {
            "faithfulness": round(report.mean_generation.faithfulness, 4),
            "completeness": round(report.mean_generation.completeness, 4),
            "answer_correctness": round(report.mean_generation.answer_correctness, 4),
        },
        "n": len(report.results),
    }


def _describe_query(query: Any) -> str:
    from prenatal_rag.conditions import describe

    return describe(query)