"""S 对照变体实现：metadata filter 与 MMR（预注册 pace-research-plan.md §6.2）。

S 冻结流程：先在开发集（62 题）离线比较各 S 候选的检索指标，选定一个配置，
再运行生成。本模块只做**检索层选取**（零 LLM），生成复用四臂管线的同一 prompt。

变体：
- ``S_metadata``：metadata filter —— 三值过滤（与前置过滤同语义）+ 普通 top-k。
  对应"用 LightRAG metadata 过滤就能解决"的简单假设。
- ``S_mmr``：MMR —— λ 加权的 relevance/diversity 平衡，无三值过滤、无来源限额。
  对应"多样性重排就能解决"的简单假设。
- ``S_both``：metadata filter + MMR。
"""

from __future__ import annotations

from typing import Any


def metadata_filter(
    scored_rows: list[dict[str, Any]],
    inapplicable: set[int],
) -> list[dict[str, Any]]:
    """三值过滤（仅剔除明确 Inapplicable；Unknown 保留）。"""

    return [row for row in scored_rows if row["anchor_id"] not in inapplicable]


def mmr_select(
    scored_rows: list[dict[str, Any]],
    embeddings: dict[int, list[float]],
    *,
    k: int,
    lambda_mult: float = 0.7,
) -> list[dict[str, Any]]:
    """MMR 选取：λ×相关性 − (1−λ)×与已选集的最大相似度。

    ``scored_rows`` 按相关性降序；``embeddings`` 提供 anchor -> 归一化向量。
    缺向量的候选按相关性 0 处理（仍可选，但不参与多样性项）。
    """

    def _cos(a: list[float], b: list[float]) -> float:
        num = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        return num / (na * nb) if na and nb else 0.0

    remaining = list(scored_rows)
    picked: list[dict[str, Any]] = []
    picked_vecs: list[list[float]] = []
    while remaining and len(picked) < k:
        best_row, best_score = None, float("-inf")
        for row in remaining:
            rel = 1.0 / (row.get("retrieval_rank", len(picked) + 1))
            vec = embeddings.get(row["anchor_id"])
            max_sim = (
                max((_cos(vec, pv) for pv in picked_vecs), default=0.0)
                if vec
                else 0.0
            )
            score = lambda_mult * rel - (1 - lambda_mult) * max_sim
            if score > best_score or best_row is None:
                best_row, best_score = row, score
        if best_row is None:
            break
        picked.append(best_row)
        vec = embeddings.get(best_row["anchor_id"])
        if vec:
            picked_vecs.append(vec)
        remaining.remove(best_row)
    return picked
