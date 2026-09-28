"""prenatal_rag_client —— B1 条件约束受控生成包。

复用冻结的 B0 检索结果（同检索、显式过滤），在检索与生成之间插入三值条件过滤，
再用固定受控生成器重生成答案。对每道题生成两个臂：

- **b0_ctrl**：不过滤（使用全部检索上下文），作为同生成器下的对照；
- **b1**：按题目查询条件丢弃明确 Inapplicable 的上下文后生成。

两臂仅差别在"是否过滤"，从而把条件处理对生成的效应隔离出来。
"""

from __future__ import annotations

from benchmark.baseline.prenatal_rag_client.b1_filter import FilterResult, filter_contexts
from benchmark.baseline.prenatal_rag_client.evaluate import (
    arm_score,
    arm_summary,
    run_b1_evaluation,
    score_arm,
)
from benchmark.baseline.prenatal_rag_client.generator import a_generate, generate_with_context
from benchmark.baseline.prenatal_rag_client.prompting import build_generation_messages

__all__ = [
    "FilterResult",
    "a_generate",
    "arm_score",
    "arm_summary",
    "build_generation_messages",
    "filter_contexts",
    "generate_with_context",
    "run_b1_evaluation",
    "score_arm",
]