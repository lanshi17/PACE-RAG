"""15 组条件变体验收：真实引文逐字嵌入（SPEC-conditions Feature E）。

引文取自 benchmark/results/corpus-audit-20260912/density_statements_raw.json
（2026-09-15 逐组核对）。预期值依据引文本身可支持的抽取结果：
- 变体组：成员在引文可表达的轴上必须两两区分；
- 近重复组（6/7/9/12 及组 1 的 q1≡q3）：条件值集必须相等（反幻觉对照）——
  审计标注与引文不符处以引文为准，抽取器不得为对齐噪声标签而编造条件。

API 为行式 ``ChunkCondition``；``sig`` 以 (条件类型, value) 集合为粒度
（与 B1 过滤的判别粒度一致，不含偏移）。
"""

from __future__ import annotations

import pytest

from prenatal_rag.conditions import ConditionType, extract_conditions

# ── 真实引文（逐字，含 PDF 连字与乱码，禁止"修复"引文） ─────────────────────

G1_Q1 = "Deliver if DV a-wave at or below baseline or STV < 2.6 ms"
G1_Q2 = (
    "26 + 0 to 28 + 6 weeks: deliver if ductus venosus a-wave is at or below "
    "baseline or STV < 2.6 ms"
)
G1_Q3 = "Deliver if DV a-wave at or below baseline or STV < 3.0 ms"

G2_A = "The cardiac screening examination is performed optimally between 18 and 22 weeks’ gestation"
G2_B = "The fetal cardiac examination is optimally performed between 18 and 22 weeks' menstrual age."
G2_C = (
    "Screening at 20–22 weeks' gestation is less likely to require an additional "
    "scan for completion of this evaluation"
)

G3_A = (
    "a scan at around 36 weeks is more effective at detecting FGR than is a scan "
    "closer to 32 weeks"
)
G3_B = (
    "The timing of the third-trimester scan, if indicated, between 32 and 36 weeks, "
    "should be decided based on individual maternal and fetal characteristics"
)
G3_C = (
    "Traditionally, the third-trimester scan has been performed at 32–34 weeks. "
    "The anatomical examination may be technically easier at this stage"
)

G4_A = (
    "and a negative cell-free DNA screen, we recommend describing the ﬁnding as "
    "not clinically signi ﬁcant or as a normal variant (GRADE 2B)"
)
G4_B = (
    "and a negative ﬁrst- or second-trimester screening result, we recom-mend "
    "describing the ﬁnding as not clinically signi ﬁcant or as a normal variant (GRADE 2B)"
)

G5_A = (
    "32 + 0 to 33 + 6 weeks (permitted after 30 + 0 weeks): deliver if UA-EDF is "
    "reversed or STV < 3.5 ms"
)
G5_B = (
    "≥ 34 + 0 weeks (permitted after 32 + 0 weeks): deliver if UA-EDF is absent "
    "or STV < 4.5 ms"
)

G6_A = (
    "Note gestational age, ideally as assessed by ﬁrst-trimester ultrasound 23, "
    "and pertinent prior clinical assessment and ultrasound ﬁndings."
)
G6_B = (
    "Note the gestational age, ideally as assessed by first-trimester ultrasound, "
    "and pertinent prior clinical assessment and ultrasound findings"
)

G7_A = (
    "Some anomalies may be identified during the late first and early second "
    "trimesters of pregnancy, especially when increased nuchal translucency "
    "thickness is identified"
)
G7_B = (
    "Some anomalies may be identiﬁed during the late ﬁrst and early second "
    "trimesters of pregnancy, especially when increased nuchal translucency is identified"
)

G8_A = (
    "for fetuses with isolated UTD A1, we recommend an ultrasound examination at "
    "‡32 weeks of gestation to determine if postnatal pediatric urology or "
    "nephrology follow-up is needed"
)
G8_B = (
    "For fetuses with UTD A2-3, we recommend an individualized follow-up "
    "ultrasound assessment with planned postnatal follow-up (GRADE 1C)."
)

G9_A = (
    "Harmonic imaging may provide improved images especially for patients with "
    "increased maternal abdominal wall thickness during the third trimester of "
    "pregnancy."
)
G9_B = (
    "Tissue harmonic imaging provides improved images, especially for patients "
    "with increased abdominal wall thickness and during the third trimester of "
    "pregnancy"
)

