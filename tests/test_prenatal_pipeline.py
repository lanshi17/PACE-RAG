"""并行召回编排（prenatal_rag.retrieval.pipeline）测试。

覆盖：GraphChannel 种子→扩展→回映锚点的确定性、去重与 k 截断；
condition_seed_anchors 的三值门控；EmbeddingChannel 的向量→锚点回映；
parallel_recall 的两通道/三通道 RRF 合并顺序与向后兼容。
"""

from __future__ import annotations

import pytest

from prenatal_rag.conditions import (
    ChunkCondition,
    ConditionType,
    GaWindow,
    QueryConditions,
)
from prenatal_rag.evidence_store import EvidenceStore
from prenatal_rag.retrieval import (
    EmbeddingChannel,
    GraphChannel,
    LightRagChunkGraph,
    OverlapBridge,
    VectorIndex,
    condition_seed_anchors,
    parallel_recall,
)


def _graph() -> LightRagChunkGraph:
    return LightRagChunkGraph(
        chunk_texts={"kA": "a", "kB": "b", "kC": "c", "kD": "d", "kE": "e"},
        chunk_source={key: "s" for key in ("kA", "kB", "kC", "kD", "kE")},
        adjacency={"kA": {"kB": 2, "kC": 1, "kD": 1, "kE": 1}},
    )


def _bridge() -> OverlapBridge:
    # kE 不在映射中 → 回映时被跳过。
    return OverlapBridge({"kA": 1, "kB": 2, "kC": 3, "kD": 4})


class TestGraphChannelRank:
    def test_seed_anchor_expands_to_anchor_ranking(self) -> None:
        channel = GraphChannel(_graph(), _bridge())
        assert channel.rank([1]) == [2, 3, 4]

    def test_k_truncates_and_none_returns_all(self) -> None:
        channel = GraphChannel(_graph(), _bridge())
        assert channel.rank([1], k=2) == [2, 3]
        assert channel.rank([1], k=None) == [2, 3, 4]

    def test_empty_and_unknown_seeds(self) -> None:
        channel = GraphChannel(_graph(), _bridge())
        assert channel.rank([]) == []
        assert channel.rank([99]) == []

    def test_duplicate_anchor_deduplicated_keep_first(self) -> None:
        # kB、kC 都映射到锚点 2：只保留图排名更高的 kB（首个）。
        channel = GraphChannel(
            _graph(), OverlapBridge({"kA": 1, "kB": 2, "kC": 2})
        )
        assert channel.rank([1]) == [2]

    def test_deterministic_across_calls(self) -> None:
        channel = GraphChannel(_graph(), _bridge())
        assert channel.rank([1]) == channel.rank([1])

    def test_zero_k_returns_empty(self) -> None:
        channel = GraphChannel(_graph(), _bridge())
        assert channel.rank([1], k=0) == []
        assert channel.rank([1], k=-1) == []


def _index() -> VectorIndex:
    """kA/kB 与查询同向且并列、kC 正交、kD 反向、kE 无桥映射。"""
    return VectorIndex(
        ["kA", "kB", "kC", "kD", "kE"],
        [
            [1.0, 0.0],
            [1.0, 0.0],
            [0.0, 1.0],
            [-1.0, 0.0],
            [0.5, 0.5],
        ],
    )


class TestEmbeddingChannel:
    def test_vector_ranking_maps_to_anchors(self) -> None:
        # 向量序 kA,kB,kE,kC,kD；kE 无映射被跳过 → 锚点 1,2,3,4。
        channel = EmbeddingChannel(_index(), _bridge())
        assert channel.rank([1.0, 0.0]) == [1, 2, 3, 4]

    def test_k_truncates(self) -> None:
        channel = EmbeddingChannel(_index(), _bridge())
        assert channel.rank([1.0, 0.0], k=2) == [1, 2]

    def test_zero_k_returns_empty(self) -> None:
        channel = EmbeddingChannel(_index(), _bridge())
        assert channel.rank([1.0, 0.0], k=0) == []

    def test_duplicate_anchor_deduplicated_keep_first(self) -> None:
        # kA、kB 都映射到锚点 1：只保留向量排名更高的 kA（首个）。
        channel = EmbeddingChannel(_index(), OverlapBridge({"kA": 1, "kB": 1}))
        assert channel.rank([1.0, 0.0]) == [1]

    def test_unmapped_only_returns_empty(self) -> None:
        channel = EmbeddingChannel(_index(), OverlapBridge({}))
        assert channel.rank([1.0, 0.0]) == []

    def test_dimension_mismatch_raises(self) -> None:
        channel = EmbeddingChannel(_index(), _bridge())
        with pytest.raises(ValueError, match="查询维度"):
            channel.rank([1.0])

    def test_empty_index_with_empty_query_returns_empty(self) -> None:
        channel = EmbeddingChannel(VectorIndex([], []), _bridge())
        assert channel.rank(()) == []

    def test_deterministic_across_calls(self) -> None:
        channel = EmbeddingChannel(_index(), _bridge())
        assert channel.rank([1.0, 0.0]) == channel.rank([1.0, 0.0])


