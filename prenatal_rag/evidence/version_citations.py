"""生成端版本一致性核验：答案是否"引了旧版却漏了当前版本"。

PACE §7 版本时态的第三层。检索与选择层已保证被替代版本不承担直接支持
（批次八结构层、批次九时点层），但生成模型仍可能在答案正文里引用旧版编号。
本模块把该检查落成确定性函数（无 LLM、无网络）：

- 解析答案中的 ``[E{i}]`` 引用标记（与提示词 ``[E1]..[En]`` 约定一致），
  按 1-based 下标映射回上下文记录，得到被引来源；
- 若某被引来源已被替代，而其**当前版本也在候选上下文内**却未被引用，
  记为 ``missing_current``——陈旧引用；
- 若当前版本根本不在候选上下文内，则不计为模型过失，单列
  ``unavailable_current``（当前版本不可得，模型无从引用）。

状态：

- ``CONSISTENT``：未引旧版，或旧版与当前版并引（版本比较是允许用法）；
- ``STALE_ONLY``：引了旧版且漏引可得当前版；
- ``CURRENT_UNAVAILABLE``：引了旧版但当前版不在候选集内；
- ``NO_CITATIONS``：答案未引用任何证据编号。

给出 ``as_of_year`` 时按该时点判定"当前版本"（批次九的时点语义）。
本模块只做判定；来源、替代图与上下文由调用方注入，``prenatal_rag`` 不依赖
``benchmark.*``。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from prenatal_rag.evidence.supersession import SupersessionGraph

_CITATION_RE = re.compile(r"\[E(\d+)\]")


class VersionCitationStatus(str, Enum):
    """答案版本引用的核验结论。"""

    CONSISTENT = "consistent"
    STALE_ONLY = "stale_only"
    CURRENT_UNAVAILABLE = "current_unavailable"
    NO_CITATIONS = "no_citations"


@dataclass(frozen=True)
class VersionCitationReport:
    """单条答案的版本引用核验结果（确定性）。"""

    cited_sources: tuple[str, ...]
    superseded_cited: tuple[str, ...]
    current_cited: tuple[str, ...]
    missing_current: tuple[str, ...]
    unavailable_current: tuple[str, ...]
    status: VersionCitationStatus

    @property
    def is_consistent(self) -> bool:
        """答案是否未陈旧引用（``STALE_ONLY`` 才算失败）。"""
        return self.status is not VersionCitationStatus.STALE_ONLY


def _cited_indices(answer: str) -> list[int]:
    """按出现顺序返回答案中不重复的 ``[E{i}]`` 下标。"""
    seen: set[int] = set()
    out: list[int] = []
    for match in _CITATION_RE.finditer(answer):
        index = int(match.group(1))
        if index not in seen:
            seen.add(index)
            out.append(index)
    return out


def _dedup(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def verify_version_citations(
    answer: str,
    contexts: Sequence[Mapping[str, object]],
    supersession: SupersessionGraph,
    *,
    as_of_year: int | None = None,
) -> VersionCitationReport:
    """核验 ``answer`` 对 ``contexts`` 的版本引用一致性。

    Parameters
    ----------
    answer : 生成答案正文（含 ``[E1]..[En]`` 引用标记）。
    contexts : 与提示词顺序一致的上下文记录（含 ``source_id``）。
    supersession : 版本替代图（含可选时间轴）。
    as_of_year : 按该时点判定当前版本；``None`` 用结构层最新版本。
    """
    cited_sources: list[str] = []
    for index in _cited_indices(answer):
        if 1 <= index <= len(contexts):
            source_id = str(contexts[index - 1].get("source_id") or "")
            if source_id:
                cited_sources.append(source_id)
    cited_sources = list(dict.fromkeys(cited_sources))
    context_sources = {str(item.get("source_id") or "") for item in contexts}
    cite_set = set(cited_sources)

    superseded_cited: list[str] = []
    current_cited: list[str] = []
    missing_current: list[str] = []
    unavailable_current: list[str] = []
    for source_id in cited_sources:
        if as_of_year is None:
            superseded = supersession.is_superseded(source_id)
            current = supersession.current_version(source_id)
        else:
            superseded = supersession.is_superseded_at(source_id, as_of_year)
            current = supersession.current_version_at(source_id, as_of_year)
        if not superseded:
            continue
        superseded_cited.append(source_id)
        if current in cite_set:
            current_cited.append(current)
        elif current in context_sources:
            missing_current.append(current)
        else:
            unavailable_current.append(current)

    if not cited_sources:
        status = VersionCitationStatus.NO_CITATIONS
    elif missing_current:
        status = VersionCitationStatus.STALE_ONLY
    elif unavailable_current:
        status = VersionCitationStatus.CURRENT_UNAVAILABLE
    else:
        status = VersionCitationStatus.CONSISTENT

    return VersionCitationReport(
        cited_sources=tuple(cited_sources),
        superseded_cited=_dedup(superseded_cited),
        current_cited=_dedup(current_cited),
        missing_current=_dedup(missing_current),
        unavailable_current=_dedup(unavailable_current),
        status=status,
    )


__all__ = [
    "VersionCitationReport",
    "VersionCitationStatus",
    "verify_version_citations",
]
