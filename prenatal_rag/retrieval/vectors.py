"""向量通道的本地存储与余弦排序（PACE 批次十一）。

背景：LightRAG 投影里已经存有**冻结**的 chunk 向量（``vdb_chunks.json``），
而 §5.1 的"并行召回"还缺第三路（embedding）。本模块把"读向量 + 本地余弦
排序"固化成可测 API，供
:class:`~prenatal_rag.retrieval.pipeline.EmbeddingChannel` 在锚点空间里与
BM25、图通道并列，再由 RRF **只按排名**合并（禁止把不同模型的相似度直接
相加，见 ``rrf`` 模块）。

实现取舍：本包不引入第三方依赖，故纯 stdlib——向量解码用 ``base64`` +
:mod:`array`，点积用 :func:`math.sumprod`（CPython 3.12 的 C 实现）。
在本项目 468×3072 的投影上，一次全量排序实测约 16 ms。

nano-vectordb v2 存储格式::

    {"embedding_dim": 3072,
     "data": [{"__id__": "…-chunk-000", "vector": "<base64(zlib(float16))>"}, …],
     "matrix": "<base64(float32 行主序矩阵)>"}

``matrix`` 逐行与 ``data`` 同序、是 float32 精确值；每条记录里的 ``vector``
是同一向量的 **float16 有损副本**（把它按 float32 误读会得到 ~1e-10 的伪值），
故一律以 ``matrix`` 为准。
"""

from __future__ import annotations

import base64
import json
import math
import sys
from array import array
from collections.abc import Iterable, Sequence
from pathlib import Path

__all__ = ["VectorIndex"]


def _decode_matrix(raw: bytes, *, swap: bool) -> array:
    """把 float32 行主序字节解码为数组；``swap=True`` 时按相反字节序解释。

    nano-vectordb 以小端写出，故 :meth:`VectorIndex.from_vdb_json` 传
    ``sys.byteorder == "big"``。本机（小端）上真实数据不会触发换序，因此该
    分支由测试显式传 ``swap=True`` 覆盖——换取的是"换序逻辑确实被执行且
    结果确实不同"的证据，而不是一条永不执行的代码。
    """
    decoded = array("f")
    decoded.frombytes(raw)
    if swap:
        decoded.byteswap()
    return decoded


