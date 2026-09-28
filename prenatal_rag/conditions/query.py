"""查询条件解析（主文档 §5.1 第 1 步的确定性首版）。

把用户/评测题目文本解析为 :class:`~prenatal_rag.conditions.filter.QueryConditions`：
- 孕周：窗口与单点全部经由 evidence 抽取器（``ga_window``/``ga_point`` 规格
  自带 hedge 与畸形 fail-closed）；取第一个窗口，无则 None；
- 人群：twin/singleton/monochorionic/dichorionic 等（复用词表）；
- 技术：仅强约束型标记（cfDNA/NT-only 等），保守收集。

三值语义不变：查不到的条件维度保持空集合/None，不假设存在。
查询侧不再保留更宽松的独立回退正则（R2-F5 修复）——否则 ``24+7 weeks`` /
``around 36 weeks`` / ``1 to 2 weeks`` 会在查询侧伪造孕周点，违反主文档
「未知即未知」的硬约束。
"""

from __future__ import annotations

from prenatal_rag.conditions.extract import extract_conditions
from prenatal_rag.conditions.filter import QueryConditions
from prenatal_rag.conditions.schema import ConditionType, GaWindow


def _ga_windows(text: str) -> list[GaWindow]:
    return [
        GaWindow.parse(c.value)
        for c in extract_conditions(text, anchor_id=0, source_id="_q", base_offset=0)
        if c.condition_type is ConditionType.GESTATIONAL_AGE
    ]


def _cond_values(text: str, ctype: ConditionType) -> frozenset[str]:
    return frozenset(
        c.value
        for c in extract_conditions(
            text, anchor_id=0, source_id="_q", base_offset=0
        )
        if c.condition_type is ctype
    )


def parse_query_conditions(text: str) -> QueryConditions:
    """从题目/临床文本推导查询适用条件（确定性、保守）。

    孕周取抽取器产出的第一个窗口（含单点形态 ``at 13 weeks``）；
    无则 None。人群/技术按词表命中收集。
    """
    windows = _ga_windows(text)
    ga = windows[0] if windows else None

    population = _cond_values(text, ConditionType.POPULATION)
    # 技术仅保留强约束标记，避免把“答案主题”误当查询条件。
    strong_technique = _cond_values(text, ConditionType.TECHNIQUE)
    technique = frozenset(v for v in strong_technique if _is_constraint_technique(v))
    return QueryConditions(
        gestational_age=ga,
        population=population,
        technique=technique,
    )


_CONSTRAINT_TECHNIQUES = frozenset(
    {
        "cfdna_screen",
        "nt_only",
        "transvaginal",
        "transabdominal",
        "harmonic_imaging",
    }
)


def _is_constraint_technique(value: str) -> bool:
    return value in _CONSTRAINT_TECHNIQUES


def describe(q: QueryConditions) -> str:
    """人类可读描述（用于报告）。"""
    parts: list[str] = []
    if q.gestational_age is not None:
        parts.append(f"GA {q.gestational_age}")
    if q.population:
        parts.append("人群 " + ",".join(sorted(q.population)))
    if q.technique:
        parts.append("技术 " + ",".join(sorted(q.technique)))
    return "; ".join(parts) if parts else "（无条件）"