G10_A = (
    "History-indicated (or prophylactic) cerclage placement at 12–14 weeks for "
    "women with previous PTB suggestive of cervical insufficiency was associated "
    "with a significant reduction in the rate of PTB < 33 weeks"
)
G10_B = (
    "History-indicated cerclage is not recommended in unselected twin pregnancy "
    "(GRADE OF RECOMMENDATION: C)."
)

G11_A = "Complicated dichorionic twins should be scanned more frequently, depending on the condition and its severity"
G11_B = "Complicated monochorionic twins should be scanned more frequently, depending on the condition and its severity"

G12_A = (
    "in women who have already received a negative cell-free DNA screening result, "
    "ultrasound at 11 e14 weeks of gestation solely for the purpose of nuchal "
    "translucency measurement (Current Procedural Terminol-ogy code 76813) is not "
    "recommended (GRADE 1B)"
)
G12_B = (
    "In women who have already received a negative cfDNA screen, ultrasound at "
    "11 e14 weeks of gestation solely for the purpose of NT measurement (CPT code "
    "76813) is not recommended (GRADE 1B)"
)

G13_A = (
    "Individuals with a high chance result should also be informed that FPR may "
    "occur, and that diagnostic testing is recommended prior to management decisions"
)
G13_B = (
    "Post-test counseling for those with low chance results should include a "
    "caveat that NIPT does not exclude all genetic conditions and that "
    "false-negative results may occur."
)

G14_A = (
    "Some fetal abnormalities will not be detected at the routine second-trimester "
    "anatomy scan, even with the best equipment in the most expert of hands."
)
G14_B = "no information on the second-trimester anomaly scan (18+0 to 22+6 weeks) was available"

G15_A = (
    "1.5 T (Figure 2a–c) is the most commonly used field strength, providing "
    "acceptable resolution even as early as 18 gestational weeks"
)
G15_B = (
    "3 T has the potential to achieve higher-resolution images with a better "
    "signal-to-noise ratio than does 1.5 T at a comparable rate of energy "
    "deposition on tissue"
)

NEG_CONTROL_1 = (
    "Anomalies were diagnosed prenatally in 200 (1.8%) fetuses; 81 (0.7%) were "
    "chromosomal and 119 (1.1%) were structural."
)
NEG_CONTROL_2 = (
    "T2-weighted contrast is the mainstay of fetal magnetic resonance imaging (MRI)."
)
NEG_CONTROL_3 = (
    "At any gestational age: presence of maternal indication (e.g. severe "
    "pre-eclampsia, HELLP syndrome) or obstetric emergency requiring delivery"
)


def sig(text: str) -> frozenset[tuple[str, str]]:
    """条件值签名：(条件类型, value) 集合；不含偏移（B1 判别粒度）。"""
    return frozenset(
        (c.condition_type.value, c.value) for c in extract_conditions(text)
    )


def ga_values(text: str) -> set[str]:
    return {c.value for c in extract_conditions(text) if c.condition_type is ConditionType.GESTATIONAL_AGE}


def pop_values(text: str) -> set[str]:
    return {c.value for c in extract_conditions(text) if c.condition_type is ConditionType.POPULATION}


def tech_values(text: str) -> set[str]:
    return {c.value for c in extract_conditions(text) if c.condition_type is ConditionType.TECHNIQUE}


def assert_p1(text: str) -> None:
    for c in extract_conditions(text):
        assert text[c.char_start : c.char_end] == c.matched_text


ALL_QUOTES = [G1_Q1, G1_Q2, G1_Q3, G2_A, G2_B, G2_C, G3_A, G3_B, G3_C, G4_A, G4_B,
              G5_A, G5_B, G6_A, G6_B, G7_A, G7_B, G8_A, G8_B, G9_A, G9_B, G10_A,
              G10_B, G11_A, G11_B, G12_A, G12_B, G13_A, G13_B, G14_A, G14_B,
              G15_A, G15_B, NEG_CONTROL_1, NEG_CONTROL_2, NEG_CONTROL_3]


