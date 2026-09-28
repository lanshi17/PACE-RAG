"""证据集合选择：三值适用性 × 证据角色 的联合门控（主文档 §5.2 / §5.1 第 5 步）。

把 PACE 的核心主张落成确定性算法：

1. **直接支持仅限"适用∧角色匹配"**——候选须三值判为 Applicable、且其证据角色
   命中查询所需角色（并可选回指来源锚点），才可承担直接支持角色（§5.2）；
2. **Unknown 永不丢弃**——只降级到 ``applicability_unknown`` 桶，不得删除；
3. **Inapplicable 不删除**——保留在 ``comparative`` 桶，作真实分歧/版本比较材料
   （§5.1 第 5 步"分歧材料不会因为影响答案简洁而被删除"），不承担直接支持；
4. **被替代版本不得承担直接支持**——当提供 ``supersession`` 版本图时，来源已被
   更新版本替代（SUPERSEDES）的候选降级到 ``comparative``（版本比较材料），
   即使其适用性为 Applicable 且角色匹配；给出 ``as_of_year`` 时按该时点判定
   （尚未发布的新版不算替代，未生效或已失效的来源同样降级）；
   ``Unknown`` 仍优先入 ``applicability_unknown``（"Unknown 永不丢"高于版本降级）；
5. 确定性、预算 ``budget`` 封顶；同输入恒同输出，无 LLM、无网络、不依赖 benchmark.*。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from prenatal_rag.applicability import Applicability
from prenatal_rag.evidence.supersession import SupersessionGraph


class EvidenceRole(str, Enum):
    """证据角色（§5.2 的必需证据角色；由经核验的任务模板定义）。"""

    GUIDELINE = "guideline"  # 指南条款/建议，需原文支持
    OBSERVATION = "observation"  # 视觉/测量观察，需原图/区域或经评估的观察模型
    BACKGROUND = "background"  # 补充背景，不需承担直接支持


class EvidenceBucket(str, Enum):
    """输出桶（§5.1 第 5 步的四种输出）。"""

    PRIMARY_SUPPORT = "primary_support"  # 可直接支持
    BACKGROUND = "background"  # 补充背景
    APPLICABILITY_UNKNOWN = "applicability_unknown"  # 三值 Unknown，不得承担直接支持
    COMPARATIVE = "comparative"  # 真实分歧/版本比较（Inapplicable 亦不删除）


@dataclass(frozen=True)
class EvidenceCandidate:
    """一个待判证据候选。"""

    id: str
    verdict: Applicability
    roles: frozenset[EvidenceRole] = frozenset()
    source_anchor: bool = True  # 是否可回指原始描述/锚点
    source_id: str = ""  # 证据来源（用于版本替代 SUPERSEDES 门控）


@dataclass
class SelectedEvidence:
    """选择结果：按桶分组，恒保序、确定性。"""

    primary_support: list[str] = field(default_factory=list)
    background: list[str] = field(default_factory=list)
    applicability_unknown: list[str] = field(default_factory=list)
    comparative: list[str] = field(default_factory=list)

    def iter_buckets(self) -> list[tuple[EvidenceBucket, list[str]]]:
        return [
            (EvidenceBucket.PRIMARY_SUPPORT, self.primary_support),
            (EvidenceBucket.BACKGROUND, self.background),
            (EvidenceBucket.APPLICABILITY_UNKNOWN, self.applicability_unknown),
            (EvidenceBucket.COMPARATIVE, self.comparative),
        ]


def select_evidence(
    candidates: list[EvidenceCandidate],
    *,
    required_roles: frozenset[EvidenceRole],
    budget: int | None = None,
    require_source_anchor: bool = True,
    supersession: SupersessionGraph | None = None,
    as_of_year: int | None = None,
) -> SelectedEvidence:
    """按三值适用性×角色把候选分桶；确定性（按输入顺序入桶）。

    Parameters
    ----------
    candidates : 已按 RRF/精排排序的候选（同序入桶，保证可复现）。
    required_roles : 查询必需证据角色。
    budget : 选择总条数上限；``None`` 视为不限。
    require_source_anchor : 直接支持是否要求来源锚点回指。
    supersession : 指南版本替代图；提供时，已被替代来源的候选降级到
        ``comparative``（版本比较材料），不得承担直接支持。
    as_of_year : 查询的"截至年份"；提供时版本门控按该时点判定——晚于该年
        才发布的新版不算已替代，未生效（尚未出版）或已失效（``valid_until``）
        的来源同样降级。``None`` 表示按结构层（忽略时点）判定。

    Returns
    -------
    分好桶的 SelectedEvidence。
    """
    if budget is not None and budget <= 0:
        return SelectedEvidence()
    selected = SelectedEvidence()
    for candidate in candidates:
        if budget is not None and _total(selected) >= budget:
            break
        bucket = _bucket_for(
            candidate,
            required_roles=required_roles,
            require_source_anchor=require_source_anchor,
            supersession=supersession,
            as_of_year=as_of_year,
        )
        _append(selected, bucket, candidate.id)
    return selected


def _temporally_blocked(
    supersession: SupersessionGraph, source_id: str, as_of_year: int
) -> bool:
    """``as_of_year`` 时点该来源是否不得承担直接支持（未生效或已被替代）。"""
    if not supersession.is_effective_at(source_id, as_of_year):
        return True
    return supersession.is_superseded_at(source_id, as_of_year)


def _bucket_for(
    candidate: EvidenceCandidate,
    *,
    required_roles: frozenset[EvidenceRole],
    require_source_anchor: bool,
    supersession: SupersessionGraph | None = None,
    as_of_year: int | None = None,
) -> EvidenceBucket:
    if candidate.verdict is Applicability.INAPPLICABLE:
        return EvidenceBucket.COMPARATIVE
    if candidate.verdict is Applicability.UNKNOWN:
        return EvidenceBucket.APPLICABILITY_UNKNOWN
    # Applicable：被替代版本不得承担直接支持，降级为版本比较材料。
    if supersession is not None and candidate.source_id:
        blocked = (
            supersession.is_superseded(candidate.source_id)
            if as_of_year is None
            else _temporally_blocked(supersession, candidate.source_id, as_of_year)
        )
        if blocked:
            return EvidenceBucket.COMPARATIVE
    role_match = bool(candidate.roles & required_roles)
    anchored = candidate.source_anchor or not require_source_anchor
    if role_match and anchored:
        return EvidenceBucket.PRIMARY_SUPPORT
    return EvidenceBucket.BACKGROUND


def _total(selected: SelectedEvidence) -> int:
    return sum(len(ids) for _, ids in selected.iter_buckets())


def _append(selected: SelectedEvidence, bucket: EvidenceBucket, id_: str) -> None:
    if bucket is EvidenceBucket.PRIMARY_SUPPORT:
        selected.primary_support.append(id_)
    elif bucket is EvidenceBucket.BACKGROUND:
        selected.background.append(id_)
    elif bucket is EvidenceBucket.APPLICABILITY_UNKNOWN:
        selected.applicability_unknown.append(id_)
    else:
        selected.comparative.append(id_)


__all__ = [
    "Applicability",
    "EvidenceBucket",
    "EvidenceCandidate",
    "EvidenceRole",
    "SelectedEvidence",
    "SupersessionGraph",
    "select_evidence",
]