"""并行召回编排（主文档 §5.1 第 2 步的装配层）。

把 §5.1 的"并行召回 → RRF 合并"固化为可测 API：

- :class:`GraphChannel`：图通道适配器——给定真值层种子锚点，经
  :class:`~prenatal_rag.retrieval.bridge.OverlapBridge` 映到投影 chunk 键、
  由 :class:`~prenatal_rag.retrieval.graph.LightRagChunkGraph` 加权扩展，
  再映回锚点空间，产出锚点排名；
- :class:`EmbeddingChannel`：向量通道适配器——查询向量经
  :class:`~prenatal_rag.retrieval.vectors.VectorIndex` 在投影 chunk 上排序，
  再经同一个桥映回锚点空间（第三路召回，批次十一）；
- :func:`condition_seed_anchors`：从查询条件三值分类里取"非明确不适用"
  的锚点作种子（空查询返回全量）；
- :func:`parallel_recall`：把 BM25、图通道、（可选）向量通道的锚点排名
  交给 RRF 合并并截断。禁止把不同通道的分数直接相加——只合并顺序
  （见 rrf 模块文档）。
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass

from prenatal_rag.applicability import Applicability
from prenatal_rag.conditions.filter import QueryConditions, classify
from prenatal_rag.evidence_store.store import EvidenceStore
from prenatal_rag.retrieval.bridge import OverlapBridge
from prenatal_rag.retrieval.graph import LightRagChunkGraph
from prenatal_rag.retrieval.rrf import reciprocal_rank_fusion, top_k
from prenatal_rag.retrieval.vectors import VectorIndex


@dataclass(frozen=True)
class GraphChannel:
    """图通道：种子锚点 -> 投影图扩展 -> 锚点排名（确定性）。"""

    graph: LightRagChunkGraph
    bridge: OverlapBridge
    hops: int = 2
    k_expand: int = 20

    def rank(self, seed_anchors: Iterable[int], *, k: int | None = None) -> list[int]:
        """由种子锚点返回图通道锚点排名。

        种子按给定顺序经 ``anchor_to_chunks`` 收集（跨种子去重），
        图扩展出的每个 chunk 键只保留首次（最高图排名）出现的锚点；
        无映射的 chunk 键跳过。``k`` 为 None 时返回全部扩展结果；
        ``k <= 0`` 返回空列表（与 ``top_k`` 语义一致）。
        """
        if k is not None and k <= 0:
            return []
        seed_keys: list[str] = []
        seen_keys: set[str] = set()
        for anchor_id in seed_anchors:
            for chunk_key in self.bridge.anchor_to_chunks(anchor_id):
                if chunk_key not in seen_keys:
                    seen_keys.add(chunk_key)
                    seed_keys.append(chunk_key)
        expanded = self.graph.expand(seed_keys, hops=self.hops, k=self.k_expand)
        ranking: list[int] = []
        seen_anchors: set[int] = set()
        for chunk_key in expanded:
            anchor_id = self.bridge.chunk_to_anchor(chunk_key)
            if anchor_id is None or anchor_id in seen_anchors:
                continue
            seen_anchors.add(anchor_id)
            ranking.append(anchor_id)
            if k is not None and len(ranking) >= k:
                break
        return ranking


@dataclass(frozen=True)
class EmbeddingChannel:
    """向量通道：查询向量 -> 投影 chunk 排名 -> 锚点排名（确定性）。

    与 :class:`GraphChannel` 共用同一个 :class:`OverlapBridge`：向量只在
    投影 chunk 空间排序，回映到真值层锚点后才有候选；无映射的 chunk 键
    跳过，同一锚点只保留首次（向量排名最高）出现。
    """

    index: VectorIndex
    bridge: OverlapBridge

    def rank(
        self, query_vector: Sequence[float], *, k: int | None = None
    ) -> list[int]:
        """由查询向量返回向量通道锚点排名。

        ``k`` 为 None 时返回全部回映结果；``k <= 0`` 返回空列表。向量维度
        与索引不符时由 :meth:`VectorIndex.rank` 抛 ``ValueError``。
        """
        if k is not None and k <= 0:
            return []
        ranking: list[int] = []
        seen_anchors: set[int] = set()
        for chunk_key in self.index.rank(query_vector):
            anchor_id = self.bridge.chunk_to_anchor(chunk_key)
            if anchor_id is None or anchor_id in seen_anchors:
                continue
            seen_anchors.add(anchor_id)
            ranking.append(anchor_id)
            if k is not None and len(ranking) >= k:
                break
        return ranking


def condition_seed_anchors(store: EvidenceStore, query: QueryConditions) -> list[int]:
    """返回"非明确不适用"的真值层锚点作条件种子（确定性、按 anchor_id）。

    复用三值分类：Unknown 与 Applicable 均可作图扩展种子（Unknown 不得
    被剔除的语义在这里同样成立）；空查询时全量锚点都可作种子。
    """
    seeds: list[int] = []
    for chunk in store.iter_chunks():
        conds = store.conditions_for(chunk.anchor_id)
        if classify(conds, query) is not Applicability.INAPPLICABLE:
            seeds.append(chunk.anchor_id)
    return seeds


def parallel_recall(
    bm25_ranking: Sequence[Hashable],
    graph_ranking: Sequence[Hashable],
    *,
    k: int,
    embedding_ranking: Sequence[Hashable] | None = None,
) -> list[Hashable]:
    """把 BM25、图通道、（可选）向量通道排名用 RRF 合并并截断到前 k 名。

    任一通道可为空（RRF 天然兼容）；``embedding_ranking`` 为 None 时退化为
    批次六的两通道语义（向后兼容）；``k <= 0`` 返回空列表。
    """
    rankings = [list(bm25_ranking), list(graph_ranking)]
    if embedding_ranking is not None:
        rankings.append(list(embedding_ranking))
    return top_k(reciprocal_rank_fusion(rankings), k)


__all__ = [
    "EmbeddingChannel",
    "GraphChannel",
    "condition_seed_anchors",
    "parallel_recall",
]