class TestVariantGroups:
    def test_group1_ga_in_metadata_not_quote(self) -> None:
        assert ga_values(G1_Q1) == set()
        assert ga_values(G1_Q3) == set()
        assert sig(G1_Q1) == sig(G1_Q3) == frozenset({("technique", "dv"), ("technique", "stv")})
        assert sig(G1_Q2) == frozenset(
            {("gestational_age", "182:202"), ("technique", "dv"), ("technique", "stv")}
        )

    def test_group2_cardiac_timing(self) -> None:
        assert ga_values(G2_A) == ga_values(G2_B) == {"126:154"}
        assert ga_values(G2_C) == {"140:154"}
        assert sig(G2_A) != sig(G2_C)

    def test_group3_third_trimester_timing(self) -> None:
        assert ga_values(G3_A) == set()  # hedged fail closed
        assert ga_values(G3_B) == {"224:252"}
        assert ga_values(G3_C) == {"224:238"}

    def test_group4_screening_modality(self) -> None:
        assert tech_values(G4_A) == {"cfdna_screen"}
        assert tech_values(G4_B) == {"first_or_second_trimester_screening"}

    def test_group5_reversed_ua_edf(self) -> None:
        assert ga_values(G5_A) == {"224:237", "210:"}
        assert ga_values(G5_B) == {"238:", "224:"}
        assert tech_values(G5_A) == tech_values(G5_B) == {"ua_edf", "stv"}

    def test_group6_near_duplicate_control(self) -> None:
        assert sig(G6_A) == sig(G6_B) == frozenset()

    def test_group7_near_duplicate_control(self) -> None:
        assert sig(G7_A) == sig(G7_B) == frozenset(
            {("technique", "nt"), ("population", "increased_nt")}
        )

    def test_group8_utd_subgroups_garble_fail_closed(self) -> None:
        assert pop_values(G8_A) == {"utd_a1"}
        assert pop_values(G8_B) == {"utd_a2_3"}
        assert ga_values(G8_A) == set()  # ‡32 乱码 fail closed
        assert sig(G8_A) != sig(G8_B)

    def test_group9_near_duplicate_control(self) -> None:
        assert sig(G9_A) == sig(G9_B) == frozenset({("technique", "harmonic_imaging")})

    def test_group10_cerclage(self) -> None:
        assert ga_values(G10_A) == {"84:98", ":230"}
        assert pop_values(G10_A) == {"previous_ptb"}
        assert pop_values(G10_B) == {"unselected", "twin"}

    def test_group11_chorionicity(self) -> None:
        assert pop_values(G11_A) == {"dichorionic", "twin"}
        assert pop_values(G11_B) == {"monochorionic", "twin"}
        assert sig(G11_A) != sig(G11_B)

    def test_group12_near_duplicate_control(self) -> None:
        assert sig(G12_A) == sig(G12_B) == frozenset(
            {("technique", "cfdna_screen"), ("technique", "nt")}
        )

    def test_group13_nipt_chance(self) -> None:
        assert pop_values(G13_A) == {"high_chance"}
        assert sig(G13_B) == frozenset(
            {("population", "low_chance"), ("technique", "nipt")}
        )

    def test_group14_anomaly_scan_window(self) -> None:
        assert sig(G14_A) == frozenset()
        assert ga_values(G14_B) == {"126:160"}

    def test_group15_mr_field_strength(self) -> None:
        assert tech_values(G15_A) == {"field_1.5t"}
        assert ga_values(G15_A) == {"126:"}
        assert tech_values(G15_B) == {"field_3t", "field_1.5t"}
        assert sig(G15_A) != sig(G15_B)


class TestSpanIntegrityAcrossGroups:
    @pytest.mark.parametrize("quote", ALL_QUOTES)
    def test_every_matched_text_slices_to_itself(self, quote: str) -> None:
        assert_p1(quote)


class TestNegativeControls:
    @pytest.mark.parametrize(
        "quote", [NEG_CONTROL_1, NEG_CONTROL_2, NEG_CONTROL_3]
    )
    def test_condition_free_quotes_extract_empty(self, quote: str) -> None:
        assert extract_conditions(quote) == []
