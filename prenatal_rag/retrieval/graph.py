"""LightRAG 投影图召回通道（主文档 §5.1 第 2 步的"图"通道）。

PACE 的证据真值层是唯一 truth，LightRAG 图/向量是可重建投影；本模块把
LightRAG 索引里的 chunk 级邻接（``kv_store_entity_chunks.json`` 与
``kv_store_relation_chunks.json`` 两张 incidence 表）离线解析成一张确定性的
无向加权 chunk 图，作为 RRF 的第二个通道：从种子 chunk 出发按加权 BFS
扩展出邻居排名。纯 stdlib、零 LLM、完全确定性，便于跨版本复现与审计。

图是投影而非真值：chunk 键（``<doc>--<hash>-chunk-NNN``）是 LightRAG 的
切分身份；映射回真值层锚点由 :mod:`prenatal_rag.retrieval.bridge` 负责。
边权 = 两个 chunk 共同出现在几张 incidence 表（entity / relation）里，
权重与表顺序无关（每张表内对 chunk 列表去重后再两两成对），保证确定性。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

# LightRAG chunk 内容首两行为投影元数据头，不属于正文。
_SOURCE_ID_RE = re.compile(r"^SOURCE_ID:\s*(\S+)", re.MULTILINE)


def _source_of(content: str) -> str:
    match = _SOURCE_ID_RE.search(content)
    return match.group(1) if match else ""


def _link_pair(
    adjacency: dict[str, dict[str, int]], first: str, second: str
) -> None:
    """为无向边 ``first < second`` 加权；自环忽略；确定性的规范序。"""
    if first == second:
        return
    if first > second:
        first, second = second, first
    row = adjacency.setdefault(first, {})
    row[second] = row.get(second, 0) + 1


def _link_incidence(adjacency: dict[str, dict[str, int]], ids: Iterable[str]) -> None:
    """把一张 incidence 表的 chunk 列表两两成对连边（表内去重、与顺序无关）。"""
    unique = sorted(set(ids))
    for i, first in enumerate(unique):
        for second in unique[i + 1 :]:
            _link_pair(adjacency, first, second)


class LightRagChunkGraph:
    """LightRAG 投影的无向加权 chunk 图（chunk 键为节点）。

    Parameters
    ----------
    chunk_texts : chunk 键 -> 投影 chunk 正文（定义节点空间与来源解析）。
    chunk_source : chunk 键 -> source_id（可缺省为空串）。
    adjacency : chunk 键 -> {邻居 -> 边权}（无向，只存 ``first < second``）。
    """

    def __init__(
        self,
        chunk_texts: Mapping[str, str],
        chunk_source: Mapping[str, str],
        adjacency: Mapping[str, Mapping[str, int]],
    ) -> None:
        self._chunk_texts = dict(chunk_texts)
        self._chunk_source = dict(chunk_source)
        # 邻接在构建期只存规范序 first<second；这里对称化保证无向语义
        # （任意一端出发都能沿反向边扩展）。
        symmetric: dict[str, dict[str, int]] = {}
        for key, row in adjacency.items():
            for neighbor, weight in row.items():
                symmetric.setdefault(key, {})[neighbor] = weight
                symmetric.setdefault(neighbor, {})[key] = weight
        self._adjacency = symmetric
        self._nodes = frozenset(self._chunk_texts) | frozenset(self._adjacency)

    # ── 构建 ────────────────────────────────────────────────────────────────
    @classmethod
    def from_index_dir(cls, index_dir: Path) -> "LightRagChunkGraph":
        """从 LightRag 命名空间目录解析三个 JSON；缺文件抛带路径的 ValueError。"""
        index_dir = Path(index_dir)

        def _load(name: str) -> dict[str, object]:
            path = index_dir / name
            if not path.is_file():
                raise ValueError(f"LightRAG 投影索引缺失文件: {path}")
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"LightRAG 投影文件格式非法（非对象）: {path}")
            return data

        text_chunks = _load("kv_store_text_chunks.json")
        entity_chunks = _load("kv_store_entity_chunks.json")
        relation_chunks = _load("kv_store_relation_chunks.json")

        chunk_texts: dict[str, str] = {}
        chunk_source: dict[str, str] = {}
        for key, entry in text_chunks.items():
            if not isinstance(entry, dict):
                raise ValueError(f"LightRAG 投影 chunk 记录格式非法: {key}")
            content = entry.get("content", "")
            chunk_texts[key] = content
            chunk_source[key] = _source_of(str(content))

        adjacency: dict[str, dict[str, int]] = {}
        for record in (entity_chunks, relation_chunks):
            for entry in record.values():
                if not isinstance(entry, dict):
                    raise ValueError("LightRAG 投影 incidence 记录格式非法")
                ids = entry.get("chunk_ids", ())
                _link_incidence(adjacency, ids)
        return cls(chunk_texts, chunk_source, adjacency)

    # ── 查询 ────────────────────────────────────────────────────────────────
    def expand(
        self,
        seed_keys: Iterable[str],
        *,
        hops: int = 2,
        k: int = 20,
        include_seeds: bool = False,
    ) -> list[str]:
        """从种子出发按加权 BFS 返回邻居排名（确定性）。

        排名键：距离升序优先；同距离边权降序；再按 chunk 键升序。
        默认 ``include_seeds=False``：种子由词法通道给出，这里只返回扩展
        邻居，避免在 RRF 里重复计分。未知种子忽略；``k <= 0`` 返回空。
        """
        if k <= 0:
            return []
        hops = max(hops, 0)
        seen_keys = dict.fromkeys(seed_keys)
        seeds = [key for key in seen_keys if key in self._nodes]
        if not seeds:
            return []
        seed_set = set(seeds)
        # best[key] = (距离, 边权)：首次到达即锁定距离，同距离取最大边权。
        best: dict[str, tuple[int, int]] = {key: (0, 0) for key in seeds}
        frontier: list[str] = seeds
        for hop in range(1, hops + 1):
            candidates: dict[str, int] = {}
            for node in frontier:
                for neighbor, weight in self._adjacency.get(node, {}).items():
                    if neighbor in best:
                        continue
                    candidates[neighbor] = max(
                        candidates.get(neighbor, 0), weight
                    )
            if not candidates:
                break
            for neighbor, weight in candidates.items():
                best[neighbor] = (hop, weight)
            frontier = list(candidates)
        ranked = sorted(
            best.items(), key=lambda item: (item[1][0], -item[1][1], item[0])
        )
        result = [key for key, _ in ranked if include_seeds or key not in seed_set]
        return result[:k]

    def source_for(self, chunk_key: str) -> str:
        """返回投影 chunk 的来源 source_id；未知 chunk 返回空串。"""
        return self._chunk_source.get(chunk_key, "")

    @property
    def texts(self) -> Mapping[str, str]:
        """投影 chunk 正文映射（chunk 键 -> 内容）；供桥接构建等复用。"""
        return self._chunk_texts

    @property
    def chunk_count(self) -> int:
        return len(self._nodes)

    def __len__(self) -> int:
        return len(self._nodes)


__all__ = ["LightRagChunkGraph"]
