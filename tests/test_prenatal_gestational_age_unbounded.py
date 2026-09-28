"""单侧（无界）孕周区间：GestationalAgeInterval 扩展测试（SPEC-conditions Feature G）。

下界或上界为 ``None`` 表示该侧无界；比较原语把 ``None`` 视为 −∞/+∞。
双闭/双开语义与既有双侧区间一致，既有行为不得改变（原测试文件冻结）。

区间常量用工厂函数惰性构造：特性缺失时每个测试各自在行为处失败，
而不是在收集阶段整体报错（RED 质量要求）。
"""

from __future__ import annotations

import pytest

from prenatal_rag.applicability import (
    Applicability,
    GestationalAge,
    GestationalAgeInterval,
    apply_ga_interval,
    apply_ga_point,
)


def lower_only() -> GestationalAgeInterval:
    """\"from 10 weeks onwards\" / \"≥ 34+0 weeks\" 形态。"""
    return GestationalAgeInterval(lower_days=70, upper_days=None)


def upper_only_incl() -> GestationalAgeInterval:
    """\"up to 24 weeks\"：上界包含。"""
    return GestationalAgeInterval(lower_days=None, upper_days=168)


def upper_only_excl() -> GestationalAgeInterval:
    """\"before 14 weeks\"：上界排除第 98 天（14+0）。"""
    return GestationalAgeInterval(lower_days=None, upper_days=98, upper_inclusive=False)


def after_30_0() -> GestationalAgeInterval:
    """\"permitted after 30+0 weeks\"：下界排除第 210 天。"""
    return GestationalAgeInterval(lower_days=210, upper_days=None, lower_inclusive=False)


def ge_34_0() -> GestationalAgeInterval:
    """\"≥ 34+0 weeks\"：下界包含第 238 天。"""
    return GestationalAgeInterval(lower_days=238, upper_days=None)


def mid() -> GestationalAgeInterval:
    return GestationalAgeInterval.parse("18+0 to 24+0")


class TestUnboundedConstruction:
    def test_lower_only_construction(self) -> None:
        interval = lower_only()
        assert interval.lower_days == 70
        assert interval.upper_days is None

    def test_upper_only_construction(self) -> None:
        interval = GestationalAgeInterval(lower_days=None, upper_days=97)
        assert interval.lower_days is None
        assert interval.upper_days == 97

    def test_fully_unbounded_allowed_and_contains_everything(self) -> None:
        interval = GestationalAgeInterval(lower_days=None, upper_days=None)
        assert interval.contains_point(GestationalAge(0))
        assert interval.contains_point(GestationalAge(300))

    def test_concrete_inversion_still_rejected(self) -> None:
        with pytest.raises(ValueError):
            GestationalAgeInterval(lower_days=100, upper_days=99)


class TestUnboundedContains:
    def test_lower_only_contains_boundary_and_later(self) -> None:
        interval = lower_only()
        assert interval.contains_point(GestationalAge(70))
        assert interval.contains_point(GestationalAge(200))
        assert not interval.contains_point(GestationalAge(69))

    def test_fully_unbounded_covers_upper_only(self) -> None:
        # 下界比较的 b=None 分支：无下界证据被 [70,∞) 覆盖 → 比较原语走 True 分支。
        assert lower_only().covers(upper_only_incl())

    def test_empty_interval_after_exclusive_shrink(self) -> None:
        # 排他边界收缩为空集（13+6 排他 ~ 14+0 排他）：covers/overlaps 均为 False。
        empty = GestationalAgeInterval(
            lower_days=97, upper_days=98, lower_inclusive=False, upper_inclusive=False
        )
        assert empty._effective_bounds() is None
        assert empty.covers(mid()) is False
        assert empty.overlaps(mid()) is False

    def test_parse_rejects_unparsable_text(self) -> None:
        with pytest.raises(ValueError):
            GestationalAgeInterval.parse("garbage")

    def test_parse_weeks_rejects_unparsable_text(self) -> None:
        with pytest.raises(ValueError):
            GestationalAgeInterval.parse_weeks("garbage")
    def test_upper_only_contains_early_and_boundary(self) -> None:
        interval = upper_only_incl()
        assert interval.contains_point(GestationalAge(0))
        assert interval.contains_point(GestationalAge(168))
        assert not interval.contains_point(GestationalAge(169))

    def test_exclusive_upper_excludes_boundary_day(self) -> None:
        # "before 14 weeks" 排除第 98 天（14+0）本身
        interval = upper_only_excl()
        assert not interval.contains_point(GestationalAge(98))
        assert interval.contains_point(GestationalAge(97))

    def test_exclusive_lower_excludes_boundary_day(self) -> None:
        # "permitted after 30+0 weeks" 排除第 210 天（30+0）本身
        interval = after_30_0()
        assert not interval.contains_point(GestationalAge(210))
        assert interval.contains_point(GestationalAge(211))


