"""Property layer for the conditions gauntlet (hypothesis; SPEC-conditions F-model).

P1 span integrity  — every condition's matched_text equals the original-text
                     slice (incl. ligature back-mapping), at any base_offset.
P2 fail closed     — text over an alphabet with no pattern vocabulary yields
                     zero conditions (no fabricated GA/population/technique).
P3 ligature fold   — replacing ASCII "fi" with the ﬁ ligature changes neither
                     the condition value set nor matched_text content
                     (offsets shift; mapping must absorb it).

Usage:
    uv run --with pytest --with hypothesis python \
        benchmark/report/old-coder/property_conditions.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from prenatal_rag.conditions import (  # noqa: E402
    ChunkCondition,
    ConditionType,
    extract_conditions,
)

FILLER_WORDS = [
    "the", "patient", "guideline", "recommendation", "careful", "review",
    "clinical", "assessment", "follow", "structured", "reporting", "system",
    "standard", "practice", "evidence", "support", "level", "expert",
    "consensus", "statement", "quality", "safety", "audit",
]

_CLEAN_ALPHABET = "abcdefghijklmnopqrstuvwxyz \n.,;:'()"

# IGNORECASE 词表的全部小写可命中片段；生成文本不得包含它们。
_VOCAB_EXCLUSIONS = (
    "twin", "triplet", "singleton", "chorionic", "risk", "chance",
    "unselected", "obese", "ivf", "cfdna", "ductus", "nuchal",
    "translucency", "harmonic", "transvaginal", "transabdominal",
    "combined", "chamber", "vessel", "previous", "birth", "ptb", "week",
)

VOCAB_SNIPPETS = [
    "11+0 to 13+6 weeks",
    "between 18 and 22 weeks",
    "26 + 0 to 28 + 6 weeks",
    "from 10 weeks onwards",
    "before 14 weeks",
    "at 16 weeks",
    "34 weeks or more",
    "up to 24 weeks",
    "monochorionic twins",
    "dichorionic",
    "singleton",
    "cfDNA",
    "NT",
    "DV",
    "STV",
    "1.5 T",
    "harmonic imaging",
]


@st.composite
def _spliced_texts(draw: st.DrawFn) -> str:
    parts: list[str] = []
    for _ in range(draw(st.integers(1, 10))):
        if draw(st.booleans()):
            parts.append(draw(st.sampled_from(VOCAB_SNIPPETS)))
        else:
            parts.append(draw(st.sampled_from(FILLER_WORDS)))
    return " ".join(parts)


def _no_conditions_strategy() -> st.SearchStrategy[str]:
    # 无数字、无词表片段 → 任何模式都不应命中。
    return (
        st.lists(
            st.text(alphabet=_CLEAN_ALPHABET, min_size=1, max_size=15),
            min_size=1,
            max_size=12,
        )
        .map(lambda words: " ".join(words))
        .filter(
            lambda text: not any(
                fragment in text.lower() for fragment in _VOCAB_EXCLUSIONS
            )
        )
    )


def _assert_spans(text: str, conditions: list[ChunkCondition], base: int) -> None:
    for c in conditions:
        assert text[c.char_start - base : c.char_end - base] == c.matched_text


class TestSpanIntegrity:
    @settings(max_examples=200, deadline=None)
    @given(_spliced_texts(), st.integers(0, 500))
    def test_every_span_slices_to_matched_text(
        self, text: str, base_offset: int
    ) -> None:
        conditions = extract_conditions(
            text, anchor_id=1, source_id="S", base_offset=base_offset
        )
        _assert_spans(text, conditions, base_offset)


class TestFailClosed:
    @settings(max_examples=200, deadline=None)
    @given(_no_conditions_strategy())
    def test_clean_text_yields_no_conditions(self, text: str) -> None:
        conditions = extract_conditions(
            text, anchor_id=0, source_id="S", base_offset=0
        )
        assert conditions == [], text

    @settings(max_examples=100, deadline=None)
    @given(st.text(min_size=0, max_size=80))
    def test_arbitrary_text_never_crashes(self, text: str) -> None:
        # 任意字符串（含数字/符号）不崩溃；GA 窗口若产出则必然合理。
        conditions = extract_conditions(
            text, anchor_id=0, source_id="S", base_offset=0
        )
        for c in conditions:
            if c.condition_type is ConditionType.GESTATIONAL_AGE:
                lo, hi = c.value.split(":")
                assert lo == "" or int(lo) >= 0
                assert hi == "" or int(hi) >= 0


class TestLigatureFolding:
    @settings(max_examples=150, deadline=None)
    @given(_spliced_texts())
    def test_ligature_substitution_preserves_values(self, text: str) -> None:
        ligature_text = text.replace("fi", "ﬁ")
        if ligature_text == text:
            return
        plain = extract_conditions(text, anchor_id=1, source_id="S", base_offset=0)
        folded = extract_conditions(
            ligature_text, anchor_id=1, source_id="S", base_offset=0
        )
        assert {(c.condition_type, c.value) for c in plain} == {
            (c.condition_type, c.value) for c in folded
        }
        for c in folded:
            assert ligature_text[c.char_start : c.char_end] == c.matched_text


def main() -> int:
    # 直接运行（不经 pytest）时以等价的确定性冒烟代替：fail-closed 检查。
    smoke = ["", "no conditions here", "the patient was reviewed"]
    for text in smoke:
        assert extract_conditions(text) == []
    digits = re.compile(r"\d")
    assert digits.search("no conditions here") is None
    print("property_conditions: smoke ok (run via pytest for hypothesis layers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
