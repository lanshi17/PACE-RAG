"""LightRAG 投影图通道（prenatal_rag.retrieval.graph）测试。

覆盖：incidence 解析、无向加权邻接、加权 BFS 扩展的确定性排序、
from_index_dir 的失败分支，以及 hypothesis 属性（确定性/子集/无重复）。
"""

from __future__ import annotations

import json

import pytest
from hypothesis import given, settings, strategies as st

from prenatal_rag.retrieval.graph import LightRagChunkGraph, _link_pair


def _tiny_graph() -> LightRagChunkGraph:
    """a-b 边权 2；a-c、a-d、c-d 边权 1；e 孤立。"""
    return LightRagChunkGraph(
        chunk_texts={
            "a": "alpha text",
            "b": "beta text",
            "c": "gamma text",
            "d": "delta text",
            "e": "epsilon text",
        },
        chunk_source={"a": "s1", "b": "s1", "c": "s2", "d": "s2", "e": "s3"},
        adjacency={
            "a": {"b": 2, "c": 1, "d": 1},
            "c": {"d": 1},
        },
    )


class TestFromIndexDir:
    def _write(self, tmp_path, *, text_chunks, entity_chunks, relation_chunks) -> None:
        ns = tmp_path / "ns"
        ns.mkdir()
        (ns / "kv_store_text_chunks.json").write_text(
            json.dumps(text_chunks), encoding="utf-8"
        )
        (ns / "kv_store_entity_chunks.json").write_text(
            json.dumps(entity_chunks), encoding="utf-8"
        )
        (ns / "kv_store_relation_chunks.json").write_text(
            json.dumps(relation_chunks), encoding="utf-8"
        )

    def test_builds_weighted_undirected_adjacency(self, tmp_path) -> None:
        self._write(
            tmp_path,
            text_chunks={
                "a--chunk-000": {"content": "SOURCE_ID: doc-a\n\nalpha"},
                "b--chunk-001": {"content": "SOURCE_ID: doc-b\n\nbeta"},
                "c--chunk-002": {"content": "SOURCE_ID: doc-c\n\ngamma"},
            },
            entity_chunks={
                "e1": {"chunk_ids": ["a--chunk-000", "b--chunk-001"]},
                "e2": {"chunk_ids": ["a--chunk-000", "c--chunk-002"]},
            },
            relation_chunks={
                "e1<SEP>e2": {"chunk_ids": ["a--chunk-000", "b--chunk-001"]},
            },
        )
        graph = LightRagChunkGraph.from_index_dir(tmp_path / "ns")
        assert graph.chunk_count == 3
        # a-b 共同出现在 e1 + relation → 边权 2；a-c 仅 e2 → 边权 1。
        assert graph.expand(["a--chunk-000"], hops=1, k=10) == [
            "b--chunk-001",
            "c--chunk-002",
        ]
        # 无向：从 b 出发同样可达 a。
        assert "a--chunk-000" in graph.expand(["b--chunk-001"], hops=1, k=10)
        assert graph.source_for("a--chunk-000") == "doc-a"

    def test_source_empty_when_header_absent(self, tmp_path) -> None:
        self._write(
            tmp_path,
            text_chunks={"x--chunk-000": {"content": "no header here"}},
            entity_chunks={},
            relation_chunks={},
        )
        graph = LightRagChunkGraph.from_index_dir(tmp_path / "ns")
        assert graph.source_for("x--chunk-000") == ""

    def test_missing_file_raises_with_path(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="LightRAG 投影索引缺失文件"):
            LightRagChunkGraph.from_index_dir(tmp_path / "empty")

    def test_non_object_json_raises(self, tmp_path) -> None:
        ns = tmp_path / "ns"
        ns.mkdir()
        (ns / "kv_store_text_chunks.json").write_text("[1, 2]", encoding="utf-8")
        (ns / "kv_store_entity_chunks.json").write_text("{}", encoding="utf-8")
        (ns / "kv_store_relation_chunks.json").write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="格式非法"):
            LightRagChunkGraph.from_index_dir(ns)

    def test_invalid_chunk_record_raises(self, tmp_path) -> None:
        self._write(
            tmp_path,
            text_chunks={"x": ["not-a-dict"]},
            entity_chunks={},
            relation_chunks={},
        )
        with pytest.raises(ValueError, match="chunk 记录格式非法"):
            LightRagChunkGraph.from_index_dir(tmp_path / "ns")

    def test_invalid_incidence_record_raises(self, tmp_path) -> None:
        self._write(
            tmp_path,
            text_chunks={"x--chunk-000": {"content": "alpha"}},
            entity_chunks={"e1": ["not-a-dict"]},
            relation_chunks={},
        )
        with pytest.raises(ValueError, match="incidence 记录格式非法"):
            LightRagChunkGraph.from_index_dir(tmp_path / "ns")


