"""RRF 合并层测试：握手语义 + hypothesis 属性（确定性、通道序无关、去重）。"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from prenatal_rag.retrieval import reciprocal_rank_fusion, top_k


@given(
    channels=st.lists(
        st.lists(st.integers(min_value=0, max_value=40), min_size=1),
        min_size=1,
        max_size=5,
    ),
)
@settings(max_examples=200)
def test_rrf_is_permutation_of_union(channels: list[list[int]]) -> None:
    merged = reciprocal_rank_fusion(channels)
    union = sorted({item for ch in channels for item in ch}, key=str)
    assert sorted(merged, key=str) == union


@given(
    channels=st.lists(
        st.lists(st.integers(min_value=0, max_value=40), min_size=1),
        min_size=1,
        max_size=5,
    ),
)
@settings(max_examples=200)
def test_rrf_invariant_to_channel_order(channels: list[list[int]]) -> None:
    import random

    rng = random.Random(1234)
    shuffled = list(channels)
    rng.shuffle(shuffled)
    assert reciprocal_rank_fusion(channels) == reciprocal_rank_fusion(shuffled)


def test_shared_item_ranks_higher() -> None:
    # 单物品被两个通道同时召回 → RRF 分更高，排在最前。
    merged = reciprocal_rank_fusion([[7, 9], [7, 8]], k=60)
    assert merged[0] == 7
    assert set(merged) == {7, 8, 9}


def test_rank_position_determines_order() -> None:
    # 通道1:[10,20]，通道2:[30,40,50,60,20]。
    # 20 在两通道都被召回 → RRF 分最高排第一；此后 rank1 单召(10,30) > rank2(40) > …，
    # rank1 平分按 str 升序：10 先于 30。
    merged = reciprocal_rank_fusion([[10, 20], [30, 40, 50, 60, 20]], k=60)
    assert merged == [20, 10, 30, 40, 50, 60]


def test_top_k_behavior() -> None:
    merged = [5, 3, 1, 2]
    assert top_k(merged, 2) == [5, 3]
    assert top_k(merged, 0) == []
    assert top_k(merged, -1) == []


def test_k_nonpositive_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        reciprocal_rank_fusion([[1]], k=0)


def test_empty_and_empty_channels() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_duplicate_within_channel_counts_once() -> None:
    # 通道内重复条目只计最高排名处一次：[[10,20,20]] 去重后 10=1/61、20=1/62，
    # 故 20 应排在 10 之后；若重复计分则 20=1/62+1/63 反超 10，顺序翻转。
    assert reciprocal_rank_fusion([[10, 20, 20]], k=60) == [10, 20]

def test_diverse_top_k_caps_per_source() -> None:
    from prenatal_rag.retrieval import diverse_top_k

    merged = [1, 2, 3, 4, 5, 6]
    source_of = {1: "a", 2: "a", 3: "a", 4: "b", 5: "b", 6: "c"}
    # a 最多 2 条：第 3 条被跳过，b/c 补位。
    assert diverse_top_k(merged, 4, source_of=source_of, max_per_source=2) == [1, 2, 4, 5]
    assert diverse_top_k(merged, 6, source_of=source_of, max_per_source=2) == [1, 2, 4, 5, 6]


def test_diverse_top_k_fallbacks() -> None:
    from prenatal_rag.retrieval import diverse_top_k

    merged = [1, 2, 3]
    assert diverse_top_k(merged, 2) == [1, 2]
    assert diverse_top_k(merged, 0, source_of={1: "a"}) == []
    assert diverse_top_k(merged, 5, source_of={1: "a"}, max_per_source=0) == [1, 2, 3]