def _seeded_store(tmp_path) -> tuple[EvidenceStore, int]:
    store = EvidenceStore(tmp_path / "es")
    store.ingest_document(
        "Doc-A", "## Page 1\n\nalpha beta gamma delta\n", family_id="fam-A"
    )
    chunk = next(iter(store.iter_chunks()))
    store.rewrite_chunk_conditions(
        chunk.anchor_id,
        [
            ChunkCondition(
                chunk.anchor_id, "Doc-A", ConditionType.GESTATIONAL_AGE,
                GaWindow.closed(77, 97).serialize(), 0, 1, "11", "",
            ),
            ChunkCondition(
                chunk.anchor_id, "Doc-A", ConditionType.POPULATION,
                "twin", 0, 1, "twin", "",
            ),
        ],
    )
    return store, chunk.anchor_id


class TestConditionSeedAnchors:
    def test_empty_query_seeds_all(self, tmp_path) -> None:
        store, anchor_id = _seeded_store(tmp_path)
        assert condition_seed_anchors(store, QueryConditions()) == [anchor_id]

    def test_population_opposite_is_inapplicable_and_excluded(self, tmp_path) -> None:
        store, _ = _seeded_store(tmp_path)
        query = QueryConditions(population=frozenset({"singleton"}))
        assert condition_seed_anchors(store, query) == []

    def test_matching_population_is_kept(self, tmp_path) -> None:
        store, anchor_id = _seeded_store(tmp_path)
        query = QueryConditions(population=frozenset({"twin"}))
        assert condition_seed_anchors(store, query) == [anchor_id]

    def test_partial_ga_overlap_is_unknown_and_kept(self, tmp_path) -> None:
        store, anchor_id = _seeded_store(tmp_path)
        # 证据窗口 77:97；查询 70:90 部分重叠 → Unknown → 保留。
        query = QueryConditions(gestational_age=GaWindow.closed(70, 90))
        assert condition_seed_anchors(store, query) == [anchor_id]

    def test_no_ga_overlap_is_inapplicable_and_excluded(self, tmp_path) -> None:
        store, _ = _seeded_store(tmp_path)
        query = QueryConditions(gestational_age=GaWindow.closed(50, 60))
        assert condition_seed_anchors(store, query) == []


class TestParallelRecall:
    def test_rrf_merge_ordering(self) -> None:
        assert parallel_recall([1, 2, 3], [3, 4, 5], k=5) == [3, 1, 2, 4, 5]

    def test_k_truncates(self) -> None:
        assert parallel_recall([1, 2, 3], [3, 4, 5], k=3) == [3, 1, 2]

    def test_empty_graph_channel_ok(self) -> None:
        assert parallel_recall([1, 2], [], k=2) == [1, 2]

    def test_zero_k_returns_empty(self) -> None:
        assert parallel_recall([1, 2], [2, 3], k=0) == []

    def test_deterministic(self) -> None:
        assert parallel_recall([1, 2, 3], [3, 4, 5], k=5) == parallel_recall(
            [1, 2, 3], [3, 4, 5], k=5
        )

    def test_embedding_none_matches_two_channel(self) -> None:
        two = parallel_recall([1, 2, 3], [3, 4, 5], k=5)
        assert parallel_recall([1, 2, 3], [3, 4, 5], k=5, embedding_ranking=None) == two

    def test_three_channel_merge_ordering(self) -> None:
        # 嵌入通道 [5,6,7]：5 与 3 同分（各自通道 rank1+rank3 组合不同）
        # → 3=1/61+1/63 与 5=1/63+1/61 并列，按键升序 → 3 先。
        assert parallel_recall(
            [1, 2, 3], [3, 4, 5], k=7, embedding_ranking=[5, 6, 7]
        ) == [3, 5, 1, 2, 4, 6, 7]

    def test_three_channel_k_truncates(self) -> None:
        assert parallel_recall(
            [1, 2, 3], [3, 4, 5], k=2, embedding_ranking=[5, 6, 7]
        ) == [3, 5]

    def test_embedding_only_channel_merges(self) -> None:
        assert parallel_recall([], [], k=3, embedding_ranking=[7, 8]) == [7, 8]

    def test_three_channel_deterministic(self) -> None:
        first = parallel_recall([1, 2, 3], [3, 4, 5], k=7, embedding_ranking=[5, 6, 7])
        second = parallel_recall([1, 2, 3], [3, 4, 5], k=7, embedding_ranking=[5, 6, 7])
        assert first == second
