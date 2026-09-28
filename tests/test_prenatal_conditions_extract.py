"""条件抽取单元测试：孕周/人群/技术三轴 + 偏移与确定性（SPEC-conditions Features A–D, H）。

所有示例均为真实语料文本或真实语料模式；hedged/garble/畸形形式必须 fail closed。
API 为行式 ``ChunkCondition``（与 filter/query/evidence_store 消费方一致）：
孕周 ``value`` 是 ``GaWindow.serialize()``，人群/技术 ``value`` 是规范化 token。
"""

import pytest


from pathlib import Path

from prenatal_rag.conditions import (
    ConditionType,
    extract_conditions,
)

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "prenatal_rag"


def conds(text: str, base_offset: int = 0) -> list:
    return extract_conditions(
        text, anchor_id=7, source_id="T", base_offset=base_offset
    )


def ga_values(text: str) -> set[str]:
    return {c.value for c in conds(text) if c.condition_type is ConditionType.GESTATIONAL_AGE}


def pop_values(text: str) -> set[str]:
    return {c.value for c in conds(text) if c.condition_type is ConditionType.POPULATION}


def tech_values(text: str) -> set[str]:
    return {c.value for c in conds(text) if c.condition_type is ConditionType.TECHNIQUE}


def assert_span_slices(text: str, base_offset: int = 0) -> None:
    """P1 不变量：matched_text 必须等于原文对应切片（含连字折叠回映射）。"""
    for c in conds(text, base_offset=base_offset):
        assert text[c.char_start - base_offset : c.char_end - base_offset] == c.matched_text


