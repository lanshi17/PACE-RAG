"""孕周解析与三值适用性（prenatal_rag.applicability）测试。"""

from __future__ import annotations

import pytest

from prenatal_rag.applicability import (
    Applicability,
    GestationalAge,
    GestationalAgeInterval,
    apply_ga_interval,
    apply_ga_point,
)


class TestGestationalAge:
    def test_parses_to_days(self) -> None:
        # 22+3 = 154 + 3 = 157 天（主文档 §4.2 的硬约束）
        ga = GestationalAge.parse("22+3")
        assert ga.days == 157
        assert (ga.weeks, ga.day_in_week) == (22, 3)

    def test_roundtrip(self) -> None:
        assert str(GestationalAge.parse("11+0")) == "11+0"
        assert str(GestationalAge.parse("13+6")) == "13+6"

    def test_tolerates_spaces(self) -> None:
        assert GestationalAge.parse(" 22 + 3 ").days == 157

    @pytest.mark.parametrize("bad", ["22.3", "24+7", "abc", "", "+3", "22+"]
    )
    def test_rejects_invalid_forms(self, bad: str) -> None:
        with pytest.raises(ValueError):
            GestationalAge.parse(bad)

    def test_negative_days_rejected(self) -> None:
        with pytest.raises(ValueError):
            GestationalAge(days=-1)


class TestGestationalAgeInterval:
    def test_parse_plus_window(self) -> None:
        interval = GestationalAgeInterval.parse("11+0 to 13+6")
        assert (interval.lower_days, interval.upper_days) == (77, 97)

    def test_parse_en_dash_window(self) -> None:
        assert GestationalAgeInterval.parse("11+0–13+6").upper_days == 97

    def test_parse_weeks_window_maps_to_week_bounds(self) -> None:
        # 18 to 24 weeks → [18+0, 24+0]；是否覆盖 24+0..24+6 由条款级抽取显式给出
        interval = GestationalAgeInterval.parse_weeks("18 to 24 weeks")
        assert (interval.lower_days, interval.upper_days) == (126, 168)
        assert GestationalAgeInterval.parse_weeks("18-24 weeks").upper_days == 168

    def test_contains_point_respects_inclusive_upper(self) -> None:
        interval = GestationalAgeInterval.parse("11+0-14+0")
        assert interval.contains_point(GestationalAge.parse("14+0"))
        open_upper = GestationalAgeInterval(
            interval.lower_days, interval.upper_days, upper_inclusive=False
        )
        assert not open_upper.contains_point(GestationalAge.parse("14+0"))
        assert open_upper.contains_point(GestationalAge.parse("13+6"))

    def test_covers_and_overlaps(self) -> None:
        outer = GestationalAgeInterval.parse("11+0-14+0")
        inner = GestationalAgeInterval.parse("12+0-13+6")
        assert outer.covers(inner)
        assert outer.overlaps(inner)
        assert not inner.covers(outer)
        assert GestationalAgeInterval.parse("15+0-16+0").overlaps(inner) is False

    def test_open_boundary_shrinks_effective_days(self) -> None:
        closed = GestationalAgeInterval(154, 154)
        assert closed.contains_point(GestationalAge(154))
        open_both = GestationalAgeInterval(
            154, 154, lower_inclusive=False, upper_inclusive=False
        )
        assert open_both._effective_bounds() is None
        assert not open_both.contains_point(GestationalAge(154))

    def test_lower_above_upper_rejected(self) -> None:
        with pytest.raises(ValueError):
            GestationalAgeInterval(100, 99)


class TestThreeValuedApplicability:
    def test_covered_query_is_applicable(self) -> None:
        evidence = GestationalAgeInterval.parse("11+0-14+0")
        query = GestationalAgeInterval.parse("12+0-13+6")
        assert apply_ga_interval(evidence, query) is Applicability.APPLICABLE

    def test_disjoint_query_is_inapplicable(self) -> None:
        evidence = GestationalAgeInterval.parse("11+0-14+0")
        query = GestationalAgeInterval.parse("18+0-24+0")
        assert apply_ga_interval(evidence, query) is Applicability.INAPPLICABLE

    def test_cross_boundary_query_stays_unknown(self) -> None:
        # 查询跨越规则边界：不能取中点，不能推断整体适用（主文档 §4.2）
        evidence = GestationalAgeInterval.parse("11+0-14+0")
        query = GestationalAgeInterval.parse("13+0-15+0")
        assert apply_ga_interval(evidence, query) is Applicability.UNKNOWN

    def test_missing_side_is_unknown(self) -> None:
        evidence = GestationalAgeInterval.parse("11+0-14+0")
        assert apply_ga_interval(evidence, None) is Applicability.UNKNOWN
        assert apply_ga_interval(None, evidence) is Applicability.UNKNOWN
        assert apply_ga_interval(None, None) is Applicability.UNKNOWN

    def test_point_query_is_decisive(self) -> None:
        evidence = GestationalAgeInterval.parse("11+0-14+0")
        assert (
            apply_ga_point(evidence, GestationalAge.parse("12+3"))
            is Applicability.APPLICABLE
        )
        assert (
            apply_ga_point(evidence, GestationalAge.parse("15+0"))
            is Applicability.INAPPLICABLE
        )
        assert apply_ga_point(None, GestationalAge.parse("12+3")) is Applicability.UNKNOWN

    def test_point_at_open_upper_boundary(self) -> None:
        evidence = GestationalAgeInterval(77, 98, upper_inclusive=False)
        assert (
            apply_ga_point(evidence, GestationalAge(98)) is Applicability.INAPPLICABLE
        )
        assert (
            apply_ga_point(evidence, GestationalAge(97)) is Applicability.APPLICABLE
        )
