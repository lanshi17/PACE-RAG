"""向量索引（prenatal_rag.retrieval.vectors）测试。

覆盖：构造校验（数量/重复键/维度）、余弦的边界（零向量、零查询、维度不符、
未知键）、排序的确定性与平分键序、``k``/``keys`` 子集语义、nano-vectordb
读取（以 ``matrix`` 为准、长度校验、字节序），以及属性测试（排名是键的
排列、正缩放不变、k 是前缀、rank 与 cosine 交叉一致）。
"""

from __future__ import annotations

import base64
import json
import struct
import sys
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from prenatal_rag.retrieval import VectorIndex
from prenatal_rag.retrieval.vectors import _decode_matrix

FLOATS = st.floats(
    min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False, width=32
)


def _index() -> VectorIndex:
    """a/b 与查询同向且并列（键序 a 先）、c 正交、d 反向、z 为零向量。"""
    return VectorIndex(
        ["a", "b", "c", "d", "z"],
        [
            [1.0, 0.0],
            [1.0, 0.0],
            [0.0, 1.0],
            [-1.0, 0.0],
            [0.0, 0.0],
        ],
    )


class TestConstruction:
    def test_keys_dimensions_len(self) -> None:
        index = _index()
        assert index.keys == ("a", "b", "c", "d", "z")
        assert index.dimensions == 2
        assert len(index) == 5

    def test_vector_returns_row(self) -> None:
        assert _index().vector("c") == (0.0, 1.0)

    def test_unknown_key_raises(self) -> None:
        with pytest.raises(KeyError):
            _index().vector("missing")

    def test_count_mismatch_rejected(self) -> None:
        with pytest.raises(ValueError, match="不等"):
            VectorIndex(["a"], [[1.0], [2.0]])

    def test_duplicate_keys_rejected(self) -> None:
        with pytest.raises(ValueError, match="唯一"):
            VectorIndex(["a", "a"], [[1.0], [2.0]])

    def test_ragged_rows_rejected(self) -> None:
        with pytest.raises(ValueError, match="维度不一致"):
            VectorIndex(["a", "b"], [[1.0], [1.0, 2.0]])

    def test_zero_dimension_row_rejected(self) -> None:
        with pytest.raises(ValueError, match="维度不能为 0"):
            VectorIndex(["a"], [[]])

    def test_empty_index_allowed(self) -> None:
        index = VectorIndex([], [])
        assert len(index) == 0
        assert index.dimensions == 0
        assert index.rank(()) == []


