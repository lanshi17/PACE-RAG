"""确定性条件抽取器（主文档 §5.1 第 3 步；批次文档 §5.4 的 chunk 级条件元数据）。

设计要点：
- PDF 连字（ﬁ ﬂ ﬀ ﬃ ﬄ）在匹配前折叠，偏移经映射表还原到原文，
  ``matched_text`` 恒为原文切片（span 可还原不变量）；
- GA 规格按列表顺序即优先级：已接受 span 包含新 span → 跳过，
  新 span 包含已接受 span → 替换（更长/更具体者胜，防重复记账）；
- 合理性守卫：窗口两端均须 ≥42 天（ viability 前的 ``1 to 2 weeks`` 随访
  间隔、``up to 5 weeks`` 等非孕周区间不产出 GA 条件）；
- hedge（around/approximately/about）、PDF 乱码（``11 e14`` / ``‡32``）与
  畸形（``24+7`` / ``22.3``）一律不抽取——fail closed，未知保留为未知；
- 纯函数：同一输入恒得同一输出；无 LLM、无网络、不依赖 ``benchmark.*``。
"""

from __future__ import annotations

import re
from typing import Callable, ClassVar, Iterable, Sequence

from prenatal_rag.conditions.schema import (
    ChunkCondition,
    ConditionType,
    GaWindow,
    GaWindowIsEmptyError,
)

_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}

_I = re.IGNORECASE
# 周数记法共用片段：分隔符覆盖 to/and/三种 dash（en/em/minus/ASCII hyphen）。
_SEP = r"(?:to|and|–|—|−|-)"
_WEEKS_OPT_PLUS = r"(?P<a>\d{1,2})(?:\s*\+\s*(?P<ad>[0-6]))?"
_WEEKS_OPT_PLUS_HI = r"(?P<b>\d{1,2})(?:\s*\+\s*(?P<bd>[0-6]))?"
_GUARD_DAYS = 42  # viability 前的天数不构成孕周窗口

# 单点形态；query 回退与抽取器共用同一正则（R2-F5 修复：查询侧不再有
# 更宽松的独立回退路径）。
_POINT_PATTERN = re.compile(
    r"\bat\s+(?:(?P<hedge>around|approximately|about)\s+)?(?P<a>\d{1,2})\s*weeks?\b",
    _I,
)

# R2-F4：匹配起点前若是 "数字 + "（悬挂加号），起点数字是被撕裂的畸形
# 天数千位（如 "24 + 7 and 26 + 0 weeks" 的 "7"），整段保留 Unknown。
_DANGLING_PLUS_RE = re.compile(r"\d\s*\+\s*$")

MatchBuilder = Callable[[re.Match[str]], "GaWindow | None"]

def _fold(text: str) -> tuple[str, list[int]]:
    """折叠 PDF 连字；返回（折叠文本, 折叠偏移→原文偏移映射，含末尾哨兵）。"""
    folded: list[str] = []
    mapping: list[int] = []
    for index, char in enumerate(text):
        expansion = _LIGATURES.get(char)
        if expansion is None:
            folded.append(char)
            mapping.append(index)
        else:
            folded.extend(expansion)
            mapping.extend([index] * len(expansion))
    mapping.append(len(text))
    return "".join(folded), mapping

def _build_closed(match: re.Match[str]) -> GaWindow:
    """``a``/``b``（可选 ``ad``/``bd`` 天数）命名组 → 双闭窗口（周 → 天）。

    用 :meth:`groupdict` 取可选组：外部规格（如消融子类）的正则可能不含
    ``ad``/``bd``，缺失按 0 天处理。
    """
    groups = match.groupdict()
    lower = int(groups["a"]) * 7 + (int(groups["ad"]) if groups.get("ad") else 0)
    upper = int(groups["b"]) * 7 + (int(groups["bd"]) if groups.get("bd") else 0)
    return GaWindow.closed(lower, upper)


def _day_component(match: re.Match[str]) -> int:
    """``a``（周）×7 + 可选 ``ad``（天）；缺失组按 0 天（F-10 修复：
    单侧形态也须计入 +M 天，``7N+M`` 全局算术）。
    """
    groups = match.groupdict()
    days = int(groups["a"]) * 7
    if groups.get("ad"):
        days += int(groups["ad"])
    return days


def _at_least(match: re.Match[str]) -> GaWindow:
    return GaWindow.at_least(_day_component(match))


