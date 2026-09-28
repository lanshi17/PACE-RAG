"""投影 → 真值层锚点桥（prenatal_rag.retrieval.bridge）测试。

覆盖：最佳重叠映射、投影头剥离、平分取小 anchor_id、min_jaccard 严格
阈值边界，以及 hypothesis 属性（双向映射自洽）。
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from prenatal_rag.evidence_store import EvidenceStore
from prenatal_rag.retrieval import OverlapBridge


def _store(tmp_path, docs: list[tuple[str, str]]) -> EvidenceStore:
    store = EvidenceStore(tmp_path / "es")
    for index, (source_id, text) in enumerate(docs):
        store.ingest_document(
            source_id, f"## Page 1\n\n{text}\n", family_id=f"fam-{index}"
        )
    return store


def _anchor(store: EvidenceStore, source_id: str) -> int:
    return next(c.anchor_id for c in store.iter_chunks() if c.source_id == source_id)


class TestBuild:
    def test_exact_match_maps_with_header_stripped(self, tmp_path) -> None:
        store = _store(
            tmp_path,
            [
                ("Doc-A", "nuchal translucency measurement at eleven weeks"),
                ("Doc-B", "fetal cardiac screening views"),
            ],
        )
        anchor_a = _anchor(store, "Doc-A")
        bridge = OverlapBridge.build(
            {
                "a--chunk-000": (
                    "SOURCE_ID: Doc-A\nORIGINAL_FILE: x.pdf\n\n"
                    "nuchal translucency measurement at eleven weeks\n"
                )
            },
            store,
        )
        # 头行被剥离，正文与锚点 token 完全一致 → Jaccard 1.0。
        assert bridge.chunk_to_anchor("a--chunk-000") == anchor_a
        assert bridge.anchor_to_chunks(anchor_a) == ["a--chunk-000"]
        assert bridge.jaccard_for("a--chunk-000") == 1.0
        assert bridge.jaccard_for("no-such-chunk") is None

    def test_partial_overlap_maps_to_best_not_first(self, tmp_path) -> None:
        # 先遍历到 Doc-A（重叠 0.2），但最佳重叠是 Doc-B（0.75）：
        # 必须取最大重叠锚点，而不是首个出现重叠的锚点。
        store = _store(
            tmp_path,
            [
                ("Doc-A", "fetal cardiac views"),
                ("Doc-B", "cardiac screening fetus view"),
            ],
        )
        anchor_b = _anchor(store, "Doc-B")
        bridge = OverlapBridge.build(
            {"b--chunk-000": "cardiac screening fetus"}, store
        )
        assert bridge.chunk_to_anchor("b--chunk-000") == anchor_b

    def test_no_overlap_is_not_mapped(self, tmp_path) -> None:
        store = _store(tmp_path, [("Doc-A", "nuchal translucency at eleven weeks")])
        bridge = OverlapBridge.build(
            {"z--chunk-000": "zzz qqq www", "h--chunk-000": "SOURCE_ID: Doc-A\nORIGINAL_FILE: x"},
            store,
        )
        assert bridge.chunk_to_anchor("z--chunk-000") is None
        assert bridge.chunk_to_anchor("h--chunk-000") is None  # 仅有头行 → 空 token

    def test_tie_picks_smaller_anchor_id(self, tmp_path) -> None:
        store = _store(
            tmp_path,
            [("Doc-C", "alpha beta"), ("Doc-D", "alpha beta")],
        )
        anchor_c = _anchor(store, "Doc-C")
        anchor_d = _anchor(store, "Doc-D")
        assert anchor_c < anchor_d
        bridge = OverlapBridge.build({"c--chunk-000": "alpha beta"}, store)
        assert bridge.chunk_to_anchor("c--chunk-000") == anchor_c

    def test_min_jaccard_boundary_at_exactly_threshold(self, tmp_path) -> None:
        store = _store(tmp_path, [("Doc-E", "red green")])
        anchor_e = _anchor(store, "Doc-E")
        # "red" 与 {red, green} 的 Jaccard 恰为 0.5：>= 阈值应包含，> 阈值应剔除。
        kept = OverlapBridge.build({"e--chunk-000": "red"}, store, min_jaccard=0.5)
        dropped = OverlapBridge.build(
            {"e--chunk-000": "red"}, store, min_jaccard=0.5 + 1e-9
        )
        assert kept.chunk_to_anchor("e--chunk-000") == anchor_e
        assert dropped.chunk_to_anchor("e--chunk-000") is None

    def test_multiple_keys_to_same_anchor_sorted(self, tmp_path) -> None:
        store = _store(
            tmp_path,
            [("Doc-A", "nuchal translucency measurement at eleven weeks")],
        )
        anchor_a = _anchor(store, "Doc-A")
        bridge = OverlapBridge.build(
            {
                "a--chunk-000": "nuchal translucency measurement at eleven weeks",
                "a2--chunk-000": "nuchal translucency measurement at eleven weeks",
            },
            store,
        )
        assert bridge.anchor_to_chunks(anchor_a) == [
            "a--chunk-000",
            "a2--chunk-000",
        ]


class TestDirectConstruction:
    def test_anchor_to_chunks_sorted_and_unknown_empty(self) -> None:
        bridge = OverlapBridge({"k": 7, "j": 7, "m": 9})
        assert bridge.anchor_to_chunks(7) == ["j", "k"]
        assert bridge.anchor_to_chunks(9) == ["m"]
        assert bridge.anchor_to_chunks(123) == []

    def test_chunk_to_anchor_unknown_is_none(self) -> None:
        bridge = OverlapBridge({"k": 7})
        assert bridge.chunk_to_anchor("nope") is None
        assert bridge.chunk_to_anchor("k") == 7

    def test_jaccard_for_requires_jaccards(self) -> None:
        bridge = OverlapBridge({"k": 7})
        assert bridge.jaccard_for("k") is None
        with_j = OverlapBridge({"k": 7}, jaccards={"k": 0.6})
        assert with_j.jaccard_for("k") == 0.6

    def test_empty_mapping(self) -> None:
        bridge = OverlapBridge({})
        assert bridge.anchor_to_chunks(1) == []
        assert bridge.chunk_to_anchor("k") is None


@given(
    st.dictionaries(
        st.text(min_size=1, max_size=8), st.integers(min_value=0, max_value=20),
        min_size=0, max_size=10,
    )
)
@settings(max_examples=100)
def test_inverse_contains_each_key(mapping) -> None:
    bridge = OverlapBridge(mapping)
    for key, anchor_id in mapping.items():
        assert bridge.chunk_to_anchor(key) == anchor_id
        assert key in bridge.anchor_to_chunks(anchor_id)
