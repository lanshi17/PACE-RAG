"""BM25 召回通道（主文档 §5.1 第 2 步）。

并行召回的各通道（BM25 / embedding / 图）各自输出排名，由上层 RRF 合并；
禁止把未经校准的相似度直接相加，因此本模块只输出排名与 BM25 分数。
无第三方依赖、完全确定性，便于跨版本复现与审计。
分词：英文按字母数字词（小写化），CJK 字符逐字成 token——查询与语料
中英混排（中文问题、英文指南）时两侧使用同一分词器。
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

from prenatal_rag.evidence_store.store import EvidenceStore

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """小写化英文词与逐字 CJK token；与索引、查询两侧共用。"""
    return _TOKEN_RE.findall(text.lower())


@dataclass(frozen=True)
class ScoredChunk:
    """BM25 命中结果；rank 为 1-based 排名。"""

    chunk_id: int
    source_id: str
    score: float
    rank: int


class Bm25Index:
    """内存只读 Okapi BM25 索引。

    k1=1.5、b=0.75 为起步超参（主文档 §5.1：所有超参在开发集调优，
    不是效果保证）。平分时按 chunk_id 升序保证确定性。
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._doc_ids: list[tuple[int, str]] = []
        self._doc_len: list[int] = []
        self._avgdl: float = 0.0
        self._postings: dict[str, list[tuple[int, int]]] = {}

    @classmethod
    def build(
        cls,
        chunks: Iterable[tuple[int, str, str]],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> "Bm25Index":
        """构建索引；``chunks`` 产出 (chunk_id, source_id, text)，id 必须唯一。"""
        index = cls(k1=k1, b=b)
        seen: set[int] = set()
        total_len = 0
        for chunk_id, source_id, text in chunks:
            if chunk_id in seen:
                raise ValueError(f"chunk_id 重复: {chunk_id}")
            seen.add(chunk_id)
            tokens = tokenize(text)
            doc_idx = len(index._doc_ids)
            index._doc_ids.append((chunk_id, source_id))
            index._doc_len.append(len(tokens))
            total_len += len(tokens)
            counts: dict[str, int] = {}
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1
            for term, tf in counts.items():
                index._postings.setdefault(term, []).append((doc_idx, tf))
        if index._doc_ids:
            index._avgdl = total_len / len(index._doc_ids)
        return index

    @classmethod
    def from_store(
        cls,
        store: EvidenceStore,
        source_id: str | None = None,
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> "Bm25Index":
        """直接为证据存储中的 chunk 建索引（可限定单来源）。"""
        return cls.build(
            (
                (chunk.anchor_id, chunk.source_id, chunk.text)
                for chunk in store.iter_chunks(source_id)
            ),
            k1=k1,
            b=b,
        )

    def search(self, query: str, k: int = 20) -> list[ScoredChunk]:
        """返回前 k 名；无命中词或空库返回空列表。"""
        if k <= 0:
            return []
        n_docs = len(self._doc_ids)
        if n_docs == 0 or self._avgdl == 0:
            return []
        scores: dict[int, float] = {}
        for term in set(tokenize(query)):
            postings = self._postings.get(term)
            if not postings:
                continue
            df = len(postings)
            idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
            for doc_idx, tf in postings:
                norm = self._k1 * (
                    1.0 - self._b + self._b * self._doc_len[doc_idx] / self._avgdl
                )
                scores[doc_idx] = scores.get(doc_idx, 0.0) + idf * (
                    tf * (self._k1 + 1.0) / (tf + norm)
                )
        ordered = sorted(
            scores.items(), key=lambda item: (-item[1], self._doc_ids[item[0]][0])
        )
        return [
            ScoredChunk(
                chunk_id=self._doc_ids[doc_idx][0],
                source_id=self._doc_ids[doc_idx][1],
                score=score,
                rank=rank,
            )
            for rank, (doc_idx, score) in enumerate(ordered[:k], start=1)
        ]

    def __len__(self) -> int:
        return len(self._doc_ids)