class TestGAWindows:
    def test_plus_window_with_spaces_and_and(self) -> None:
        text = (
            "first-trimester screening (FTS) by the combined test between "
            "11+0 and 13+6 weeks of pregnancy"
        )
        conds_list = conds(text)
        ga = [c for c in conds_list if c.condition_type is ConditionType.GESTATIONAL_AGE]
        assert len(ga) == 1
        assert ga[0].value == "77:97"
        assert ga[0].pattern_id == "ga_window"
        assert "11+0 and 13+6" in ga[0].matched_text
        assert_span_slices(text)

    def test_plus_window_spaces_around_plus(self) -> None:
        text = (
            "26 + 0 to 28 + 6 weeks: deliver if ductus venosus a-wave is at or "
            "below baseline or STV < 2.6 ms"
        )
        assert ga_values(text) == {"182:202"}

    def test_weeks_window_between_and(self) -> None:
        text = "The cardiac screening examination is performed optimally between 18 and 22 weeks' gestation"
        assert ga_values(text) == {"126:154"}

    def test_weeks_window_dash_range(self) -> None:
        text = "Traditionally, the third-trimester scan has been performed at 32–34 weeks."
        assert ga_values(text) == {"224:238"}

    def test_point_weeks_literal_single_day(self) -> None:
        text = "an ultrasound examination at 16 weeks"
        conds_list = conds(text)
        ga = [c for c in conds_list if c.condition_type is ConditionType.GESTATIONAL_AGE]
        assert len(ga) == 1
        assert ga[0].value == "112:112"
        assert ga[0].pattern_id == "ga_point"

    def test_lower_bound_from_onwards(self) -> None:
        text = "cffDNA has become available for all women as first-tier screening from 10 weeks onwards"
        assert ga_values(text) == {"70:"}

    def test_lower_bound_ge_plus_form(self) -> None:
        text = "≥ 34 + 0 weeks (permitted after 32 + 0 weeks): deliver if UA-EDF is absent"
        assert ga_values(text) == {"238:", "224:"}

    def test_lower_bound_after_is_at_least(self) -> None:
        # GaWindow 无开边界语义："permitted after 30+0" 记为 at_least(210)。
        text = "permitted after 30 + 0 weeks"
        conds_list = conds(text)
        ga = [c for c in conds_list if c.condition_type is ConditionType.GESTATIONAL_AGE]
        assert len(ga) == 1
        assert ga[0].value == "210:"
        assert ga[0].pattern_id == "ga_after"

    def test_lower_bound_as_early_as(self) -> None:
        text = (
            "1.5 T (Figure 2a–c) is the most commonly used field strength, "
            "providing acceptable resolution even as early as 18 gestational weeks"
        )
        assert ga_values(text) == {"126:"}

    def test_upper_bound_before_excludes_boundary_week(self) -> None:
        # "before 14 weeks" = 至多 13+6（第 97 天）：at_most(97)，天集合与互斥表述一致。
        text = "performed before 14 weeks"
        assert ga_values(text) == {":97"}

    def test_upper_bound_up_to_includes_boundary(self) -> None:
        assert ga_values("screening can be performed up to 24 weeks") == {":168"}

    def test_upper_bound_lt_excludes_boundary_week(self) -> None:
        text = "associated with a significant reduction in the rate of PTB < 33 weeks"
        assert ga_values(text) == {":230"}

    def test_plausibility_guard_rejects_non_ga_ranges(self) -> None:
        # 随访间隔等非孕周区间（任一端 <42 天）不得产出 GA 条件。
        assert ga_values("follow-up in 1 to 2 weeks") == set()
        assert ga_values("follow-up scan up to 5 weeks") == set()
        assert ga_values("fetal surveillance in 3 to 8 weeks") == set()

    def test_hedged_around_never_extracted(self) -> None:
        text = "a scan at around 36 weeks is more effective at detecting FGR than is a scan closer to 32 weeks"
        assert ga_values(text) == set()
        assert_span_slices(text)
    def test_ga_window_parse_rejects_malformed(self) -> None:
        from prenatal_rag.conditions import GaWindow
        from prenatal_rag.conditions.schema import GaWindowIsEmptyError

        with pytest.raises(GaWindowIsEmptyError):
            GaWindow.parse("garbage")  # 形状错误
        with pytest.raises(GaWindowIsEmptyError):
            GaWindow.parse("a:b")  # 整数解析错误

    def test_garbled_pdf_tokens_fail_closed(self) -> None:
        assert ga_values("ultrasound at 11 e14 weeks of gestation") == set()
        assert ga_values("examination at ‡32 weeks of gestation") == set()

    def test_malformed_forms_fail_closed(self) -> None:
        assert ga_values("24+7 weeks") == set()
        assert ga_values("22.3 weeks") == set()
    def test_inverted_real_corpus_form_fails_closed(self) -> None:
        # 真实语料伪影（跨栏/断行）："8 and 2 weeks"、"37 and 32 weeks"。
        # 不得崩溃，不得产出 GA 条件（保留 Unknown）。
        assert ga_values("8 and 2 weeks") == set()
        assert ga_values("37 and 32 weeks") == set()
        assert_span_slices("follow-up at 8 and 2 weeks of age")

    def test_multiple_windows_in_one_text(self) -> None:
        text = "first window is 11+0 to 13+6 weeks and the second window is between 18 and 22 weeks"
        assert ga_values(text) == {"77:97", "126:154"}
        assert_span_slices(text)

    def test_serialize_formats(self) -> None:
        cases = [
            ("26 + 0 to 28 + 6 weeks", "182:202"),
            ("from 10 weeks onwards", "70:"),
            ("permitted after 30 + 0 weeks", "210:"),
            ("performed before 14 weeks", ":97"),
            ("up to 24 weeks", ":168"),
            ("at 16 weeks", "112:112"),
        ]
        for text, value in cases:
            assert value in ga_values(text), text
    def test_guard_threshold_boundary_pinned(self) -> None:
        # F-1：窗口任一端落在 [36,42) 天必须被守卫拒绝（42 阈值两侧都钉死）。
        assert ga_values("follow-up 5+6 to 9+0 weeks") == set()  # 下界 41 天
        assert ga_values("follow-up 5+1 to 9+0 weeks") == set()  # 下界 36 天

    def test_compound_malformed_day_fails_closed(self) -> None:
        # F-8/F-11：畸形 "+7" 不得经回溯伪造成 "7 and 26+0 weeks" 窗口。
        assert ga_values("delivery between 24+7 and 26+0 weeks") == set()
    def test_spaced_compound_malformed_fails_closed(self) -> None:
        # R2-F4：空格容忍形态下的畸形 "+ 7" 同样不得经回溯伪造窗口。
        assert ga_values("delivery between 24 + 7 and 26 + 0 weeks") == set()
    def test_lookbehind_unique_inputs_fail_closed(self) -> None:
        # F-R3-5：片段防护的唯一贡献——"+" 前无数字的形态
        # （悬挂加号检查不覆盖此类起点）。
        assert ga_values("+7 and 26+0 weeks") == set()
        assert ga_values("+7 weeks or more") == set()

    def test_ga_window_covers_reflexivity(self) -> None:
        # F-R3-4：covers 自反 + 等下界半有界覆盖（边界等号语义）。
        from prenatal_rag.conditions import GaWindow

        for window in (
            GaWindow.closed(140, 150),
            GaWindow.at_least(140),
            GaWindow.at_most(150),
            GaWindow.closed(0, 300),
            GaWindow(None, None),
        ):
            assert window.covers(window)
        assert GaWindow.at_least(140).covers(GaWindow.closed(140, 168))
        assert GaWindow.at_most(168).covers(GaWindow.closed(140, 168))

    def test_guard_accept_side_pinned(self) -> None:
        # R2-F1：42 天下界（含）必须被接受——守卫接受侧钉死。
        assert ga_values("follow-up 6 to 9 weeks") == {"42:63"}
        assert ga_values("at 6 weeks") == {"42:42"}

    def test_closed_lower_plus_days_counted(self) -> None:
        # R2-F2：双闭窗口下界的 +M 天同样计入（7N+M 全局算术）。
        assert ga_values("between 11+2 and 13+6 weeks") == {"79:97"}

    def test_or_more_lookbehind_pinned(self) -> None:
        # R2-F3：ga_or_more 的片段防护与 ga_window 一致。
        assert ga_values("24+7 weeks or more") == set()
    def test_single_sided_plus_days_counted(self) -> None:
        # F-10：单侧形态同样计入 +M 天（7N+M 全局算术）。
        assert ga_values("permitted after 30 + 1 weeks") == {"211:"}
        assert ga_values("≥ 30 + 1 weeks") == {"211:"}


