"""SUPERSEDES 版本图加载：注册表（superseded_by）+ 真值层 DOI 关联。

指南注册表 ``GUIDELINE_REGISTRY`` 的键名与语料 ``source_documents.source_id``
并不一致，但两者都携带 **DOI**（语料侧存在 ``family_id``）。本模块以 DOI 为桥：

    registry[old_key].doi  →  source_id(old)
    registry[old_key].superseded_by = new_key
    registry[new_key].doi  →  source_id(new)

解析出 ``source_id(old) -> source_id(new)`` 的边交给 ``SupersessionGraph``。
无法解析（缺 DOI / 该 DOI 不在语料 / 旧式别名）的条目被跳过——图只含可验证边。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from benchmark.qa.schema import GUIDELINE_REGISTRY
from prenatal_rag.evidence import SupersessionGraph, verify_version_citations
from prenatal_rag.evidence_store import EvidenceStore


def load_supersession_graph(store: EvidenceStore) -> SupersessionGraph:
    """从注册表 + 证据真值层构建 ``source_id -> source_id`` 替代图与时间轴。

    结构边：``registry[old].superseded_by`` 经 DOI 映射到语料 ``source_id``。
    时间轴：出版年取注册表 ``year``；失效年取 ``valid_until``（当前全部未设置，
    故时间轴实际由"后继版本的出版年"驱动）。
    """
    source_by_doi = {doc.family_id: doc.source_id for doc in store.documents()}

    edges: dict[str, str] = {}
    years: dict[str, int] = {}
    valid_until: dict[str, int] = {}
    for _key, meta in GUIDELINE_REGISTRY.items():
        doi = meta.get("doi")
        source = source_by_doi.get(doi) if doi else None
        if source:
            year = meta.get("year")
            if isinstance(year, int):
                years[source] = year
            until = meta.get("valid_until")
            if isinstance(until, int):
                valid_until[source] = until
        newer_key = meta.get("superseded_by")
        if not newer_key or not doi:
            continue
        newer_doi = GUIDELINE_REGISTRY.get(newer_key, {}).get("doi")
        if not newer_doi:
            continue
        older_source = source_by_doi.get(doi)
        newer_source = source_by_doi.get(newer_doi)
        if not older_source or not newer_source:
            continue
        edges[older_source] = newer_source
    return SupersessionGraph(edges, years=years, valid_until=valid_until)


__all__ = ["build_version_checker", "load_supersession_graph"]


def build_version_checker(
    store: EvidenceStore,
) -> Callable[[str, list[dict[str, str]]], dict[str, Any]]:
    """构造生成端版本核验器 ``(answer, contexts) -> 结论字典``。

    供 B1 端到端评估逐题调用：检查答案是否引用了被替代版本却漏引可得当前版本。
    """
    graph = load_supersession_graph(store)

    def check(answer: str, contexts: list[dict[str, str]]) -> dict[str, Any]:
        report = verify_version_citations(answer, contexts, graph)
        return {
            "status": report.status.value,
            "cited_sources": list(report.cited_sources),
            "superseded_cited": list(report.superseded_cited),
            "missing_current": list(report.missing_current),
            "unavailable_current": list(report.unavailable_current),
        }

    return check
