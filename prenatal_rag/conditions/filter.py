"""条件过滤：三值适用性分类（主文档 §4.2 / §5.1）。

B1 过滤器的核心：按 chunk 已抽取条件对给定查询条件做
:class:`~prenatal_rag.applicability.gestational_age.Applicability` 三值判断。

- Applicable  — 查询条件被 chunk 覆盖，可承担直接支持角色；
- Inapplicable— 有明确依据判定不适用（如孕周区间无交集、人群正对冲突），
  过滤时剔除，但召回/呈现阶段仍可作比较材料；
- Unknown     — 条件缺失或部分重叠（跨越边界），**不得剔除**，
  只能降级为"不能直接支持"。

多条同类条件时：任一窗口覆盖查询即 Applicable；无任一覆盖但有部分重叠
→ Unknown；全部无交集 → Inapplicable。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from prenatal_rag.applicability import Applicability
from prenatal_rag.conditions.extract import extract_conditions
from prenatal_rag.conditions.schema import (
    POPULATION_OPPOSITES,
    ChunkCondition,
    ConditionType,
    GaWindow,
)


def classify_text(
    text: str,
    query: QueryConditions,
    *,
    source_id: str = "",
    base_offset: int = 0,
) -> Applicability:
    """对一段任意文本（benchmark 上下文/阶段文本）直接做三值分类。

    便捷入口：先对文本抽条件，再对给定查询分类——用于 B1 过滤
    "以任意长度上下文为单位的独立判断"，无需证据存储 chunk 先建索引。
    base_offset 供锚点对齐引用；默认从 0 起（相对该段文本）。
    """
    conds = extract_conditions(
        text,
        anchor_id=0,
        source_id=source_id,
        base_offset=base_offset,
    )
    return classify(conds, query)


@dataclass(frozen=True)
class QueryConditions:
    """结构化的查询/任务适用条件（来自"任务与适用条件解析"）。

    三值语义：未约束的维度不影响判断（不贡献任何值）。
    """

    gestational_age: GaWindow | None = None
    population: frozenset[str] = field(default_factory=frozenset)
    technique: frozenset[str] = field(default_factory=frozenset)


def _window_direction(query: GaWindow, evidence: GaWindow) -> Applicability:
    """单窗口三值：全覆盖 Applicable，部分重叠 Unknown，无交集 Inapplicable。"""
    if not evidence.overlaps(query):
        return Applicability.INAPPLICABLE
    if evidence.covers(query):
        return Applicability.APPLICABLE
    return Applicability.UNKNOWN


def _same(superset: Iterable[str], subset: Iterable[str]) -> bool:
    return not set(superset).isdisjoint(set(subset))


def _classify_ga(
    conds: list[ChunkCondition], query: GaWindow | None
) -> Applicability | None:
    if query is None:
        return None
    ga_conds = [c for c in conds if c.condition_type == ConditionType.GESTATIONAL_AGE]
    if not ga_conds:
        return Applicability.UNKNOWN
    any_applicable = False
    any_unknown = False
    for c in ga_conds:
        evidence = GaWindow.parse(c.value)
        verdict = _window_direction(query, evidence)
        if verdict is Applicability.APPLICABLE:
            any_applicable = True
        elif verdict is Applicability.UNKNOWN:
            any_unknown = True
    if any_applicable:
        return Applicability.APPLICABLE
    if any_unknown:
        return Applicability.UNKNOWN
    return Applicability.INAPPLICABLE


def _classify_token(
    conds: list[ChunkCondition], ctype: ConditionType, query_set: frozenset[str]
) -> Applicability | None:
    if not query_set:
        return None
    present = frozenset(
        c.value for c in conds if c.condition_type == ctype
    )
    if not present:
        return Applicability.UNKNOWN
    if _same(query_set, present):
        return Applicability.APPLICABLE
    # 明确的人群正对（twin vs singleton 等）→ Inapplicable；
    # 其余既非命中也非正对 → Unknown。
    if ctype is ConditionType.POPULATION:
        for q in query_set:
            for p in present:
                if p in POPULATION_OPPOSITES.get(q, ()):
                    return Applicability.INAPPLICABLE
    return Applicability.UNKNOWN


def classify(
    chunk_conditions: list[ChunkCondition], query: QueryConditions
) -> Applicability:
    """对单个 chunk 的已抽条件做三值适用性分类。

    合并规则：任一类明确 Inapplicable → Inapplicable；
    否则任一 Unknown → Unknown；否则 Applicable。
    """
    verdicts: list[Applicability] = []
    for v in (
        _classify_ga(chunk_conditions, query.gestational_age),
        _classify_token(
            chunk_conditions, ConditionType.POPULATION, query.population
        ),
        _classify_token(
            chunk_conditions, ConditionType.TECHNIQUE, query.technique
        ),
    ):
        if v is not None:
            verdicts.append(v)
    if not verdicts:
        return Applicability.APPLICABLE
    if Applicability.INAPPLICABLE in verdicts:
        return Applicability.INAPPLICABLE
    if Applicability.UNKNOWN in verdicts:
        return Applicability.UNKNOWN
    return Applicability.APPLICABLE


def filter_chunks(
    indexed: Iterable[tuple[int, str, list[ChunkCondition]]],
    query: QueryConditions,
) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """B1 显式过滤：返回 (保留集, 剔除集)。

    drop 只含明确 Inapplicable 的 chunk；Unknown 与 Applicable 均保留
    （Unknown 不得被剔除，主文档 §4.2）。``indexed`` 产出
    (anchor_id, source_id, conditions)。
    """
    kept: list[tuple[int, str]] = []
    dropped: list[tuple[int, str]] = []
    for anchor_id, source_id, conds in indexed:
        verdict = classify(conds, query)
        if verdict is Applicability.INAPPLICABLE:
            dropped.append((anchor_id, source_id))
        else:
            kept.append((anchor_id, source_id))
    return kept, dropped