class TestPopulation:
    def test_chorionicity_discrimination(self) -> None:
        di = pop_values("Complicated dichorionic twins should be scanned more frequently")
        mono = pop_values("Complicated monochorionic twins should be scanned more frequently")
        assert di == {"dichorionic", "twin"}
        assert mono == {"monochorionic", "twin"}

    def test_singleton(self) -> None:
        assert "singleton" in pop_values("the risk is lower in singleton pregnancies")

    def test_previous_ptb_qualifier(self) -> None:
        assert "previous_ptb" in pop_values(
            "cerclage placement at 12–14 weeks for women with previous PTB"
        )

    def test_unselected_twin(self) -> None:
        values = pop_values(
            "History-indicated cerclage is not recommended in unselected twin pregnancy"
        )
        assert {"unselected", "twin"} <= values

    def test_utd_subgroups(self) -> None:
        assert "utd_a1" in pop_values("for fetuses with isolated UTD A1")
        assert "utd_a2_3" in pop_values("For fetuses with UTD A2-3")

    def test_nipt_chance_qualifiers(self) -> None:
        assert "high_chance" in pop_values("Individuals with a high chance result")
        assert "low_chance" in pop_values(
            "Post-test counseling for those with low chance results"
        )

    def test_clean_text_extracts_no_population(self) -> None:
        assert pop_values("The scan should be documented and communicated.") == set()


class TestFilterSemantics:
    """B1 三值分类与查询解析的边界语义（verifier F-4/F-6/F-7）。"""

    def test_chorionicity_opposites_inapplicable(self) -> None:
        from prenatal_rag.applicability import Applicability
        from prenatal_rag.conditions import QueryConditions, classify

        chunk_di = extract_conditions("Complicated dichorionic twins should be scanned more frequently")
        chunk_mono = extract_conditions("Complicated monochorionic twins should be scanned more frequently")
        query_mono = QueryConditions(population=frozenset({"monochorionic"}))
        query_di = QueryConditions(population=frozenset({"dichorionic"}))
        assert classify(chunk_di, query_mono) is Applicability.INAPPLICABLE
        assert classify(chunk_mono, query_di) is Applicability.INAPPLICABLE

    def test_classify_any_applicable_beats_unknown(self) -> None:
        from prenatal_rag.applicability import Applicability
        from prenatal_rag.conditions import GaWindow, QueryConditions, classify

        # 一个 chunk 含两个窗口：任一覆盖查询即 Applicable（不是 Unknown）。
        text = "guideline for 18 to 24 weeks and cardiac screening at 20 to 24 weeks of gestation"
        conds = extract_conditions(text)
        query = QueryConditions(gestational_age=GaWindow.closed(130, 150))
        assert classify(conds, query) is Applicability.APPLICABLE

    def test_query_no_leaky_fallback(self) -> None:
        from prenatal_rag.conditions import parse_query_conditions

        # R2-F5：查询侧回退已删除——无 "at" 锚定的裸周数、hedged、畸形、
        # 亚 viability 区间在查询侧一律不得伪造孕周点（fail closed）。
        for text in (
            "13 weeks' gestation follow-up",
            "24+7 weeks",
            "a scan at around 36 weeks is more effective at detecting FGR",
            "follow-up in 1 to 2 weeks",
        ):
            assert parse_query_conditions(text).gestational_age is None, text

    def test_query_first_window_precedence(self) -> None:
        from prenatal_rag.conditions import parse_query_conditions

        # 多窗口查询取第一个窗口（窗口优先，且窗口内序按文本顺序）。
        two = parse_query_conditions(
            "between 18 and 22 weeks screening, before 14 weeks historic scan"
        )
        assert two.gestational_age is not None
        assert two.gestational_age.serialize() == "126:154"


