"""生成端版本引用核验测试（答案是否"引了旧版却漏了当前版本"）。"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings, strategies as st

from prenatal_rag.evidence import (
    SupersessionGraph,
    VersionCitationStatus,
    verify_version_citations,
)

_CHAIN = {"a2006": "a2013", "a2013": "a2023"}
_YEARS = {"a2006": 2006, "a2013": 2013, "a2023": 2023}


def _ctx(*source_ids: str) -> list[dict[str, Any]]:
    return [{"source_id": s, "text": f"t{i}"} for i, s in enumerate(source_ids, 1)]


class TestVerifyVersionCitations:
    def test_no_citations(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        report = verify_version_citations("证据不足，无法回答。", _ctx("a2006"), g)
        assert report.status is VersionCitationStatus.NO_CITATIONS
        assert report.cited_sources == ()
        assert report.is_consistent is True  # 未陈旧引用即不算失败

    def test_cites_only_current_version(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        report = verify_version_citations("结论见 [E1]。", _ctx("a2023"), g)
        assert report.status is VersionCitationStatus.CONSISTENT
        assert report.cited_sources == ("a2023",)
        assert report.superseded_cited == ()

    def test_cites_old_and_current_together(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        report = verify_version_citations(
            "2006 版 [E1] 与 2023 版 [E2] 一致。", _ctx("a2006", "a2023"), g
        )
        assert report.status is VersionCitationStatus.CONSISTENT
        assert report.superseded_cited == ("a2006",)
        assert report.current_cited == ("a2023",)
        assert report.missing_current == ()

    def test_stale_only_when_current_available(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        report = verify_version_citations("依据 [E1]。", _ctx("a2006", "a2023"), g)
        assert report.status is VersionCitationStatus.STALE_ONLY
        assert report.missing_current == ("a2023",)
        assert report.unavailable_current == ()
        assert report.is_consistent is False

    def test_current_unavailable_not_blamed(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        report = verify_version_citations("依据 [E1]。", _ctx("a2006"), g)
        assert report.status is VersionCitationStatus.CURRENT_UNAVAILABLE
        assert report.unavailable_current == ("a2023",)
        assert report.missing_current == ()
        assert report.is_consistent is True

    def test_out_of_range_and_duplicate_indices(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        report = verify_version_citations(
            "[E1] 与 [E1] 相同；[E9] 不存在。", _ctx("a2006", "a2023"), g
        )
        assert report.cited_sources == ("a2006",)
        assert report.status is VersionCitationStatus.STALE_ONLY

    def test_zero_and_negative_indices_ignored(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        report = verify_version_citations("[E0] [E-1]", _ctx("a2006"), g)
        assert report.status is VersionCitationStatus.NO_CITATIONS

    def test_blank_or_missing_source_id_skipped(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        report = verify_version_citations(
            "[E1] [E2]",
            [{"source_id": "", "text": "x"}, {"text": "y"}],
            g,
        )
        assert report.cited_sources == ()
        assert report.status is VersionCitationStatus.NO_CITATIONS

    def test_as_of_treats_later_version_as_current(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        # 2016 年时 2013 版才是当前版本 → 引用它不算陈旧。
        report = verify_version_citations(
            "[E2]", _ctx("a2006", "a2013"), g, as_of_year=2016
        )
        assert report.status is VersionCitationStatus.CONSISTENT
        assert report.superseded_cited == ()

    def test_as_of_flags_older_version(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        report = verify_version_citations(
            "[E1]", _ctx("a2006", "a2013"), g, as_of_year=2016
        )
        assert report.status is VersionCitationStatus.STALE_ONLY
        assert report.missing_current == ("a2013",)

    def test_as_of_2024_cites_mid_and_current(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        report = verify_version_citations(
            "[E1] [E3]", _ctx("a2013", "x", "a2023"), g, as_of_year=2024
        )
        assert report.status is VersionCitationStatus.CONSISTENT
        assert report.superseded_cited == ("a2013",)
        assert report.current_cited == ("a2023",)

    def test_multi_hop_missing_records_final_version(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        report = verify_version_citations("[E1]", _ctx("a2006", "a2023"), g)
        # a2006 的当前版本是链尾 a2023，不是中间版 a2013。
        assert report.missing_current == ("a2023",)

    def test_two_stale_sources_deduped(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        report = verify_version_citations(
            "[E1] [E2]", _ctx("a2006", "a2013", "a2023"), g
        )
        assert report.status is VersionCitationStatus.STALE_ONLY
        # a2006 与 a2013 的当前版本同为 a2023 → 去重为一条缺失。
        assert report.missing_current == ("a2023",)


@given(
    cited=st.lists(
        st.integers(min_value=1, max_value=3), min_size=0, max_size=3, unique=True
    )
)
@settings(max_examples=50)
def test_consistent_iff_no_missing(cited: list[int]) -> None:
    g = SupersessionGraph(_CHAIN, years=_YEARS)
    contexts = _ctx("a2006", "a2013", "a2023")
    answer = "".join(f"[E{i}]" for i in cited)
    report = verify_version_citations(answer, contexts, g)
    assert (report.status is VersionCitationStatus.CONSISTENT) == (
        not report.missing_current
        and report.status is not VersionCitationStatus.NO_CITATIONS
    )
