"""投影 → 真值层锚点桥（主文档 §4"图/向量是可重建投影"的落点）。

LightRAG 的 chunk 切分与真值层（EvidenceStore）的段落装箱不同，两者没有
一一对应；图通道在 chunk 键空间产出排名后，需要映射回锚点空间才能与 BM25
通道在 RRF 里合并。本桥以**归一化文本的 token 集合 Jaccard** 为重叠度量，
把每个投影 chunk 映射到重叠最大的真值层锚点（平分取更小 anchor_id，保证
确定性），并维护反向索引 ``anchor_id -> [chunk key]``（按 key 升序）。

桥是近似而非精确（保真度由真实索引探针如实上报）；重叠低于
``min_jaccard`` 的映射不建立，避免把毫不相干的文本硬凑成锚点。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from prenatal_rag.evidence_store.store import EvidenceStore
from prenatal_rag.retrieval.bm25 import tokenize

# LightRAG 投影 chunk 内容首两行为元数据头（SOURCE_ID / ORIGINAL_FILE），
# 不属于正文，重叠度量前剔除。
_PROJECTION_HEADER_RE = re.compile(r"^(SOURCE_ID|ORIGINAL_FILE):.*$", re.MULTILINE)

Tokenizer = Callable[[str], list[str]]


def _strip_projection_header(text: str) -> str:
    return _PROJECTION_HEADER_RE.sub("", text)


class OverlapBridge:
    """chunk 键 <-> 锚点 id 的双向重叠映射。

    Parameters
    ----------
    mapping : chunk 键 -> 真值层锚点 id（重叠最大的锚点）。
    jaccards : 可选，chunk 键 -> 该映射的最佳重叠 Jaccard（保真度元数据）。
    """

    def __init__(
        self,
        mapping: Mapping[str, int],
        *,
        jaccards: Mapping[str, float] | None = None,
    ) -> None:
        self._mapping = dict(mapping)
        self._jaccards = dict(jaccards or {})
        inverse: dict[int, list[str]] = {}
        for key, anchor_id in self._mapping.items():
            inverse.setdefault(anchor_id, []).append(key)
        self._inverse = {anchor_id: sorted(keys) for anchor_id, keys in inverse.items()}

    @classmethod
    def build(
        cls,
        chunk_texts: Mapping[str, str],
        store: EvidenceStore,
        *,
        min_jaccard: float = 0.0,
        tokenizer: Tokenizer = tokenize,
    ) -> "OverlapBridge":
        """为一批投影 chunk 构建到真值层锚点的重叠映射（确定性）。

        每个 chunk 取与全部锚点中 Jaccard 最大者；``best_jaccard``
        低于 ``min_jaccard`` 时不建映射（``chunk_to_anchor`` 返回 None）。
        """
        anchors = list(store.iter_chunks())
        anchor_tokens = [set(tokenizer(chunk.text)) for chunk in anchors]
        mapping: dict[str, int] = {}
        jaccards: dict[str, float] = {}
        for key, content in chunk_texts.items():
            query_tokens = set(tokenizer(_strip_projection_header(content)))
            best_anchor: int | None = None
            best_jaccard = 0.0
            for chunk, at in zip(anchors, anchor_tokens):
                overlap = len(query_tokens & at)
                if overlap == 0:
                    continue
                jaccard = overlap / len(query_tokens | at)
                if (
                    best_anchor is None
                    or jaccard > best_jaccard
                    or (jaccard == best_jaccard and chunk.anchor_id < best_anchor)
                ):
                    best_jaccard = jaccard
                    best_anchor = chunk.anchor_id
            if best_anchor is not None and best_jaccard >= min_jaccard:
                mapping[key] = best_anchor
                jaccards[key] = best_jaccard
        return cls(mapping, jaccards=jaccards)

    def chunk_to_anchor(self, chunk_key: str) -> int | None:
        """返回投影 chunk 映射到的锚点 id；无映射返回 None。"""
        return self._mapping.get(chunk_key)

    def jaccard_for(self, chunk_key: str) -> float | None:
        """返回该映射的最佳重叠 Jaccard（保真度元数据）；无映射返回 None。"""
        return self._jaccards.get(chunk_key)

    def anchor_to_chunks(self, anchor_id: int) -> list[str]:
        """返回映射到该锚点的全部 chunk 键（按 key 升序）；空元组则空列表。"""
        return list(self._inverse.get(anchor_id, ()))


__all__ = ["OverlapBridge"]
