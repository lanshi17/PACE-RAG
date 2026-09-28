"""孕周时间轴：以天存储、区间开闭边界、三值适用性。

PACE 主文档 §4.2 的硬约束：

1. 孕周以天存储：``22+3 = 157`` 天，绝不使用 22.3 周这类小数；
2. 输入区间跨越规则边界时不能取中点判断，只能保留 Unknown；
3. 缺失孕周或缺失证据适用区间时保留 Unknown，模型预测不能补成事实；
4. 明确不适用（Inapplicable）的材料不能支持当前个体建议，
   但仍可作为比较或解释材料呈现。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_GA_PLUS_FULL_RE = re.compile(r"\s*(\d{1,2})\s*\+\s*([0-6])\s*")
_GA_WINDOW_RE = re.compile(
    r"(\d{1,2})\s*\+\s*([0-6])\s*(?:–|—|−|-|to|to)\s*(\d{1,2})\s*\+\s*([0-6])"
)
_WEEKS_WINDOW_RE = re.compile(r"(\d{1,2})\s*(?:–|—|−|-|to)\s*(\d{1,2})\s*weeks?")


class Applicability(str, Enum):
    """三值适用性：applicability(q, e) ∈ {Applicable, Inapplicable, Unknown}。"""

    APPLICABLE = "Applicable"
    """证据覆盖查询的全部条件，可承担直接支持角色。"""

    INAPPLICABLE = "Inapplicable"
    """有明确依据判定不适用；不得支持当前个体建议，可作比较/解释材料。"""

    UNKNOWN = "Unknown"
    """条件缺失或查询跨越边界；保留未知，不得由生成器补全。"""

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class GestationalAge:
    """以天存储的孕周点：22+3 → 157 天。"""

    days: int

    def __post_init__(self) -> None:
        if self.days < 0:
            raise ValueError(f"孕周天数不能为负: {self.days}")

    @property
    def weeks(self) -> int:
        return self.days // 7

    @property
    def day_in_week(self) -> int:
        return self.days % 7

    @classmethod
    def parse(cls, text: str) -> "GestationalAge":
        """解析 ``N+M`` 形式孕周；拒绝小数周（22.3 周）与 ``M > 6``。"""
        match = _GA_PLUS_FULL_RE.fullmatch(str(text))
        if not match:
            raise ValueError(f"无法解析孕周 {text!r}：期望 N+M 形式（如 22+3）")
        weeks, days = int(match.group(1)), int(match.group(2))
        return cls(days=weeks * 7 + days)

    def __str__(self) -> str:
        return f"{self.weeks}+{self.day_in_week}"


def _lower_le(a: int | None, b: int | None) -> bool:
    """下界比较 ``a <= b``；``None`` 视为 −∞（因此恒不超过任何下界）。"""
    if b is None:
        return True
    return a is None or a <= b


def _upper_ge(a: int | None, b: int | None) -> bool:
    """上界比较 ``a >= b``；``None`` 视为 +∞（因此恒不小于任何上界）。"""
    if a is None:
        return True
    return b is not None and a >= b


def _le(a: int | None, b: int | None) -> bool:
    """跨端点比较（下界 vs 上界）；任一侧 ``None``（±∞）时恒真。"""
    return a is None or b is None or a <= b


@dataclass(frozen=True)
class GestationalAgeInterval:
    """孕周区间；任一侧可为 ``None`` 表示该侧无界。

    边界语义按整数天集合处理：开边界即排除该天；``lower_days=None`` 视为 −∞，
    ``upper_days=None`` 视为 +∞（条款级 ``from N weeks onwards`` / ``after N+0`` /
    ``before N weeks`` 等单侧形态）。四个比较原语（contains_point / covers /
    overlaps）均基于化简后的有效天集合。
    """

    lower_days: int | None
    upper_days: int | None
    lower_inclusive: bool = True
    upper_inclusive: bool = True

    def __post_init__(self) -> None:
        if (
            self.lower_days is not None
            and self.upper_days is not None
            and self.lower_days > self.upper_days
        ):
            raise ValueError(
                f"孕周区间下界大于上界: {self.lower_days} > {self.upper_days}"
            )

    @classmethod
    def parse(cls, text: str) -> "GestationalAgeInterval":
        """解析 ``11+0–13+6`` / ``11+0 to 13+6`` 形式的孕周区间（双闭）。"""
        match = _GA_WINDOW_RE.search(str(text))
        if not match:
            raise ValueError(f"无法解析孕周区间 {text!r}：期望 N+M–P+Q 形式")
        lower = int(match.group(1)) * 7 + int(match.group(2))
        upper = int(match.group(3)) * 7 + int(match.group(4))
        return cls(lower_days=lower, upper_days=upper)

    @classmethod
    def parse_weeks(cls, text: str) -> "GestationalAgeInterval":
        """解析 ``18 to 24 weeks`` / ``18–24 weeks`` 形式的周界区间。

        周界映射为整周起点（N 周 → 7N 天）：下界取 N+0，上界取 M+0。
        条款是否实际覆盖到 M+6（如“到 24 周底”），须由条款级抽取显式给出，
        本方法不得擅自外推。
        """
        match = _WEEKS_WINDOW_RE.search(str(text))
        if not match:
            raise ValueError(f"无法解析周界区间 {text!r}：期望 N to M weeks 形式")
        return cls(
            lower_days=int(match.group(1)) * 7,
            upper_days=int(match.group(2)) * 7,
        )

    def _effective_bounds(self) -> tuple[int | None, int | None] | None:
        """化简为有效天集合的两端；空集返回 ``None``。

        无界侧保持 ``None``（−∞/+∞）；仅双侧均为具体天数时才可能为空集。
        """
        lower: int | None
        upper: int | None
        lower = (
            None
            if self.lower_days is None
            else self.lower_days + (0 if self.lower_inclusive else 1)
        )
        upper = (
            None
            if self.upper_days is None
            else self.upper_days - (0 if self.upper_inclusive else 1)
        )
        if lower is not None and upper is not None and lower > upper:
            return None
        return lower, upper

    def contains_point(self, ga: GestationalAge) -> bool:
        """单日孕周是否落在区间内（尊重开闭边界与无界侧）。"""
        bounds = self._effective_bounds()
        if bounds is None:
            return False
        lower, upper = bounds
        if lower is not None and ga.days < lower:
            return False
        if upper is not None and ga.days > upper:
            return False
        return True

    def covers(self, other: "GestationalAgeInterval") -> bool:
        """other 的全部有效天是否都落在 self 内（``None`` 按 ±∞ 比较）。"""
        mine = self._effective_bounds()
        theirs = other._effective_bounds()
        if mine is None or theirs is None:
            return False
        return _lower_le(mine[0], theirs[0]) and _upper_ge(mine[1], theirs[1])

    def overlaps(self, other: "GestationalAgeInterval") -> bool:
        """两区间的有效天集合是否有交集（``None`` 按 ±∞ 比较）。"""
        mine = self._effective_bounds()
        theirs = other._effective_bounds()
        if mine is None or theirs is None:
            return False
        return _le(mine[0], theirs[1]) and _le(theirs[0], mine[1])


def apply_ga_point(
    evidence: GestationalAgeInterval | None,
    ga: GestationalAge,
) -> Applicability:
    """单日孕周查询的三值判断：界内 Applicable，界外明确 Inapplicable。

    单日点不存在“部分重叠”，因此不产生 Unknown；缺证据区间仍为 Unknown。
    """
    if evidence is None:
        return Applicability.UNKNOWN
    if evidence.contains_point(ga):
        return Applicability.APPLICABLE
    return Applicability.INAPPLICABLE


def apply_ga_interval(
    evidence: GestationalAgeInterval | None,
    query: GestationalAgeInterval | None,
) -> Applicability:
    """区间对区间的三值判断（主文档 §4.2）。

    - 任一侧缺失 → Unknown：缺失条件不能由生成器或模型补成事实；
    - 无交集 → Inapplicable：明确不适用；
    - 证据区间完整覆盖查询区间 → Applicable；
    - 部分重叠（查询跨越边界）→ Unknown：不能取中点，不能推断整体适用。
    """
    if evidence is None or query is None:
        return Applicability.UNKNOWN
    if not evidence.overlaps(query):
        return Applicability.INAPPLICABLE
    if evidence.covers(query):
        return Applicability.APPLICABLE
    return Applicability.UNKNOWN