def _at_most_days(match: re.Match[str]) -> GaWindow:
    return GaWindow.at_most(_day_component(match))


def _at_most_before(match: re.Match[str]) -> GaWindow:
    # "before 14 weeks" / "< 33 weeks"：排除第 N 周当天 → 至多 N*7-1 天。
    return GaWindow.at_most(_day_component(match) - 1)


def _point(match: re.Match[str]) -> GaWindow | None:
    # hedged（at around N weeks）不抽取：fail closed。
    if match.group("hedge"):
        return None
    day = int(match.group("a")) * 7
    return GaWindow.closed(day, day)


def _plausible(window: GaWindow) -> bool:
    """窗口两端均须 ≥42 天，剔除随访间隔等非孕周区间。"""
    if window.lower_days is not None and window.lower_days < _GUARD_DAYS:
        return False
    if window.upper_days is not None and window.upper_days < _GUARD_DAYS:
        return False
    return True


class ConditionExtractor:
    """规格可覆盖的确定性抽取器；子类可替换 ``_GA_SPECS`` 做消融实验。"""

    # (pattern_id, regex, builder)；列表顺序即优先级（先匹配者先占位）。
    _GA_SPECS: ClassVar[list[tuple[str, re.Pattern[str], MatchBuilder]]] = [
        (
            "ga_window",
            # (?<![\d+])：匹配起点不得紧邻数字或 "+"——否则 "24+7 and 26+0 weeks"
            # 中的伪影 "7 and 26+0 weeks" 会以畸形天数为周数回溯成窗（F-8/F-11 修复）。
            re.compile(
                rf"(?<![\d+])\b{_WEEKS_OPT_PLUS}\s*{_SEP}\s*{_WEEKS_OPT_PLUS_HI}\s*weeks?\b",
                _I,
            ),
            _build_closed,
        ),
        (
            "ga_or_more",
            re.compile(r"(?<![\d+])\b(?:at\s+)?(?P<a>\d{1,2})\s*weeks?\s+(?:or\s+more|or\s+later)\b", _I),
            _at_least,
        ),
        (
            "ga_at_least",
            re.compile(r"\bat least\s+(?P<a>\d{1,2})\s*weeks?\b", _I),
            _at_least,
        ),
        (
            "ga_ge",
            re.compile(r"≥\s*(?P<a>\d{1,2})(?:\s*\+\s*(?P<ad>[0-6]))?\s*weeks?\b"),
            _at_least,
        ),
        (
            "ga_from",
            re.compile(r"\bfrom\s+(?P<a>\d{1,2})\s*weeks?\b", _I),
            _at_least,
        ),
        (
            "ga_as_early_as",
            re.compile(r"\bas early as\s+(?P<a>\d{1,2})\s*(?:gestational\s+)?weeks?\b", _I),
            _at_least,
        ),
        (
            "ga_after",
            re.compile(r"\bafter\s+(?P<a>\d{1,2})(?:\s*\+\s*(?P<ad>[0-6]))?\s*weeks?\b", _I),
            _at_least,
        ),
        (
            "ga_up_to",
            re.compile(r"\bup to\s+(?P<a>\d{1,2})\s*weeks?\b", _I),
            _at_most_days,
        ),
        (
            "ga_before",
            re.compile(r"\bbefore\s+(?P<a>\d{1,2})\s*weeks?\b", _I),
            _at_most_before,
        ),
        (
            "ga_lt",
            re.compile(r"<\s*(?P<a>\d{1,2})\s*weeks?\b"),
            _at_most_before,
        ),
        (
            "ga_by",
            re.compile(r"\bby\s+(?P<a>\d{1,2})\s*weeks?\b", _I),
            _at_most_days,
        ),
        (
            "ga_le",
            re.compile(r"≤\s*(?P<a>\d{1,2})\s*weeks?\b"),
            _at_most_days,
        ),
        (
            "ga_point",
            _POINT_PATTERN,
            _point,
        ),
    ]

    _POPULATION_SPECS: ClassVar[list[tuple[str, re.Pattern[str]]]] = [
        ("monochorionic", re.compile(r"\bmonochorionic\b", _I)),
        ("dichorionic", re.compile(r"\bdichorionic\b", _I)),
        ("singleton", re.compile(r"\bsingletons?\b", _I)),
        ("twin", re.compile(r"\btwins?\b", _I)),
        ("triplet", re.compile(r"\btriplets?\b", _I)),
        ("unselected", re.compile(r"\bunselected\b", _I)),
        ("high_risk", re.compile(r"\bhigh[- ]risk\b", _I)),
        ("low_risk", re.compile(r"\blow[- ]risk\b", _I)),
        ("previous_ptb", re.compile(r"\bprevious\s+(?:preterm\s+)?(?:PTB|birth)\b", _I)),
        ("increased_nt", re.compile(r"\bincreased\s+nuchal\s+translucency\b", _I)),
        ("utd_a1", re.compile(r"\bUTD\s+A1\b", _I)),
        ("utd_a2_3", re.compile(r"\bUTD\s+A2[-–]3\b", _I)),
        ("high_chance", re.compile(r"\bhigh\s+chance\b", _I)),
        ("low_chance", re.compile(r"\blow\s+chance\b", _I)),
        ("ivf", re.compile(r"\bIVF\b", _I)),
        ("obese", re.compile(r"\bobese\b", _I)),
    ]

    # 缩写词表大小写敏感，避免词内误命中；含空格/连字跨界的长形态在前。
    _TECHNIQUE_SPECS: ClassVar[list[tuple[str, re.Pattern[str]]]] = [
        ("cfdna_screen", re.compile(r"\b(?:cell[- ]free\s+DNA|cfDNA)\b", _I)),
        ("nt_only", re.compile(r"\b(?:NT|nuchal\s+translucency)[- ]only\b", _I)),
        ("first_trimester_screening", re.compile(r"\bfirst[- ]trimester\s+screening\b", _I)),
        ("second_trimester_screening", re.compile(r"\bsecond[- ]trimester\s+screening\b", _I)),
        (
            "first_or_second_trimester_screening",
            re.compile(r"\bfirst[- ]+or[- ]+second[- ]+trimester\s+screening\b", _I),
        ),
        ("combined_test", re.compile(r"\bcombined\s+test\b", _I)),
        ("nipt", re.compile(r"\bNIPT\b")),
        ("nt", re.compile(r"\bNT\b")),
        ("nt", re.compile(r"\bnuchal\s+translucency\b", _I)),
        ("dv", re.compile(r"\bDV\b")),
        ("dv", re.compile(r"\bductus\s+venosus\b", _I)),
        ("stv", re.compile(r"\bSTV\b")),
        ("ua_edf", re.compile(r"\bUA[- ]?EDF\b")),
        ("harmonic_imaging", re.compile(r"\b(?:tissue\s+)?harmonic\s+imaging\b", _I)),
        ("transvaginal", re.compile(r"\btransvaginal\b", _I)),
        ("transabdominal", re.compile(r"\btransabdominal\b", _I)),
        ("field_1.5t", re.compile(r"\b1\.5\s*T\b")),
        ("field_3t", re.compile(r"\b3\s*T\b")),
        ("four_chamber", re.compile(r"\bfour[- ]chamber\b", _I)),
        ("three_vessel", re.compile(r"\b3VV\b|\bthree[- ]vessel\b", _I)),
    ]

    def extract(
        self,
        text: str,
        *,
        anchor_id: int,
        source_id: str,
        base_offset: int = 0,
    ) -> list[ChunkCondition]:
        """抽取三轴条件；输出按 (类型, 起点, pattern_id) 排序，保证确定性。"""
        folded, mapping = _fold(text)
        conditions: list[ChunkCondition] = []
        conditions.extend(self._extract_ga(folded, mapping, text, anchor_id, source_id, base_offset))
        conditions.extend(
            self._extract_tokens(
                folded, mapping, text, anchor_id, source_id, base_offset,
                self._POPULATION_SPECS, ConditionType.POPULATION, "pop",
            )
        )
        conditions.extend(
            self._extract_tokens(
                folded, mapping, text, anchor_id, source_id, base_offset,
                self._TECHNIQUE_SPECS, ConditionType.TECHNIQUE, "tech",
            )
        )
        conditions.sort(
            key=lambda c: (c.condition_type.value, c.char_start, c.char_end, c.pattern_id)
        )
        return conditions

    def _condition(
        self,
        text: str,
        mapping: list[int],
        start: int,
        end: int,
        anchor_id: int,
        source_id: str,
        base_offset: int,
        condition_type: ConditionType,
        value: str,
        pattern_id: str,
    ) -> ChunkCondition:
        char_start = mapping[start]
        char_end = mapping[end]
        return ChunkCondition(
            anchor_id=anchor_id,
            source_id=source_id,
            condition_type=condition_type,
            value=value,
            char_start=base_offset + char_start,
            char_end=base_offset + char_end,
            matched_text=text[char_start:char_end],
            pattern_id=pattern_id,
        )

    @staticmethod
    def _merge_condition(
        accepted: list[ChunkCondition], candidate: ChunkCondition
    ) -> list[ChunkCondition]:
        """span 消重规则（GA 与 token 共用）：

        已接受 span 包含新 span → 跳过（返回原列表）；
        新 span 包含已接受 span → 替换（更长/更具体者胜）；
        无包含关系 → 追加。
        """
        start, end = candidate.char_start, candidate.char_end
        if any(
            c.char_start <= start and end <= c.char_end for c in accepted
        ):
            return accepted
        kept = [
            c
            for c in accepted
            if not (start <= c.char_start and c.char_end <= end)
        ]
        return [*kept, candidate]

    def _extract_ga(
        self,
        folded: str,
        mapping: list[int],
        text: str,
        anchor_id: int,
        source_id: str,
        base_offset: int,
    ) -> list[ChunkCondition]:
        accepted: list[ChunkCondition] = []
        for pattern_id, pattern, build in self._GA_SPECS:
            for match in pattern.finditer(folded):
                # R2-F4：匹配起点前若是 "数字 + "（悬挂加号），说明起点数字是
                # 被撕裂的畸形天数千位（如 "24 + 7 and 26 + 0 weeks" 的 "7"），
                # 整段保留 Unknown，不产出伪造窗口。
                if _DANGLING_PLUS_RE.search(folded, 0, match.start()):
                    continue
                try:
                    window = build(match)
                except GaWindowIsEmptyError:
                    # 真实语料存在倒置区间（如 "8 and 2 weeks"，跨栏/断行伪影）：
                    # 保留 Unknown，不产出条件，也不崩溃。
                    continue
                if window is None or not _plausible(window):
                    continue
                condition = self._condition(
                    text, mapping, match.start(), match.end(),
                    anchor_id, source_id, base_offset,
                    ConditionType.GESTATIONAL_AGE, window.serialize(), pattern_id,
                )
                accepted = self._merge_condition(accepted, condition)
        return accepted

    def _extract_tokens(
        self,
        folded: str,
        mapping: list[int],
        text: str,
        anchor_id: int,
        source_id: str,
        base_offset: int,
        specs: Sequence[tuple[str, re.Pattern[str]]],
        condition_type: ConditionType,
        prefix: str,
    ) -> list[ChunkCondition]:
        accepted: list[ChunkCondition] = []
        for token, pattern in specs:
            for match in pattern.finditer(folded):
                condition = self._condition(
                    text, mapping, match.start(), match.end(),
                    anchor_id, source_id, base_offset,
                    condition_type, token, f"{prefix}_{token}",
                )
                accepted = self._merge_condition(accepted, condition)
        return accepted


def extract_conditions(
    text: str,
    *,
    anchor_id: int = 0,
    source_id: str = "",
    base_offset: int = 0,
) -> list[ChunkCondition]:
    """模块级便捷入口：默认规格的 :class:`ConditionExtractor`。"""
    return ConditionExtractor().extract(
        text, anchor_id=anchor_id, source_id=source_id, base_offset=base_offset
    )


def index_conditions(
    items: Iterable[tuple[int, str, str]],
    *,
    store: "object",
    base_offsets: dict[int, int] | None = None,
) -> int:
    """对 (anchor_id, source_id, text) 流抽取条件并写回存储；返回写入条数。

    与存储解耦：``base_offsets`` 给出各 anchor 在规范化文本内的绝对偏移，
    使 span 锚点自洽（缺省按 0 处理）。
    """
    offsets = base_offsets or {}
    written = 0
    for anchor_id, source_id, text in items:
        conditions = extract_conditions(
            text,
            anchor_id=anchor_id,
            source_id=source_id,
            base_offset=offsets.get(anchor_id, 0),
        )
        store.rewrite_chunk_conditions(anchor_id, conditions)  # type: ignore[attr-defined]
        written += len(conditions)
    return written
