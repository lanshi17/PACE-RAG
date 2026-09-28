"""prenatal_rag_client：B1 条件约束受控生成管道的离线验证（零 token）。

用 stub 生成器（按证据片计数签名答案）验证：三值过滤、双臂生成、零丢弃等价。
"""

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

from benchmark.baseline.prenatal_rag_client.b1_filter import (
    filter_contexts,
    query_for_question,
)
from benchmark.baseline.prenatal_rag_client.generator import a_generate
from benchmark.baseline.prenatal_rag_client.evaluate import run_b1_evaluation
from prenatal_rag.conditions import GaWindow, parse_query_conditions


def _ctx(text: str, source_id: str) -> dict[str, str]:
    return {"source_id": source_id, "text": text}


def _fake_question(
    qid: str,
    text: str,
    *,
    gold_answer: str = "gold",
    gold_guides: tuple[str, ...] = ("guide-A", "guide-B"),
    must_have: tuple[str, ...] = ("关键陈述一", "关键陈述二"),
    difficulty: str = "L1",
) -> SimpleNamespace:
    return SimpleNamespace(
        question_id=qid,
        question=text,
        gold_answer=gold_answer,
        must_have_statements=list(must_have),
        gold_sources=[SimpleNamespace(guide=g) for g in gold_guides],
        difficulty=difficulty,
    )


async def _evidence_count_llm(system_prompt: str, user_prompt: str) -> str:
    n = len(re.findall(r"\[E\d+\]", user_prompt))
    return f"answer-with-{n}-evidence-chunks"


def test_filter_keeps_applicable_and_unknown_drops_inapplicable() -> None:
    query = parse_query_conditions("At 20 weeks gestation, fetal growth is restricted")
    contexts = [
        _ctx("18 to 24 weeks anatomy survey", "guide-A"),
        _ctx("NT measured at 11+0 to 13+6 weeks", "guide-B"),
        _ctx("plain protocol note", "guide-C"),
    ]
    result = filter_contexts(contexts, query)
    assert result.n_inapplicable == 1
    assert result.n_applicable == 1
    assert result.n_unknown == 1
    assert [c["source_id"] for c in result.dropped] == ["guide-B"]
    assert [c["source_id"] for c in result.kept] == ["guide-A", "guide-C"]


def test_a_generate_uses_evidence_count() -> None:
    q = _fake_question("T1", "20 weeks diagnosis")
    out = asyncio.run(a_generate(q, [_ctx("a", "s1"), _ctx("b", "s2")],
                                 llm_func=_evidence_count_llm))
    assert out == "answer-with-2-evidence-chunks"


def test_evaluate_zero_drop_arms_equal() -> None:
    q = _fake_question("T2", "20 weeks diagnosis")
    ctxs = [_ctx("18 to 24 weeks anatomy survey", "guide-A")]

    async def _run() -> dict:
        return await run_b1_evaluation(
            [q],
            lambda _q: ctxs,
            llm_func=_evidence_count_llm,
        )

    report = asyncio.run(_run())
    item = report["per_question"][0]
    assert item["n_dropped_inapplicable"] == 0
    assert item["answers_differ"] is False
    assert report["arms"]["b0_ctrl"]["final_score"] == report["arms"]["b1"]["final_score"]


def test_evaluate_drop_question_splits_generation() -> None:
    q = _fake_question("T3", "At 20 weeks gestation, fetal growth is restricted")
    ctxs = [
        _ctx("18 to 24 weeks anatomy survey", "guide-A"),
        _ctx("NT measured at 11+0 to 13+6 weeks", "guide-B"),
    ]

    async def _run() -> dict:
        return await run_b1_evaluation(
            [q],
            lambda _q: ctxs,
            llm_func=_evidence_count_llm,
        )

    report = asyncio.run(_run())
    item = report["per_question"][0]
    assert item["n_dropped_inapplicable"] == 1
    assert item["split_generation"] is True
    assert item["answers_differ"] is True


def test_query_for_question_derives_ga() -> None:
    q = _fake_question("T4", "At 30 weeks a growth-restricted fetus is seen")
    query = query_for_question(q)
    assert query.gestational_age is not None
    assert query.gestational_age.serialize() == "210:210"


def test_filter_ga_window_overlap() -> None:
    # 窗口级：20+0 点查询，18-24 周窗口覆盖 → Applicable；≥34 → Inapplicable。
    query = GaWindow.closed(140, 140)
    assert (
        filter_contexts(
            [_ctx("delivery at 18 to 24 weeks", "g1")],
            SimpleNamespace(gestational_age=query, population=frozenset(), technique=frozenset()),
        ).n_applicable
        == 1
    )