"""B1 三值过滤：对 benchmark 上下文记录做适用性分类并剔除 Inapplicable。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from prenatal_rag.applicability import Applicability
from prenatal_rag.conditions import classify_text, parse_query_conditions


@dataclass
class FilterResult:
    kept: list[dict[str, str]]
    dropped: list[dict[str, str]]
    verdicts: list[Applicability]
    query: Any = None
    n_applicable: int = field(default=0)
    n_unknown: int = field(default=0)
    n_inapplicable: int = field(default=0)


def filter_contexts(
    contexts: list[dict[str, str]],
    query: Any,
) -> FilterResult:
    """按查询条件三值过滤上下文。

    - Applicable  → 保留；
    - Unknown     → 保留（无明确证据判不适用，不得剔除）；
    - Inapplicable→ 剔除。
    """
    verdicts = [
        classify_text(str(context.get("text") or ""), query)
        for context in contexts
    ]
    kept: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []
    n_app = n_unk = n_inapp = 0
    for context, verdict in zip(contexts, verdicts):
        if verdict is Applicability.INAPPLICABLE:
            dropped.append(context)
            n_inapp += 1
        else:
            kept.append(context)
            if verdict is Applicability.APPLICABLE:
                n_app += 1
            else:
                n_unk += 1
    return FilterResult(
        kept=kept,
        dropped=dropped,
        verdicts=verdicts,
        query=query,
        n_applicable=n_app,
        n_unknown=n_unk,
        n_inapplicable=n_inapp,
    )


def query_for_question(question: Any) -> Any:
    """从题目文本派生查询条件（确定性）。"""
    return parse_query_conditions(question.question)