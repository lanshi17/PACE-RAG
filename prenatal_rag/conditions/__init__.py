"""chunk 级条件抽取与 B1 过滤（主文档 §4.1/§4.2/§5.1；批次文档 §5.4）。

三轴条件：孕周窗口（天）、人群 token、检查技术 token。确定性正则实现，
无 LLM、无网络、不依赖 ``benchmark.*``；证据存储 ``chunk_conditions``
表的物化入口见 :func:`index_conditions` 与 ``EvidenceStore.build_condition_index``。
"""

from __future__ import annotations

from prenatal_rag.conditions.extract import (
    ConditionExtractor,
    extract_conditions,
    index_conditions,
)
from prenatal_rag.conditions.filter import (
    QueryConditions,
    classify,
    classify_text,
    filter_chunks,
)
from prenatal_rag.conditions.query import describe, parse_query_conditions
from prenatal_rag.conditions.schema import (
    POPULATION_OPPOSITES,
    ChunkCondition,
    ConditionType,
    GaWindow,
)

__all__ = [
    "POPULATION_OPPOSITES",
    "ChunkCondition",
    "ConditionExtractor",
    "ConditionType",
    "GaWindow",
    "QueryConditions",
    "classify",
    "classify_text",
    "describe",
    "extract_conditions",
    "filter_chunks",
    "index_conditions",
    "parse_query_conditions",
]