class TestTechnique:
    def test_cfdna_screen(self) -> None:
        text = "and a negative cell-free DNA screen, we recommend describing the finding"
        assert tech_values(text) == {"cfdna_screen"}

    def test_ligature_first_or_second_trimester_screening(self) -> None:
        text = "and a negative ﬁrst- or second-trimester screening result, we recom-mend"
        values = tech_values(text)
        assert values == {"first_or_second_trimester_screening"}
        assert_span_slices(text)

    def test_mr_field_strength(self) -> None:
        assert tech_values("1.5 T (Figure 2a–c) is the most commonly used field strength") == {
            "field_1.5t"
        }
        assert tech_values(
            "3 T has the potential to achieve higher-resolution images than does 1.5 T"
        ) == {"field_3t", "field_1.5t"}

    def test_doppler_parameters(self) -> None:
        text = "Deliver if DV a-wave at or below baseline or STV < 2.6 ms"
        assert tech_values(text) == {"dv", "stv"}

    def test_ductus_venosus_spelled_out(self) -> None:
        assert tech_values("deliver if ductus venosus a-wave is at or below baseline") == {"dv"}

    def test_harmonic_imaging(self) -> None:
        assert tech_values("Tissue harmonic imaging provides improved images") == {
            "harmonic_imaging"
        }

    def test_nipt_acronym(self) -> None:
        assert tech_values("NIPT does not exclude all genetic conditions") == {"nipt"}

    def test_acquisition_route_tokens(self) -> None:
        assert tech_values("a transvaginal scan at the transabdominal threshold") == {
            "transvaginal",
            "transabdominal",
        }

    def test_clean_text_extracts_no_technique(self) -> None:
        text = "T2-weighted contrast is the mainstay of fetal magnetic resonance imaging (MRI)."
        assert tech_values(text) == set()


class TestAggregateBehavior:
    def test_base_offset_is_absolute(self) -> None:
        text = "scan 11+0 to 13+6 weeks"
        conds_list = conds(text, base_offset=100)
        ga = [c for c in conds_list if c.condition_type is ConditionType.GESTATIONAL_AGE]
        assert ga[0].anchor_id == 7
        assert ga[0].source_id == "T"
        assert ga[0].char_start == 100 + 5
        assert text[ga[0].char_start - 100 : ga[0].char_end - 100] == ga[0].matched_text

    def test_deterministic(self) -> None:
        text = "Complicated monochorionic twins: deliver if DV a-wave is at or below baseline at 26 + 0 to 28 + 6 weeks"
        assert conds(text) == conds(text)

    def test_empty_text(self) -> None:
        assert conds("") == []

    def test_output_sorted_deterministically(self) -> None:
        text = "monochorionic twins screening 11+0 to 13+6 weeks with DV Doppler"
        conditions = conds(text)
        keys = [(c.condition_type.value, c.char_start, c.pattern_id) for c in conditions]
        assert keys == sorted(keys)

    def test_all_spans_slice_to_matched_text(self) -> None:
        text = (
            "Complicated monochorionic twins: deliver if DV a-wave is at or below "
            "baseline at 26 + 0 to 28 + 6 weeks, permitted after 30 + 0 weeks"
        )
        assert_span_slices(text)


class TestPackageIndependence:
    def test_no_benchmark_imports(self) -> None:
        for path in sorted(PACKAGE_DIR.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            assert "import benchmark" not in source, path
            assert "from benchmark" not in source, path

    def test_no_network_or_llm_imports_in_conditions(self) -> None:
        forbidden = ("urllib", "requests", "httpx", "socket", "openai", "anthropic")
        for path in sorted((PACKAGE_DIR / "conditions").rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for name in forbidden:
                assert f"import {name}" not in source, path
                assert f"from {name}" not in source, path