class VectorIndex:
    """chunk 键 -> 向量的只读索引，提供确定性的余弦排序。

    维度必须一致、键必须唯一；零向量与零查询之间的余弦定义为 ``0.0``
    （不使用 NaN，也不抛除零错误）。索引只消费投影层已冻结的向量，
    向量本身可随时由真值层重建。

    Parameters
    ----------
    keys : chunk 键（唯一）。
    vectors : 与 ``keys`` 等长的向量行；行内维度必须一致。

    Raises
    ------
    ValueError : 键与向量数量不等、键重复、行维度不一致或行维度为 0。
    """

    __slots__ = ("_dimensions", "_flat", "_keys", "_norms", "_positions")

    def __init__(self, keys: Sequence[str], vectors: Sequence[Sequence[float]]) -> None:
        key_tuple = tuple(keys)
        if len(key_tuple) != len(vectors):
            raise ValueError(f"键数 {len(key_tuple)} 与向量数 {len(vectors)} 不等")
        rows = [tuple(float(value) for value in row) for row in vectors]
        dimensions = len(rows[0]) if rows else 0
        if rows and dimensions == 0:
            raise ValueError("向量维度不能为 0")
        for row in rows:
            if len(row) != dimensions:
                raise ValueError(f"向量维度不一致：期望 {dimensions}，实际 {len(row)}")
        flat = array("f")
        for row in rows:
            flat.extend(row)
        self._initialize(key_tuple, dimensions, flat)

    def _initialize(
        self, keys: tuple[str, ...], dimensions: int, flat: array
    ) -> None:
        """写入校验后的内部状态（构造路径共用的唯一入口）。"""
        if len(keys) != len(set(keys)):
            raise ValueError("chunk 键必须唯一")
        if len(flat) != len(keys) * dimensions:
            raise ValueError(
                f"向量总长 {len(flat)} 与 {len(keys)}×{dimensions} 不符"
            )
        self._keys = keys
        self._dimensions = dimensions
        self._flat = flat
        self._positions = {key: position for position, key in enumerate(keys)}
        if dimensions == 0:  # 空索引：无行可算范数。
            self._norms: tuple[float, ...] = ()
            return
        norms: list[float] = []
        for start in range(0, len(flat), dimensions):
            row = flat[start : start + dimensions]
            norms.append(math.sqrt(math.sumprod(row, row)))
        self._norms = tuple(norms)

    @classmethod
    def from_vdb_json(cls, path: Path) -> VectorIndex:
        """从 nano-vectordb 文件（``vdb_*.json``）读取向量（以 ``matrix`` 为准）。

        Raises
        ------
        KeyError : 缺少 ``embedding_dim`` / ``data`` / ``matrix`` 字段。
        ValueError : ``matrix`` 长度与 ``len(data) × embedding_dim`` 不符。
        """
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        dimensions = int(payload["embedding_dim"])
        keys = tuple(str(record["__id__"]) for record in payload["data"])
        flat = _decode_matrix(
            base64.b64decode(payload["matrix"]), swap=sys.byteorder == "big"
        )
        index = cls.__new__(cls)
        index._initialize(keys, dimensions, flat)
        return index

    @property
    def dimensions(self) -> int:
        """向量维度（空索引为 0）。"""
        return self._dimensions

    @property
    def keys(self) -> tuple[str, ...]:
        """全部 chunk 键（写入顺序）。"""
        return self._keys

    def __len__(self) -> int:
        return len(self._keys)

    def _row(self, position: int) -> array:
        return self._flat[
            position * self._dimensions : (position + 1) * self._dimensions
        ]

    def _prepare(self, query: Sequence[float]) -> tuple[float, ...]:
        prepared = tuple(float(value) for value in query)
        if len(prepared) != self._dimensions:
            raise ValueError(
                f"查询维度 {len(prepared)} 与索引维度 {self._dimensions} 不等"
            )
        return prepared

    def _similarity(
        self, position: int, query: tuple[float, ...], query_norm: float
    ) -> float:
        norm = self._norms[position]
        if norm == 0.0 or query_norm == 0.0:
            return 0.0
        return math.sumprod(self._row(position), query) / (norm * query_norm)

    def vector(self, key: str) -> tuple[float, ...]:
        """返回该 chunk 的向量；未知键抛 ``KeyError``。"""
        return tuple(self._row(self._positions[key]))

    def cosine(self, key: str, query: Sequence[float]) -> float:
        """返回该 chunk 与查询向量的余弦相似度。

        Raises
        ------
        KeyError : 未知 chunk 键。
        ValueError : 查询维度与索引维度不符。
        """
        position = self._positions[key]
        prepared = self._prepare(query)
        return self._similarity(
            position, prepared, math.sqrt(math.sumprod(prepared, prepared))
        )

    def rank(
        self,
        query: Sequence[float],
        *,
        k: int | None = None,
        keys: Iterable[str] | None = None,
    ) -> list[str]:
        """按余弦相似度降序返回 chunk 键（平分按键升序，确定性）。

        ``keys`` 非 None 时只在该子集内排序（子集去重、保持首次出现顺序；
        未知键抛 ``KeyError``）。``k`` 为 None 时返回全部；``k <= 0`` 返回
        空列表（与 :func:`~prenatal_rag.retrieval.rrf.top_k` 语义一致）。

        Raises
        ------
        KeyError : ``keys`` 子集内含未知 chunk 键。
        ValueError : 查询维度与索引维度不符。
        """
        if k is not None and k <= 0:
            return []
        if keys is None:
            subset = self._keys
        else:
            subset = tuple(dict.fromkeys(keys))
        prepared = self._prepare(query)
        query_norm = math.sqrt(math.sumprod(prepared, prepared))
        scored = [
            (self._similarity(self._positions[key], prepared, query_norm), key)
            for key in subset
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        ordered = [key for _, key in scored]
        return ordered if k is None else ordered[:k]
