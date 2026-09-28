"""递归排名融合 RRF（主文档 §5.1 第 2 步的上层合并）。

并行召回的各通道（BM25 / embedding / 图）各自输出**排名**，在未知绝对尺度下
用倒数排名加权合并候选；禁止把不同模型未校准的相似度直接相加。
RRF 只消费顺序，故可与任选通道（甚至不同 token 预算、不同 embedding boot）对接。

公式（Cornack et al. 2009）：``score(item) = Σ_通道 1/(k + rank)``，
常数 ``k=60``。结果按 score 降序；平分按 ``str(item)`` 升序保证确定性。
服从主文档"所有 top-k/跳数/token 上限为开发集调优超参数"的约定。
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Sequence

RANKING_K = 60

Score = int | float


def reciprocal_rank_fusion(
    rankings: Sequence[Iterable[Hashable]],
    *,
    k: int = RANKING_K,
) -> list[Hashable]:
    """把多条排名合并为单一有序候选列表（去重、确定性）。

    Parameters
    ----------
    rankings : 每个通道输出一个有序可迭代（rank1 在前）。
    k : RRF 平滑常数（默认 60）。

    Raises
    ------
    ValueError : ``k <= 0``。
    """
    if k <= 0:
        raise ValueError(f"RRF 常数 k 必须为正，实际 {k}")
    scores: dict[Hashable, Score] = {}
    for channel in rankings:
        seen: set[Hashable] = set()
        for rank, item in enumerate(channel, start=1):
            if item in seen:
                continue  # 同一通道内重复条目只计最高排名处一次。
            seen.add(item)
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda item: (-scores[item], str(item)))


def top_k(merged: Sequence[Hashable], n: int) -> list[Hashable]:
    """截断到前 n 名；``n <= 0`` 返回空列表（不抛错，适配 k=0 语义）。"""
    if n <= 0:
        return []
    return list(merged[:n])


__all__ = ["RANKING_K", "reciprocal_rank_fusion", "top_k"]