class TestCosine:
    def test_identical_is_one(self) -> None:
        assert _index().cosine("a", [1.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_is_zero(self) -> None:
        assert _index().cosine("c", [1.0, 0.0]) == pytest.approx(0.0)

    def test_opposite_is_minus_one(self) -> None:
        assert _index().cosine("d", [1.0, 0.0]) == pytest.approx(-1.0)

    def test_zero_vector_row_is_zero(self) -> None:
        assert _index().cosine("z", [1.0, 0.0]) == 0.0

    def test_zero_query_is_zero(self) -> None:
        assert _index().cosine("a", [0.0, 0.0]) == 0.0

    def test_dimension_mismatch_rejected(self) -> None:
        with pytest.raises(ValueError, match="查询维度"):
            _index().cosine("a", [1.0, 0.0, 0.0])

    def test_unknown_key_raises(self) -> None:
        with pytest.raises(KeyError):
            _index().cosine("missing", [1.0, 0.0])


class TestRank:
    def test_order_and_tie_break_by_key(self) -> None:
        # d(-1) < z(0) < c(0) < a(1) == b(1)：平分（含 0.0）按键升序。
        assert _index().rank([1.0, 0.0]) == ["a", "b", "c", "z", "d"]

    def test_k_truncates_prefix(self) -> None:
        index = _index()
        assert index.rank([1.0, 0.0], k=2) == ["a", "b"]
        assert index.rank([1.0, 0.0], k=2) == index.rank([1.0, 0.0])[:2]

    def test_zero_k_returns_empty(self) -> None:
        assert _index().rank([1.0, 0.0], k=0) == []
        assert _index().rank([1.0, 0.0], k=-3) == []

    def test_keys_subset_restricts_and_dedups(self) -> None:
        index = _index()
        assert index.rank([1.0, 0.0], keys=["c", "c", "a"]) == ["a", "c"]

    def test_keys_subset_unknown_key_raises(self) -> None:
        with pytest.raises(KeyError):
            _index().rank([1.0, 0.0], keys=["missing"])

    def test_dimension_mismatch_rejected(self) -> None:
        with pytest.raises(ValueError, match="查询维度"):
            _index().rank([1.0])

    def test_deterministic_across_calls(self) -> None:
        index = _index()
        assert index.rank([1.0, 0.0]) == index.rank([1.0, 0.0])


class TestDecodeMatrix:
    def test_little_endian_values(self) -> None:
        raw = struct.pack("<4f", 1.0, -2.0, 0.5, 3.0)
        assert tuple(_decode_matrix(raw, swap=False)) == (1.0, -2.0, 0.5, 3.0)

    def test_swap_byteswaps(self) -> None:
        raw = struct.pack("<4f", 1.0, -2.0, 0.5, 3.0)
        assert tuple(_decode_matrix(raw, swap=True)) != tuple(
            _decode_matrix(raw, swap=False)
        )

    def test_host_order_matches_native_decode(self) -> None:
        raw = struct.pack("<2f", 1.5, -0.25)
        decoded = _decode_matrix(raw, swap=sys.byteorder == "big")
        assert tuple(decoded) == (1.5, -0.25)


def _write_vdb(path: Path, dim: int, keys: list[str], flat: bytes) -> None:
    path.write_text(
        json.dumps(
            {
                "embedding_dim": dim,
                "data": [{"__id__": key} for key in keys],
                "matrix": base64.b64encode(flat).decode("ascii"),
            }
        ),
        encoding="utf-8",
    )


class TestFromVdbJson:
    def test_round_trip(self, tmp_path) -> None:
        path = tmp_path / "vdb_chunks.json"
        _write_vdb(path, 2, ["k1", "k2"], struct.pack("<4f", 1.0, 0.0, 0.0, 1.0))
        index = VectorIndex.from_vdb_json(path)
        assert index.keys == ("k1", "k2")
        assert index.dimensions == 2
        assert index.vector("k1") == (1.0, 0.0)
        assert index.cosine("k1", [1.0, 0.0]) == pytest.approx(1.0)
        assert index.rank([1.0, 0.0]) == ["k1", "k2"]

    def test_matrix_length_mismatch_rejected(self, tmp_path) -> None:
        path = tmp_path / "vdb_chunks.json"
        _write_vdb(path, 2, ["k1", "k2"], struct.pack("<3f", 1.0, 0.0, 0.0))
        with pytest.raises(ValueError, match="不符"):
            VectorIndex.from_vdb_json(path)

    def test_missing_field_raises(self, tmp_path) -> None:
        path = tmp_path / "vdb_chunks.json"
        path.write_text(json.dumps({"data": [], "matrix": ""}), encoding="utf-8")
        with pytest.raises(KeyError):
            VectorIndex.from_vdb_json(path)


class TestProperties:
    @given(rows=st.lists(st.lists(FLOATS, min_size=2, max_size=2), min_size=1, max_size=4),
           query=st.lists(FLOATS, min_size=2, max_size=2))
    def test_rank_is_permutation_of_keys(self, rows, query) -> None:
        index = VectorIndex([f"k{i}" for i in range(len(rows))], rows)
        ranked = index.rank(query)
        assert sorted(ranked) == sorted(index.keys)

    @given(rows=st.lists(st.lists(FLOATS, min_size=2, max_size=2), min_size=1, max_size=4),
           query=st.lists(FLOATS, min_size=2, max_size=2))
    def test_positive_doubling_is_rank_invariant(self, rows, query) -> None:
        index = VectorIndex([f"k{i}" for i in range(len(rows))], rows)
        doubled = [value * 2.0 for value in query]
        assert index.rank(query) == index.rank(doubled)

    @given(rows=st.lists(st.lists(FLOATS, min_size=2, max_size=2), min_size=1, max_size=4),
           query=st.lists(FLOATS, min_size=2, max_size=2),
           cut=st.integers(min_value=0, max_value=4))
    def test_k_is_prefix_of_full_ranking(self, rows, query, cut) -> None:
        index = VectorIndex([f"k{i}" for i in range(len(rows))], rows)
        assert index.rank(query, k=cut) == index.rank(query)[:cut]

    @given(rows=st.lists(st.lists(FLOATS, min_size=2, max_size=2), min_size=1, max_size=4),
           query=st.lists(FLOATS, min_size=2, max_size=2))
    def test_top_ranked_has_max_cosine(self, rows, query) -> None:
        index = VectorIndex([f"k{i}" for i in range(len(rows))], rows)
        best = index.rank(query)[0]
        assert index.cosine(best, query) == max(
            index.cosine(key, query) for key in index.keys
        )

    @given(rows=st.lists(st.lists(FLOATS, min_size=2, max_size=2), min_size=2, max_size=4),
           query=st.lists(FLOATS, min_size=2, max_size=2))
    def test_cosine_is_symmetric(self, rows, query) -> None:
        # 把查询本身作为一个键放进索引：cos(k_i, q) 应等于 cos(q, v_i)。
        keys = [f"k{i}" for i in range(len(rows))] + ["q"]
        index = VectorIndex(keys, [*rows, query])
        for i in range(len(rows)):
            assert index.cosine(f"k{i}", query) == pytest.approx(
                index.cosine("q", rows[i])
            )