class TestExpand:
    def test_closer_neighbors_first_then_weight(self) -> None:
        graph = _tiny_graph()
        assert graph.expand(["a"], hops=1, k=10) == ["b", "c", "d"]

    def test_two_hop_reachability(self) -> None:
        graph = _tiny_graph()
        # c 一跳：a、d；a 的二跳邻居 b 在第二跳出现。
        assert graph.expand(["c"], hops=2, k=10) == ["a", "d", "b"]

    def test_seeds_excluded_by_default(self) -> None:
        graph = _tiny_graph()
        result = graph.expand(["a"], hops=2, k=10)
        assert "a" not in result

    def test_include_seeds(self) -> None:
        graph = _tiny_graph()
        assert graph.expand(["a"], hops=1, k=10, include_seeds=True)[0] == "a"

    def test_k_truncates(self) -> None:
        graph = _tiny_graph()
        assert graph.expand(["a"], hops=1, k=2) == ["b", "c"]

    def test_zero_k_returns_empty(self) -> None:
        graph = _tiny_graph()
        assert graph.expand(["a"], k=0) == []

    def test_zero_hops_yields_only_seeds_then_excluded(self) -> None:
        graph = _tiny_graph()
        assert graph.expand(["a"], hops=0, k=10) == []

    def test_unknown_seed_ignored(self) -> None:
        graph = _tiny_graph()
        assert graph.expand(["zzz"], hops=2, k=10) == []
        assert graph.expand(["zzz", "a"], hops=1, k=10) == ["b", "c", "d"]

    def test_isolated_seed_has_no_neighbors(self) -> None:
        graph = _tiny_graph()
        assert graph.expand(["e"], hops=2, k=10) == []

    def test_empty_graph(self) -> None:
        graph = LightRagChunkGraph({}, {}, {})
        assert graph.expand(["a"], hops=2, k=10) == []
        assert len(graph) == 0

    def test_deterministic_across_calls(self) -> None:
        graph = _tiny_graph()
        assert graph.expand(["a"], hops=2, k=10) == graph.expand(
            ["a"], hops=2, k=10
        )


class TestLinkPair:
    def test_canonical_swap_self_and_increment(self) -> None:
        adjacency: dict[str, dict[str, int]] = {}
        _link_pair(adjacency, "z", "a")  # 规范序：a < z
        assert adjacency == {"a": {"z": 1}}
        _link_pair(adjacency, "a", "a")  # 自环忽略
        assert adjacency == {"a": {"z": 1}}
        _link_pair(adjacency, "a", "z")  # 再次成对 → 边权 +1
        assert adjacency == {"a": {"z": 2}}


class TestSourceAndSize:
    def test_source_for_known_and_unknown(self) -> None:
        graph = _tiny_graph()
        assert graph.source_for("a") == "s1"
        assert graph.source_for("nope") == ""

    def test_chunk_count(self) -> None:
        assert _tiny_graph().chunk_count == 5

    def test_texts_mapping(self) -> None:
        graph = _tiny_graph()
        assert graph.texts["a"] == "alpha text"
        assert len(graph.texts) == 5


_KEYS = st.lists(
    st.sampled_from(["a", "b", "c", "d", "e", "zzz"]), min_size=0, max_size=6
)


@given(
    _KEYS,
    st.integers(min_value=0, max_value=4),
    st.integers(min_value=1, max_value=12),
    st.booleans(),
)
@settings(max_examples=100)
def test_expand_deterministic_and_subset(seeds, hops, k, include_seeds) -> None:
    graph = _tiny_graph()
    first = graph.expand(seeds, hops=hops, k=k, include_seeds=include_seeds)
    second = graph.expand(seeds, hops=hops, k=k, include_seeds=include_seeds)
    assert first == second
    assert len(first) == len(set(first))
    nodes = {"a", "b", "c", "d", "e"}
    known = set(seeds) & nodes
    allowed = nodes if include_seeds else nodes - known
    assert set(first) <= allowed