class TestUnboundedRelations:
    def test_overlaps_is_symmetric_with_unbounded_side(self) -> None:
        assert lower_only().overlaps(mid())
        assert mid().overlaps(lower_only())
        assert upper_only_incl().overlaps(mid())
        early = GestationalAgeInterval.parse("8+0 to 9+6")
        assert not lower_only().overlaps(early)
        assert not early.overlaps(lower_only())

    def test_covers_with_unbounded_side(self) -> None:
        assert lower_only().covers(mid())
        assert not mid().covers(lower_only())
        assert upper_only_incl().covers(GestationalAgeInterval.parse("14+0 to 24+0"))
        # 上界排他时，覆盖到 14+0（第 98 天）的区间不被 "before 14 weeks" 覆盖
        assert not upper_only_excl().covers(GestationalAgeInterval.parse("13+6 to 14+0"))


class TestUnboundedThreeValued:
    def test_apply_ga_point_one_sided(self) -> None:
        assert apply_ga_point(lower_only(), GestationalAge(200)) is Applicability.APPLICABLE
        assert apply_ga_point(lower_only(), GestationalAge(60)) is Applicability.INAPPLICABLE
        assert (
            apply_ga_point(upper_only_excl(), GestationalAge(98))
            is Applicability.INAPPLICABLE
        )
        assert (
            apply_ga_point(upper_only_excl(), GestationalAge(97)) is Applicability.APPLICABLE
        )

    def test_apply_ga_interval_evidence_covers_query(self) -> None:
        assert apply_ga_interval(lower_only(), mid()) is Applicability.APPLICABLE
        assert (
            apply_ga_interval(
                upper_only_incl(), GestationalAgeInterval.parse("14+0 to 24+0")
            )
            is Applicability.APPLICABLE
        )

    def test_apply_ga_interval_query_crossing_boundary_is_unknown(self) -> None:
        # 查询区间跨越单侧证据边界：既不无交集也不被覆盖 → Unknown（不取中点）
        assert apply_ga_interval(mid(), lower_only()) is Applicability.UNKNOWN

    def test_apply_ga_interval_disjoint_is_inapplicable(self) -> None:
        early = GestationalAgeInterval.parse("8+0 to 9+6")
        assert apply_ga_interval(lower_only(), early) is Applicability.INAPPLICABLE
        assert apply_ga_interval(ge_34_0(), early) is Applicability.INAPPLICABLE


class TestTwoSidedUnchanged:
    """双侧既有行为回归装甲（原断言冻结文件之外的冗余防线）。"""

    def test_parse_still_two_sided(self) -> None:
        interval = GestationalAgeInterval.parse("11+0 to 13+6")
        assert (interval.lower_days, interval.upper_days) == (77, 97)
        assert interval.lower_inclusive and interval.upper_inclusive

    def test_parse_weeks_still_week_starts(self) -> None:
        interval = GestationalAgeInterval.parse_weeks("18 to 24 weeks")
        assert (interval.lower_days, interval.upper_days) == (126, 168)
