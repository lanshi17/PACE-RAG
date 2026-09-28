"""chunk 级条件抽取与三值过滤（prenatal_rag.conditions）测试。

覆盖抽规则边形（含 15 组条件变体的窗口形态）、GaWindow 往返、三值分类
与 B1 显式过滤，以及证据存储的条件持久化接口。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from prenatal_rag.applicability import Applicability
from prenatal_rag.conditions import (
    ChunkCondition,
    ConditionExtractor,
    ConditionType,
    GaWindow,
    QueryConditions,
    classify,
    classify_text,
    describe,
    extract_conditions,
    filter_chunks,
    parse_query_conditions,
)
from prenatal_rag.conditions.extract import _build_closed
from prenatal_rag.evidence_store import EvidenceStore


def _conds(text: str) -> list[ChunkCondition]:
    return extract_conditions(text, anchor_id=0, source_id="T", base_offset=0)


def _ga(text: str) -> list[ChunkCondition]:
    return [c for c in _conds(text) if c.condition_type == ConditionType.GESTATIONAL_AGE]


class TestGaWindow:
    def test_serialize_roundtrip_closed(self) -> None:
        w = GaWindow.closed(182, 202)
        assert GaWindow.parse(w.serialize()) == w

    def test_serialize_roundtrip_half_bounded(self) -> None:
        assert GaWindow.parse(GaWindow.at_least(238).serialize()) == GaWindow.at_least(238)
        assert GaWindow.parse(GaWindow.at_most(168).serialize()) == GaWindow.at_most(168)

    def test_bad_bounds_rejected(self) -> None:
        with pytest.raises(ValueError):
            GaWindow.closed(202, 182)

    def test_negative_days_rejected(self) -> None:
        with pytest.raises(ValueError):
            GaWindow(lower_days=-5, upper_days=None)

    def test_str_renders_each_bound_shape(self) -> None:
        assert GaWindow.closed(182, 202).__str__() == "[182, 202]天"
        assert "238" in GaWindow.at_least(238).__str__()
        assert "168" in GaWindow.at_most(168).__str__()
        assert GaWindow(None, None).__str__() == "(-∞, ∞)天"

    def test_condition_type_str_is_value(self) -> None:
        assert str(ConditionType.GESTATIONAL_AGE) == "gestational_age"

    def test_overlaps_covers_half_bounded(self) -> None:
        ge34 = GaWindow.at_least(238)  # ≥34 周
        # 40 周 vs ≥34：evidence=query 阈值以上
        assert ge34.overlaps(GaWindow.closed(280, 280))
        assert not ge34.overlaps(GaWindow.closed(210, 220))
        assert GaWindow.closed(238, 287).covers(GaWindow.closed(240, 250))
        assert not ge34.covers(GaWindow.closed(230, 250))  # 下界越过


class TestExtractionGA:
    # 15 组条件变体的窗口形态（验收样例节选）
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("delivery criteria 26+0 to 28+6 weeks", GaWindow.closed(182, 202)),
            ("delivery criteria 26 to 28+6 weeks", GaWindow.closed(182, 202)),
            ("delivery criteria 29+0 to 31+6 weeks", GaWindow.closed(203, 223)),
            ("delivery criteria 32-33+6 weeks", GaWindow.closed(224, 237)),
            ("delivery criteria at 34 weeks or more", GaWindow.at_least(238)),
            ("delivery criteria at least 34 weeks", GaWindow.at_least(238)),
            ("history-indicated cerclage at 12-14 weeks", GaWindow.closed(84, 98)),
            ("screening at 11+0 to 13+6 weeks", GaWindow.closed(77, 97)),
            ("mid-pregnancy scan at 18 to 24 weeks", GaWindow.closed(126, 168)),
        ],
    )
    def test_extracts_window(self, text: str, expected: GaWindow) -> None:
        got = _ga(text)
        assert len(got) == 1, got
        assert GaWindow.parse(got[0].value) == expected
        assert got[0].matched_text.lower() in text.lower()

    def test_at_most_plausible_window(self) -> None:
        # 上界条款（up to N weeks）命中 at_most（覆盖 _at_most builder）
        w = GaWindow.parse(_ga("follow-up scan up to 24 weeks")[0].value)
        assert w == GaWindow.at_most(168)

    def test_at_most_implausible_upper_guard(self) -> None:
        # up to 5 weeks：上界 <42，被合理性守卫剔除（覆盖 upper<42 分支）
        assert _ga("follow-up scan up to 5 weeks") == []

    def test_lower_guard_rejects_early_start(self) -> None:
        # "3 to 8 weeks"：下界 21 天 <42（上界 56 ≥42，上界守卫放行）
        # —— 只有下界守卫能拒绝这类早期起点的非孕周间隔（独立于 upper 分支）
        assert _ga("fetal surveillance in 3 to 8 weeks") == []

    def test_anchor_offsets_absolute(self) -> None:
        # base_offset=100 时 char 偏移为绝对偏移
        conds = extract_conditions(
            "scan 11+0 to 13+6 weeks",
            anchor_id=7,
            source_id="S",
            base_offset=100,
        )
        ga = [c for c in conds if c.condition_type == ConditionType.GESTATIONAL_AGE][0]
        assert ga.anchor_id == 7 and ga.source_id == "S"
        # "scan 11+0 to 13+6 weeks" 中 "11" 起始下标 = len("scan ") = 5
        assert ga.char_start == 100 + 5

    def test_plain_text_no_window(self) -> None:
        assert _ga("the fetal cardiac screening text here") == []


class TestExtractionToken:
    def test_population(self) -> None:
        vals = {c.value for c in _conds("monochorionic twins") if c.condition_type == ConditionType.POPULATION}
        assert {"monochorionic", "twin"} <= vals

    def test_technique(self) -> None:
        vals = {c.value for c in _conds("1.5 T four-chamber view cfDNA") if c.condition_type == ConditionType.TECHNIQUE}
        assert {"field_1.5t", "four_chamber", "cfdna_screen"} <= vals


class TestClassify:
    def test_ga_applicable(self) -> None:
        c = _conds("guideline for 18 to 24 weeks")
        q = QueryConditions(gestational_age=GaWindow.closed(140, 140))  # 20+0
        assert classify(c, q) is Applicability.APPLICABLE

    def test_ga_inapplicable(self) -> None:
        c = _conds("screening 11+0 to 13+6 weeks")
        q = QueryConditions(gestational_age=GaWindow.closed(140, 140))
        assert classify(c, q) is Applicability.INAPPLICABLE

    def test_ga_span_crossing_boundary_unknown(self) -> None:
        c = _conds("guideline for 18 to 24 weeks")
        q = QueryConditions(gestational_age=GaWindow.closed(130, 180))
        assert classify(c, q) is Applicability.UNKNOWN

    def test_ga_missing_unknown(self) -> None:
        q = QueryConditions(gestational_age=GaWindow.closed(140, 140))
        assert classify(_conds("plain phrase"), q) is Applicability.UNKNOWN

    def test_population_missing_unknown(self) -> None:
        # 查询限人群而 chunk 无任何人群 token → 无条件数据，保留 Unknown
        q = QueryConditions(population=frozenset({"twin"}))
        assert classify(_conds("scan at 18 to 24 weeks"), q) is Applicability.UNKNOWN

    def test_technique_no_match_no_opposite_unknown(self) -> None:
        # 查询限技术；chunk 有技术 token 但不命中、也无正对 → Unknown（不误删）
        q = QueryConditions(technique=frozenset({"cfdna_screen"}))
        assert (
            classify(_conds("transvaginal four-chamber view"), q)
            is Applicability.UNKNOWN
        )

    def test_population_opposite_inapplicable(self) -> None:
        c = _conds("monochorionic twins")
        q = QueryConditions(population=frozenset({"singleton"}))
        assert classify(c, q) is Applicability.INAPPLICABLE

    def test_population_match_applicable(self) -> None:
        c = _conds("monochorionic twins")
        q = QueryConditions(population=frozenset({"twin"}))
        assert classify(c, q) is Applicability.APPLICABLE

    def test_unconstrained_applicable(self) -> None:
        assert classify(_conds("plain"), QueryConditions()) is Applicability.APPLICABLE

    def test_mixed_ga_population(self) -> None:
        # 孕周不适用 + 人群不适用 → Inapplicable（任一 Inapplicable 合并后剔除）
        c = _conds("monochorionic twins screening 11+0 to 13+6 weeks")
        q = QueryConditions(
            gestational_age=GaWindow.closed(140, 140),
            population=frozenset({"singleton"}),
        )
        assert classify(c, q) is Applicability.INAPPLICABLE


class TestFilterChunks:
    def test_drops_only_inapplicable(self) -> None:
        indexed = [
            (1, "a", _conds("guideline for 18 to 24 weeks")),
            (2, "b", _conds("screening 11+0 to 13+6 weeks")),
            (3, "c", _conds("plain phrase without conditions")),
        ]
        q = QueryConditions(gestational_age=GaWindow.closed(140, 140))
        kept, dropped = filter_chunks(indexed, q)
        assert sorted(k[1] for k in kept) == ["a", "c"]  # Unknown(0条)保留
        assert [k[1] for k in dropped] == ["b"]


_OVERLAP_WIDE_RE = re.compile(
    r"\b(?P<a>20) to (?P<b>24) weeks in pregnancy\b", re.IGNORECASE
)
_OVERLAP_NARROW_RE = re.compile(r"\b(?P<a>20) to (?P<b>24) weeks\b", re.IGNORECASE)


class _WideFirstExtractor(ConditionExtractor):
    _GA_SPECS = [
        ("ga_wide", _OVERLAP_WIDE_RE, _build_closed),
        ("ga_narrow", _OVERLAP_NARROW_RE, _build_closed),
    ]


class _NarrowFirstExtractor(ConditionExtractor):
    _GA_SPECS = [
        ("ga_narrow", _OVERLAP_NARROW_RE, _build_closed),
        ("ga_wide", _OVERLAP_WIDE_RE, _build_closed),
    ]


class TestGaOverlapDedup:
    """GA 防重：新 span 被已接受 span 包含→跳过；包含旧 span→替换（长/具体者胜）。"""

    def test_narrow_contained_skipped(self) -> None:
        conds = _WideFirstExtractor().extract(
            "scan 20 to 24 weeks in pregnancy",
            anchor_id=1,
            source_id="S",
            base_offset=0,
        )
        ga = [c for c in conds if c.condition_type is ConditionType.GESTATIONAL_AGE]
        assert len(ga) == 1  # 宽匹配已在先，窄被包含→跳过（不重复记账）
        assert ga[0].pattern_id == "ga_wide"

    def test_wide_containing_replace(self) -> None:
        conds = _NarrowFirstExtractor().extract(
            "scan 20 to 24 weeks in pregnancy",
            anchor_id=1,
            source_id="S",
            base_offset=0,
        )
        ga = [c for c in conds if c.condition_type is ConditionType.GESTATIONAL_AGE]
        assert len(ga) == 1  # 窄已在先，宽替换之，长者胜
        assert ga[0].pattern_id == "ga_wide"
        assert ga[0].matched_text.lower() == "20 to 24 weeks in pregnancy"


class TestStoreConditions:
    def test_rewrite_and_read(self, tmp_path: Path) -> None:
        store = EvidenceStore(tmp_path / "es")
        try:
            store.ingest_document(
                "Doc",
                "## Page 1\n\nscan 11+0 to 13+6 weeks for monochorionic twins.",
                family_id="fam",
            )
            chunk = next(store.iter_chunks())
            conds = extract_conditions(
                chunk.text,
                anchor_id=chunk.anchor_id,
                source_id=chunk.source_id,
                base_offset=chunk.char_start,
            )
            assert conds, "应抽到至少一条条件"
            store.rewrite_chunk_conditions(chunk.anchor_id, conds)
            stored = store.conditions_for(chunk.anchor_id)
            assert len(stored) == len(conds)
            assert stored[0].source_id == "Doc"

            # 幂等：整份替换后数量一致
            store.build_condition_index()
            assert len(store.conditions_for(chunk.anchor_id)) == len(stored)
            assert all(c.source_id == "Doc" for c in store.iter_conditions())
        finally:
            store.close()


class TestQueryConditionsParse:
    def test_ga_point_at_weeks(self) -> None:
        q = parse_query_conditions("At 13 weeks' gestation, NT = 3.8 mm")
        assert q.gestational_age is not None
        assert q.gestational_age.serialize() == "91:91"

    def test_ga_window_wins_over_point(self) -> None:
        q = parse_query_conditions("screening at 11+0 to 13+6 weeks")
        assert q.gestational_age.serialize() == "77:97"

    def test_population_derived(self) -> None:
        q = parse_query_conditions("surveillance in monochorionic twins")
        assert "twin" in q.population and "monochorionic" in q.population

    def test_generic_no_condition(self) -> None:
        q = parse_query_conditions("Which structures should be assessed?")
        assert q.gestational_age is None and not q.population and not q.technique

    def test_technique_conservative(self) -> None:
        # "four-chamber view" 是答案主题，不作为查询技术约束；
        # "cfDNA" 是强约束技术标记，应进入查询条件。
        q_subject = parse_query_conditions("Which structures in four-chamber view?")
        assert "four_chamber" not in q_subject.technique
        q_cfdna = parse_query_conditions("after a negative cfDNA screen")
        assert "cfdna_screen" in q_cfdna.technique

    def test_describe(self) -> None:
        from prenatal_rag.conditions.schema import GaWindow as _GW

        assert "GA" in describe(QueryConditions(gestational_age=_GW.closed(140, 140)))
        assert "人群" in describe(QueryConditions(population=frozenset({"twin"})))
        assert "技术" in describe(QueryConditions(technique=frozenset({"cfdna_screen"})))
        assert "无条件" in describe(QueryConditions())

    def test_query_takes_first_window(self) -> None:
        # 同题同时段出现单点(20w)与晚孕窗口(26+0-28+6)：取首个窗口。
        q = parse_query_conditions(
            "At 20 weeks, delivery is considered at 26+0 to 28+6 weeks"
        )
        assert q.gestational_age.serialize() == "140:140"


class TestClassifyText:
    def test_applicable_and_inapplicable(self) -> None:
        q = QueryConditions(gestational_age=GaWindow.closed(140, 140))  # 20+0
        assert classify_text("scan at 18 to 24 weeks", q) is Applicability.APPLICABLE
        assert (
            classify_text("NT measured at 11+0 to 13+6 weeks", q)
            is Applicability.INAPPLICABLE
        )

    def test_unknown_when_no_condition(self) -> None:
        q = QueryConditions(gestational_age=GaWindow.closed(140, 140))
        assert classify_text("plain observation text", q) is Applicability.UNKNOWN


class TestIndexConditionsHelper:
    def test_writes_via_decoupled_helper(self, tmp_path: Path) -> None:
        from prenatal_rag.conditions.extract import index_conditions

        store = EvidenceStore(tmp_path / "es")
        try:
            store.ingest_document(
                "D",
                "## Page 1\n\nscan at 18 to 24 weeks in twins.",
                family_id="f",
            )
            chunk = next(store.iter_chunks())
            # base_offsets：anchor_id → 规范化文本内绝对偏移
            n = index_conditions(
                [(chunk.anchor_id, chunk.source_id, chunk.text)],
                store=store,
                base_offsets={chunk.anchor_id: chunk.char_start},
            )
            assert n >= 2
            stored = store.conditions_for(chunk.anchor_id)
            assert any(
                c.condition_type is ConditionType.GESTATIONAL_AGE for c in stored
            )
            assert stored[0].char_start >= chunk.char_start
        finally:
            store.close()


# ── property 不变量（hypothesis；N5/N4/W 契约）──────────────────────────────
_gw_pair = st.tuples(st.integers(0, 320), st.integers(0, 320)).filter(
    lambda ab: ab[0] <= ab[1]
)


class TestGaWindowProperties:
    @given(_gw_pair)
    def test_closed_roundtrip(self, ab: tuple[int, int]) -> None:
        a, b = ab
        assert GaWindow.parse(GaWindow.closed(a, b).serialize()) == GaWindow.closed(
            a, b
        )

    @given(st.integers(0, 315))
    def test_half_bounded_roundtrip(self, d: int) -> None:
        assert GaWindow.parse(GaWindow.at_least(d).serialize()) == GaWindow.at_least(d)
        assert GaWindow.parse(GaWindow.at_most(d).serialize()) == GaWindow.at_most(d)

    @given(st.integers(0, 400), st.integers(0, 400), st.integers(0, 400))
    def test_covers_implies_overlaps(self, a: int, b: int, q: int) -> None:
        assume(a <= b)
        # 非退化证据窗口（at_least/at_most 均非空集合）
        evidence = GaWindow.closed(a, b)
        for query in (
            GaWindow.closed(q, q),
            GaWindow.at_least(q),
            GaWindow.at_most(q),
        ):
            if evidence.covers(query):
                assert evidence.overlaps(query), (
                    f"covers 应蕴含 overlaps: evidence={evidence} query={query}"
                )

    @given(st.integers(1, 45))
    def test_at_least_no_overlap_below(self, weeks: int) -> None:
        ge = GaWindow.at_least(weeks * 7)
        below = GaWindow.closed(0, weeks * 7 - 1)
        assert not ge.overlaps(below)


def _token_strategy() -> st.SearchStrategy[str]:
    return st.one_of(
        st.just("11+0 to 13+6 weeks"),
        st.just("18 to 24 weeks"),
        st.just("32-33+6 weeks"),
        st.just("monochorionic twins"),
        st.just("1.5 T four-chamber view"),
        st.just("screen 26+0 to 28+6 weeks in dichorionic"),
        st.sampled_from(["NT", "cfDNA", "sagittal plane", "10-14 weeks"]),
    )


class TestExtractorProperties:
    @given(st.lists(st.text(min_size=1, max_size=12), min_size=1, max_size=8))
    def test_deterministic(self, parts: list[str]) -> None:
        text = " ".join(parts)
        first = extract_conditions(text, anchor_id=1, source_id="S", base_offset=5)
        second = extract_conditions(text, anchor_id=1, source_id="S", base_offset=5)
        assert first == second  # 确定性：重复抽取逐字节相同（N5）

    @given(st.lists(_token_strategy(), min_size=1, max_size=10))
    def test_plausible_guard_and_span(self, tokens: list[str]) -> None:
        text = " ".join(tokens)
        off = 100
        for c in extract_conditions(text, anchor_id=3, source_id="S", base_offset=off):
            assert c.char_start >= off
            assert text[c.char_start - off : c.char_end - off] == c.matched_text  # span 可还原
            if c.condition_type is ConditionType.GESTATIONAL_AGE:
                w = GaWindow.parse(c.value)
                assert (w.lower_days is None or w.lower_days >= 42) and (
                    w.upper_days is None or w.upper_days >= 42
                )
        # "1 to 2 weeks" 随访间隔绝不应产出 GA 条件（G7）
        assert not [
            c
            for c in extract_conditions(
                "follow-up in 1 to 2 weeks",
                anchor_id=3,
                source_id="S",
                base_offset=0,
            )
            if c.condition_type is ConditionType.GESTATIONAL_AGE
        ]