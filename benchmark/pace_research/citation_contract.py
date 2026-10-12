"""R4 引用契约：三检查（缺编号/越界/未覆盖必需陈述）+ 覆盖率。

预注册 pace-research-plan.md §7 第 1 条；r4-design.md §3。
纯函数，零 LLM。契约是**计数与报告**，不阻断生成；开发目标 ≥95% 是
工程验收目标，不是临床阈值。
"""

from __future__ import annotations

import re
from typing import Any

_CITATION_RE = re.compile(r"\[E(\d+)\]")


def check_citation_contract(
    answer: str,
    n_context: int,
    must_have_statements: list[str],
) -> dict[str, Any]:
    """检查答案是否满足引用契约，返回三检查结果与覆盖率。

    Parameters
    ----------
    answer : 生成的答案文本。
    n_context : 提供给生成器的上下文条数（合法编号 1..n_context）。
    must_have_statements : 必需陈述列表。

    Returns
    -------
    dict with:
      - has_citations: 是否含至少一个编号引用
      - invalid_citations: 越界编号列表（如 0、>n_context）
      - cited_indices: 合法编号（去重升序）
      - uncovered_statements: 未被任何有效引用覆盖的必需陈述
        （词法近似：陈述关键词未出现在被引上下文附近的答案文本中——
        精确判定需锚点级核验，此处为契约级检查）
      - statement_coverage: 有效引用覆盖的必需陈述数 / 全部必需陈述数
    """
    cited = [int(m.group(1)) for m in _CITATION_RE.finditer(answer)]
    valid = sorted({c for c in cited if 1 <= c <= n_context})
    invalid = sorted({c for c in cited if c < 1 or c > n_context})
    has_citations = bool(cited)

    uncovered: list[str] = []
    if must_have_statements and valid:
        answer_lower = answer.lower()
        for stmt in must_have_statements:
            keywords = [w for w in re.split(r"[，,。；;、\s]+", stmt) if len(w) > 2]
            if not keywords:
                continue
            # 词法近似：陈述的关键词出现在答案中即视为被覆盖
            # （精确的陈述-引用绑定需要锚点级对齐，属 R5 范围）
            covered = any(kw.lower() in answer_lower for kw in keywords)
            if not covered:
                uncovered.append(stmt)
    elif must_have_statements and not valid:
        uncovered = list(must_have_statements)

    total = len(must_have_statements)
    covered_n = total - len(uncovered)
    coverage = covered_n / total if total else None

    return {
        "has_citations": has_citations,
        "invalid_citations": invalid,
        "cited_indices": valid,
        "uncovered_statements": uncovered,
        "statement_coverage": coverage,
    }
