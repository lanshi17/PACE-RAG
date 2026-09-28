"""条件 schema：GaWindow、条件类型、chunk 条件记录与人群正对（主文档 §4.1/§4.2）。

设计约定（与 filter/query/evidence_store 的既有消费方一致）：
- ``GaWindow`` 孕周窗口以天存储，单侧 ``None`` 表示无界，边界一律包含
  （"before 14 weeks" → ``at_most(97)``，与互斥表述给出同一天集合）；
  ``serialize()``/``parse()`` 采用 ``"lo:hi"`` 紧凑格式（无界侧留空）。
- ``ChunkCondition`` 是行式条件记录（每条匹配一行），``to_row()`` 对齐
  证据存储 ``chunk_conditions`` 表的插入列序。
- ``POPULATION_OPPOSITES`` 是人群 token 的明确正对表，供三值分类判
  Inapplicable；不在表中的组合一律保留 Unknown，不得推断。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConditionType(str, Enum):
    """条件轴：孕周窗口 / 人群 / 检查技术。"""

    GESTATIONAL_AGE = "gestational_age"
    POPULATION = "population"
    TECHNIQUE = "technique"

    def __str__(self) -> str:
        return self.value


class GaWindowIsEmptyError(ValueError):
    """GaWindow 构造参数非法（负数天数或下界大于上界）。"""


@dataclass(frozen=True)
class GaWindow:
    """孕周窗口（天）；单侧 ``None`` 表示无界，边界包含。"""

    lower_days: int | None
    upper_days: int | None

    def __post_init__(self) -> None:
        for name in ("lower_days", "upper_days"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise GaWindowIsEmptyError(f"孕周天数不能为负: {name}={value}")
        if (
            self.lower_days is not None
            and self.upper_days is not None
            and self.lower_days > self.upper_days
        ):
            raise GaWindowIsEmptyError(
                f"孕周窗口下界大于上界: {self.lower_days} > {self.upper_days}"
            )

    @classmethod
    def closed(cls, lower_days: int, upper_days: int) -> "GaWindow":
        return cls(lower_days=lower_days, upper_days=upper_days)

    @classmethod
    def at_least(cls, lower_days: int) -> "GaWindow":
        return cls(lower_days=lower_days, upper_days=None)

    @classmethod
    def at_most(cls, upper_days: int) -> "GaWindow":
        return cls(lower_days=None, upper_days=upper_days)

    def serialize(self) -> str:
        """``"lo:hi"`` 紧凑格式；无界侧留空（``"238:"`` / ``":168"``）。"""
        lower = "" if self.lower_days is None else str(self.lower_days)
        upper = "" if self.upper_days is None else str(self.upper_days)
        return f"{lower}:{upper}"

    @classmethod
    def parse(cls, payload: str) -> "GaWindow":
        """解析 ``serialize()`` 的产物；保证 ``parse(serialize()) == self``。"""
        parts = str(payload).split(":")
        if len(parts) != 2:
            raise GaWindowIsEmptyError(f"无法解析孕周窗口 {payload!r}：期望 lo:hi")
        try:
            lower = int(parts[0]) if parts[0] else None
            upper = int(parts[1]) if parts[1] else None
        except ValueError as exc:
            raise GaWindowIsEmptyError(
                f"无法解析孕周窗口 {payload!r}：{exc}"
            ) from exc
        return cls(lower_days=lower, upper_days=upper)

    def __str__(self) -> str:
        if self.lower_days is None and self.upper_days is None:
            return "(-∞, ∞)天"
        if self.lower_days is None:
            return f"(-∞, {self.upper_days}]天"
        if self.upper_days is None:
            return f"[{self.lower_days}, ∞)天"
        return f"[{self.lower_days}, {self.upper_days}]天"

    def overlaps(self, other: "GaWindow") -> bool:
        """两窗口的天集合是否有交集（``None`` 视为 ±∞，边界包含）。"""
        if (
            self.lower_days is not None
            and other.upper_days is not None
            and self.lower_days > other.upper_days
        ):
            return False
        if (
            other.lower_days is not None
            and self.upper_days is not None
            and other.lower_days > self.upper_days
        ):
            return False
        return True

    def covers(self, other: "GaWindow") -> bool:
        """other 的全部有效天是否都落在 self 内（``None`` 视为 ±∞）。"""
        if self.lower_days is not None:
            if other.lower_days is None or self.lower_days > other.lower_days:
                return False
        if self.upper_days is not None:
            if other.upper_days is None or other.upper_days > self.upper_days:
                return False
        return True


# 人群 token 的明确正对：查询 token → 与之冲突的 chunk token。
# 仅记录有明确临床语义的对立；未列出的组合不得判 Inapplicable。
POPULATION_OPPOSITES: dict[str, tuple[str, ...]] = {
    "singleton": ("twin", "triplet"),
    "twin": ("singleton",),
    "triplet": ("singleton",),
    "monochorionic": ("dichorionic",),
    "dichorionic": ("monochorionic",),
    "high_chance": ("low_chance",),
    "low_chance": ("high_chance",),
}


@dataclass(frozen=True)
class ChunkCondition:
    """一条 chunk 级条件记录（每处匹配一行）。

    ``value`` 的语义随 ``condition_type``：
    - GESTATIONAL_AGE：``GaWindow.serialize()``（如 ``"77:97"``）；
    - POPULATION / TECHNIQUE：规范化 token（如 ``"twin"`` / ``"cfdna_screen"``）。
    ``char_start/char_end`` 为相对规范化文本的绝对偏移（含 base_offset），
    ``matched_text`` 为原文切片；``pattern_id`` 记录命中的抽取规格。
    """

    anchor_id: int
    source_id: str
    condition_type: ConditionType
    value: str
    char_start: int
    char_end: int
    matched_text: str
    pattern_id: str

    def to_row(self) -> tuple[int, str, str, int, int, str, str]:
        """对齐 ``chunk_conditions`` 表插入列序。"""
        return (
            self.anchor_id,
            self.condition_type.value,
            self.value,
            self.char_start,
            self.char_end,
            self.matched_text,
            self.pattern_id,
        )
