"""Manual mutation gauntlet for prenatal_rag.conditions (Tier 2/3).

No mutmut in the environment, so the old-coder manual-mutation procedure is
persisted here so the EVIDENCE numbers are reproducible from the repo alone.

Each mutant is one plausible real bug injected as a literal source edit. The
invariant: the conditions test suite must kill every mutant (a nonzero pytest
exit). The runner is fail-closed:

- if the expected ``old`` snippet is missing or matches != exactly once, the
  layer fails (a silent skip would be a pass);
- the file is restored from backup after each run and verified again;
- a survivor (mutant running green) makes the layer exit nonzero.

Usage (from repo root):
    PYTHONPATH=. .venv/bin/python benchmark/report/manual_mutation_prenatal.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE = "tests/test_prenatal_conditions.py"

_SCHEMA = REPO_ROOT / "prenatal_rag/conditions/schema.py"
_EXTRACT = REPO_ROOT / "prenatal_rag/conditions/extract.py"
_FILTER = REPO_ROOT / "prenatal_rag/conditions/filter.py"
_QUERY = REPO_ROOT / "prenatal_rag/conditions/query.py"
_RRF = REPO_ROOT / "prenatal_rag/retrieval/rrf.py"
_EVID = REPO_ROOT / "prenatal_rag/evidence/selection.py"
_EVID_SUITE = "tests/test_prenatal_evidence.py"
_GRAPH = REPO_ROOT / "prenatal_rag/retrieval/graph.py"
_BRIDGE = REPO_ROOT / "prenatal_rag/retrieval/bridge.py"
_PIPE = REPO_ROOT / "prenatal_rag/retrieval/pipeline.py"
_GRAPH_SUITE = "tests/test_prenatal_graph.py"
_BRIDGE_SUITE = "tests/test_prenatal_bridge.py"
_PIPE_SUITE = "tests/test_prenatal_pipeline.py"
_SUPER = REPO_ROOT / "prenatal_rag/evidence/supersession.py"
_SUPER_SUITE = "tests/test_prenatal_supersession.py"
_VC = REPO_ROOT / "prenatal_rag/evidence/version_citations.py"
_VC_SUITE = "tests/test_prenatal_version_citations.py"
_VEC = REPO_ROOT / "prenatal_rag/retrieval/vectors.py"
_VEC_SUITE = "tests/test_prenatal_vectors.py"

MUTANTS: list[dict[str, object]] = [
    {
        "file": _SCHEMA,
        "old": (
            "        if self.upper_days is not None:\n"
            "            if other.upper_days is None or other.upper_days > self.upper_days:"
        ),
        "new": (
            "        if self.upper_days is not None:\n"
            "            if other.upper_days is not None and other.upper_days > self.upper_days:"
        ),
        "why": "GaWindow.covers 误覆盖无界上界查询（有限窗口认为覆盖 ≥N 的查询）",
        "expected_kill": "TestGaWindowProperties.test_covers_implies_overlaps",
    },
    {
        "file": _FILTER,
        "old": (
            "    if evidence.covers(query):\n"
            "        return Applicability.APPLICABLE"
        ),
        "new": (
            "    if query.covers(evidence):\n"
            "        return Applicability.APPLICABLE"
        ),
        "why": "_window_direction 反向调用 covers（覆盖方向颠倒）",
        "expected_kill": "TestClassify.test_ga_applicable",
    },
    {
        "file": _EXTRACT,
        "old": "    days = int(groups[\"a\"]) * 7",
        "new": "    days = int(groups[\"a\"]) * 6",
        "why": "_day_component 周→天换算系数 7→6（全部 at_least/at_most 偏移）",
        "expected_kill": "TestExtractionGA",
    },
    {
        "file": _EXTRACT,
        "old": (
            "    if window.lower_days is not None and window.lower_days < _GUARD_DAYS:\n"
            "        return False"
        ),
        "new": (
            "    if window.lower_days is not None and window.lower_days < _GUARD_DAYS:\n"
            "        pass"
        ),
        "why": "合理性守卫下限停用（early 起始窗口不被剔除）",
        "expected_kill": "TestExtractionGA.test_lower_guard_rejects_early_start",
    },
    {
        "file": _FILTER,
        "old": (
            "                if p in POPULATION_OPPOSITES.get(q, ()):\n"
            "                    return Applicability.INAPPLICABLE"
        ),
        "new": (
            "                if p in POPULATION_OPPOSITES.get(q, ()):\n"
            "                    return Applicability.UNKNOWN"
        ),
        "why": "人群正对不再判 Inapplicable（单胎 vs 双胎不剔除）",
        "expected_kill": "TestClassify.test_population_opposite_inapplicable",
    },
    {
        "file": _QUERY,
        "old": '    ga = windows[0] if windows else None',
        "new": '    ga = windows[-1] if windows else None',
        "why": "查询孕周取末尾窗口（首个窗口选择规则失效）",
        "expected_kill": "TestQueryConditionsParse.test_query_takes_first_window",
    },
    {
        "file": _QUERY,
        "old": (
            "def _is_constraint_technique(value: str) -> bool:\n"
            "    return value in _CONSTRAINT_TECHNIQUES"
        ),
        "new": (
            "def _is_constraint_technique(value: str) -> bool:\n"
            "    return True"
        ),
        "why": "技术约束筛选失效（four-chamber 等答案主题也被当查询条件）",
        "expected_kill": "TestQueryConditionsParse.test_technique_conservative",
    },
    {
        "file": _RRF,
        "old": (
            "            if item in seen:\n"
            "                continue  # 同一通道内重复条目只计最高排名处一次。"
        ),
        "new": (
            "            if item in seen:\n"
            "                pass  # 变异：重复条目仍累计分数"
        ),
        "why": "RRF 去重失效（通道内重复条目被重复计分）",
        "expected_kill": "test_duplicate_within_channel_counts_once",
        "suite": "tests/test_prenatal_rrf.py",
    },
    {
        "file": _RRF,
        "old": "sorted(scores, key=lambda item: (-scores[item], str(item)))",
        "new": "sorted(scores, key=lambda item: (scores[item], str(item)))",
        "why": "RRF 排序方向颠倒（分数升序）",
        "expected_kill": "test_shared_item_ranks_higher",
        "suite": "tests/test_prenatal_rrf.py",
    },
    {
        "file": _RRF,
        "old": "    if k <= 0:",
        "new": "    if k < 0:",
        "why": "RRF 常数守卫失效（k=0 不再报错）",
        "expected_kill": "test_k_nonpositive_raises",
        "suite": "tests/test_prenatal_rrf.py",
    },
    {
        "file": _EVID,
        "old": (
            "    if role_match and anchored:\n"
            "        return EvidenceBucket.PRIMARY_SUPPORT"
        ),
        "new": (
            "    if anchored:\n"
            "        return EvidenceBucket.PRIMARY_SUPPORT"
        ),
        "why": "证据直接支持门控丢角色匹配（角色不符也入直接支持）",
        "expected_kill": "test_primary_support_only_applicable_role_match_anchored",
        "suite": _EVID_SUITE,
    },
    {
        "file": _EVID,
        "old": (
            "    if candidate.verdict is Applicability.UNKNOWN:\n"
            "        return EvidenceBucket.APPLICABILITY_UNKNOWN"
        ),
        "new": (
            "    if candidate.verdict is Applicability.UNKNOWN:\n"
            "        return EvidenceBucket.BACKGROUND"
        ),
        "why": "Unknown 被降级为 background 而非独立桶（UNKNOWN 不保真）",
        "expected_kill": "test_unknown_bucketed_not_dropped",
        "suite": _EVID_SUITE,
    },
    {
        "file": _EVID,
        "old": "    if candidate.verdict is Applicability.INAPPLICABLE:\n        return EvidenceBucket.COMPARATIVE",
        "new": "    if candidate.verdict is Applicability.INAPPLICABLE:\n        return EvidenceBucket.BACKGROUND",
        "why": "Inapplicable 并入 background 而非 comparative（不再保留为比较材料）",
        "expected_kill": "test_inapplicable_kept_as_comparative",
        "suite": _EVID_SUITE,
    },
    {
        "file": _GRAPH,
        "old": "    unique = sorted(set(ids))",
        "new": "    unique: list[str] = []",
        "why": "incidence 不去重成对（图通道建不出任何边）",
        "expected_kill": "TestFromIndexDir.test_builds_weighted_undirected_adjacency",
        "suite": _GRAPH_SUITE,
    },
    {
        "file": _GRAPH,
        "old": "key=lambda item: (item[1][0], -item[1][1], item[0])",
        "new": "key=lambda item: (-item[1][0], -item[1][1], item[0])",
        "why": "expand 距离主序反转（远邻居优先于近邻居）",
        "expected_kill": "test_two_hop_reachability",
        "suite": _GRAPH_SUITE,
    },
    {
        "file": _GRAPH,
        "old": "        include_seeds: bool = False,",
        "new": "        include_seeds: bool = True,",
        "why": "include_seeds 默认误开（种子泄漏进图通道，RRF 重复计分）",
        "expected_kill": "test_seeds_excluded_by_default",
        "suite": _GRAPH_SUITE,
    },
    {
        "file": _BRIDGE,
        "old": (
            "                if (\n"
            "                    best_anchor is None\n"
            "                    or jaccard > best_jaccard\n"
            "                    or (jaccard == best_jaccard and chunk.anchor_id < best_anchor)\n"
            "                ):"
        ),
        "new": (
            "                if (\n"
            "                    best_anchor is None\n"
            "                    or (jaccard == best_jaccard and chunk.anchor_id < best_anchor)\n"
            "                ):"
        ),
        "why": "取首个重叠锚点而非最大重叠（best 不再随更高 Jaccard 回退）",
        "expected_kill": "test_partial_overlap_maps_to_best_not_first",
        "suite": _BRIDGE_SUITE,
    },
    {
        "file": _BRIDGE,
        "old": "            if best_anchor is not None and best_jaccard >= min_jaccard:",
        "new": "            if best_anchor is not None and best_jaccard > min_jaccard:",
        "why": "阈值含等号改严格大于（恰等于阈值者被误剔）",
        "expected_kill": "test_min_jaccard_boundary_at_exactly_threshold",
        "suite": _BRIDGE_SUITE,
    },
    {
        "file": _PIPE,
        "old": "    rankings = [list(bm25_ranking), list(graph_ranking)]",
        "new": "    rankings = [list(bm25_ranking)]",
        "why": "parallel_recall 丢弃图通道排名（RRF 只并 BM25）",
        "expected_kill": "test_rrf_merge_ordering",
        "suite": _PIPE_SUITE,
    },
    {
        "file": _PIPE,
        "old": (
            "        for chunk_key in expanded:\n"
            "            anchor_id = self.bridge.chunk_to_anchor(chunk_key)\n"
            "            if anchor_id is None or anchor_id in seen_anchors:"
        ),
        "new": (
            "        for chunk_key in expanded:\n"
            "            anchor_id = self.bridge.chunk_to_anchor(chunk_key)\n"
            "            if anchor_id is None:"
        ),
        "why": "图通道锚点不去重（重复锚点保留多份）",
        "expected_kill": "test_duplicate_anchor_deduplicated_keep_first",
        "suite": _PIPE_SUITE,
    },
    {
        "file": _PIPE,
        "old": "        if classify(conds, query) is not Applicability.INAPPLICABLE:",
        "new": "        if classify(conds, query) is not None:",
        "why": "条件种子把明确 Inapplicable 的锚点也计入",
        "expected_kill": "test_population_opposite_is_inapplicable_and_excluded",
        "suite": _PIPE_SUITE,
    },
    {
        "file": _SUPER,
        "old": '                    raise ValueError(f"检测到替代环，起点 {start!r}")',
        "new": "                    break",
        "why": "替代环检测失效（环图被静默接受）",
        "expected_kill": "TestGraph.test_two_node_cycle_rejected",
        "suite": _SUPER_SUITE,
    },
    {
        "file": _SUPER,
        "old": '                raise ValueError(f"自环：{older!r} 被自身替代")',
        "new": "                pass",
        "why": "自环校验失效（older == newer 被接受）",
        "expected_kill": "TestGraph.test_self_edge_rejected",
        "suite": _SUPER_SUITE,
    },
    {
        "file": _SUPER,
        "old": "        return self.chain(source_id)[-1]",
        "new": "        return self.chain(source_id)[0]",
        "why": "current_version 返回链首（最旧）而非最新",
        "expected_kill": "TestGraph.test_transitive_chain",
        "suite": _SUPER_SUITE,
    },
    {
        "file": _SUPER,
        "old": "        return len(self.chain(source_id)) - 1",
        "new": "        return len(self.chain(source_id))",
        "why": "depth_to_current 差一（当前版本深度记为 1）",
        "expected_kill": "TestGraph.test_single_edge",
        "suite": _SUPER_SUITE,
    },
    {
        "file": _SUPER,
        "old": (
            "        node = self._edges.get(source_id)\n"
            "        while node is not None:"
        ),
        "new": (
            "        node = self._edges.get(source_id)\n"
            "        if node is not None:"
        ),
        "why": "chain 只走一跳（非传递，2005 看不到 2023）",
        "expected_kill": "TestGraph.test_transitive_chain",
        "suite": _SUPER_SUITE,
    },
    {
        "file": _EVID,
        "old": "            if as_of_year is None",
        "new": "            if True",
        "why": "版本门控忽略 as-of 时点（恒用结构层替代）",
        "expected_kill": "TestSelectionAsOf.test_as_of_2016_selects_2013",
        "suite": _SUPER_SUITE,
    },
    {
        "file": _EVID,
        "old": "            supersession.is_superseded(candidate.source_id)",
        "new": "            False",
        "why": "结构层版本降级失效（被替代版本仍承担直接支持）",
        "expected_kill": "TestSelectionSupersession.test_superseded_demoted_to_comparative",
        "suite": _SUPER_SUITE,
    },
    {
        "file": _EVID,
        "old": "    return supersession.is_superseded_at(source_id, as_of_year)",
        "new": "    return False",
        "why": "时点替代判定失效（旧版在 as-of 下仍承担直接支持）",
        "expected_kill": "TestSelectionAsOf.test_as_of_2016_selects_2013",
        "suite": _SUPER_SUITE,
    },
    {
        "file": _EVID,
        "old": (
            "    if candidate.verdict is Applicability.UNKNOWN:\n"
            "        return EvidenceBucket.APPLICABILITY_UNKNOWN"
        ),
        "new": (
            "    if candidate.verdict is Applicability.UNKNOWN and supersession is None:\n"
            "        return EvidenceBucket.APPLICABILITY_UNKNOWN"
        ),
        "why": "版本门控越权覆盖 Unknown（Unknown 被降级而非保留）",
        "expected_kill": "TestSelectionSupersession.test_unknown_superseded_stays_unknown",
        "suite": _SUPER_SUITE,
    },
    {
        "file": _SUPER,
        "old": (
            "            if newer_year <= older_year:\n"
            "                raise ValueError(\n"
            '                    f"版本年份非递增：{older!r}({older_year}) -> {newer!r}({newer_year})"\n'
            "                )"
        ),
        "new": "            continue",
        "why": "版本年份非递增校验失效（时间轴逆序被接受）",
        "expected_kill": "TestTimeline.test_non_increasing_years_rejected",
        "suite": _SUPER_SUITE,
    },
    {
        "file": _SUPER,
        "old": (
            "        if successor_year is None:\n"
            "            return True\n"
        ),
        "new": "        if successor_year is None:\n            return False\n",
        "why": "后继年份未知时不再保守降级（旧版逃过时点门控）",
        "expected_kill": "TestTimeline.test_missing_successor_year_is_conservative",
        "suite": _SUPER_SUITE,
    },
    {
        "file": _SUPER,
        "old": "        if end is not None and year >= end:",
        "new": "        if end is not None and year > end:",
        "why": "valid_until 半开区间被写成闭区间（失效年当年仍算有效）",
        "expected_kill": "TestTimeline.test_is_effective_at_uses_year_and_valid_until",
        "suite": _SUPER_SUITE,
    },
    {
        "file": _SUPER,
        "old": "            if successor_year is not None and successor_year > year:",
        "new": "            if successor_year is not None and successor_year < year:",
        "why": "current_version_at 比较方向反转（时点当前版本判错）",
        "expected_kill": "TestTimeline.test_current_version_at_walks_timeline",
        "suite": _SUPER_SUITE,
    },
    {
        "file": _VC,
        "old": "    elif missing_current:",
        "new": "    elif False:",
        "why": "陈旧引用不再判为 STALE_ONLY（漏引当前版本被放过）",
        "expected_kill": "test_stale_only_when_current_available",
        "suite": _VC_SUITE,
    },
    {
        "file": _VC,
        "old": "        if 1 <= index <= len(contexts):",
        "new": "        if index <= len(contexts):",
        "why": "引用下标下界失效（[E0] 被当作最后一条证据）",
        "expected_kill": "test_zero_and_negative_indices_ignored",
        "suite": _VC_SUITE,
    },
    {
        "file": _VC,
        "old": "        elif current in context_sources:",
        "new": "        elif current not in context_sources:",
        "why": "缺失/不可得两类判定互换（模型过失与不可得混淆）",
        "expected_kill": "test_stale_only_when_current_available",
        "suite": _VC_SUITE,
    },
    {
        "file": _VC,
        "old": (
            "        if not superseded:\n"
            "            continue"
        ),
        "new": (
            "        if superseded:\n"
            "            continue"
        ),
        "why": "被替代判定取反（非替代来源被当作旧版统计）",
        "expected_kill": "test_cites_only_current_version",
        "suite": _VC_SUITE,
    },
    {
        "file": _VEC,
        "old": "        scored.sort(key=lambda pair: (-pair[0], pair[1]))",
        "new": "        scored.sort(key=lambda pair: (pair[0], pair[1]))",
        "why": "向量排序方向取反（相似度升序）",
        "expected_kill": "test_order_and_tie_break_by_key",
        "suite": _VEC_SUITE,
    },
    {
        "file": _VEC,
        "old": (
            "        if norm == 0.0 or query_norm == 0.0:\n"
            "            return 0.0"
        ),
        "new": (
            "        if False:\n"
            "            return 0.0"
        ),
        "why": "零范数保护失效（零向量参与除法）",
        "expected_kill": "test_zero_vector_row_is_zero",
        "suite": _VEC_SUITE,
    },
    {
        "file": _VEC,
        "old": (
            "        if norm == 0.0 or query_norm == 0.0:\n"
            "            return 0.0"
        ),
        "new": (
            "        if norm == 0.0 or query_norm == 0.0:\n"
            "            return 1.0"
        ),
        "why": "零范数余弦返回值被改为 1.0（零向量被当作完全相似）",
        "expected_kill": "test_zero_vector_row_is_zero",
        "suite": _VEC_SUITE,
    },
    {
        "file": _VEC,
        "old": "        if len(keys) != len(set(keys)):",
        "new": "        if False:",
        "why": "重复 chunk 键校验失效",
        "expected_kill": "test_duplicate_keys_rejected",
        "suite": _VEC_SUITE,
    },
    {
        "file": _VEC,
        "old": "            subset = tuple(dict.fromkeys(keys))",
        "new": "            subset = tuple(keys)",
        "why": "rank 的 keys 子集不去重（重复键重复计分）",
        "expected_kill": "test_keys_subset_restricts_and_dedups",
        "suite": _VEC_SUITE,
    },
    {
        "file": _VEC,
        "old": "        return ordered if k is None else ordered[:k]",
        "new": "        return ordered",
        "why": "rank 忽略 k（不截断）",
        "expected_kill": "test_k_truncates_prefix",
        "suite": _VEC_SUITE,
    },
    {
        "file": _VEC,
        "old": (
            "        if k is not None and k <= 0:\n"
            "            return []\n"
            "        if keys is None:"
        ),
        "new": "        if keys is None:",
        "why": "rank 删除 k<=0 保护（负 k 退化为切片 ordered[:-3]）",
        "expected_kill": "test_zero_k_returns_empty",
        "suite": _VEC_SUITE,
    },
    {
        "file": _PIPE,
        "old": (
            "        for chunk_key in self.index.rank(query_vector):\n"
            "            anchor_id = self.bridge.chunk_to_anchor(chunk_key)\n"
            "            if anchor_id is None or anchor_id in seen_anchors:"
        ),
        "new": (
            "        for chunk_key in self.index.rank(query_vector):\n"
            "            anchor_id = self.bridge.chunk_to_anchor(chunk_key)\n"
            "            if anchor_id is None:"
        ),
        "why": "向量通道锚点不去重（同一锚点保留多份）",
        "expected_kill": "test_duplicate_anchor_deduplicated_keep_first",
        "suite": _PIPE_SUITE,
    },
    {
        "file": _PIPE,
        "old": (
            "        if k is not None and k <= 0:\n"
            "            return []\n"
            "        ranking: list[int] = []"
        ),
        "new": (
            "        if k is not None and k < 0:\n"
            "            return []\n"
            "        ranking: list[int] = []"
        ),
        "why": "向量通道的 k<=0 保护放宽为 k<0（k=0 返回全量）",
        "expected_kill": "test_zero_k_returns_empty",
        "suite": _PIPE_SUITE,
    },
    {
        "file": _PIPE,
        "old": (
            "        if k is not None and k <= 0:\n"
            "            return []\n"
            "        seed_keys: list[str] = []"
        ),
        "new": (
            "        if k is not None and k < 0:\n"
            "            return []\n"
            "        seed_keys: list[str] = []"
        ),
        "why": "图通道的 k<=0 保护放宽为 k<0（k=0 返回首个扩展锚点）",
        "expected_kill": "test_zero_k_returns_empty",
        "suite": _PIPE_SUITE,
    },
    {
        "file": _PIPE,
        "old": (
            "    if embedding_ranking is not None:\n"
            "        rankings.append(list(embedding_ranking))"
        ),
        "new": (
            "    if embedding_ranking is None:\n"
            "        rankings.append(list(embedding_ranking))"
        ),
        "why": "parallel_recall 丢弃向量通道排名（RRF 只并 BM25 与图）",
        "expected_kill": "test_three_channel_merge_ordering",
        "suite": _PIPE_SUITE,
    },
]


def _purge_pycache(path: Path) -> None:
    """删除该模块的字节码缓存。

    必要性：等长变异（如 ``>`` → ``<``）在同一秒内写回原文时，CPython 的
    ``mtime+size`` 校验会认为旧的 ``.pyc`` 仍然有效，导致**后续进程加载变异
    字节码**（源码已是原文，运行时却是变异体）。这既会污染后续门禁层，也会
    让"击杀"结论失真，故每次变异前后都清掉。
    """
    cache = path.parent / "__pycache__"
    if not cache.is_dir():
        return
    for pyc in cache.glob(f"{path.stem}.*.pyc"):
        pyc.unlink(missing_ok=True)


def _run_pytest(suite: str) -> int:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [".venv/bin/python", "-m", "pytest", suite, "-q"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    ).returncode


def main() -> int:
    results: list[tuple[str, bool, str]] = []
    for m in MUTANTS:
        path: Path = m["file"]  # type: ignore[assignment]
        old: str = m["old"]  # type: ignore[assignment]
        new: str = m["new"]  # type: ignore[assignment]
        suite: str = m.get("suite", SUITE)  # type: ignore[assignment]
        original = path.read_text(encoding="utf-8")

        # fail-closed: snippet must appear exactly once
        if original.count(old) != 1:
            results.append((m["why"], False, "fail-closed: 变异片段出现次数 != 1"))
            continue

        _purge_pycache(path)
        path.write_text(original.replace(old, new, 1), encoding="utf-8")
        rc = _run_pytest(suite)
        killed = rc != 0
        # restore and verify (mutant restore on rerun of suite, not eyeball)
        path.write_text(original, encoding="utf-8")
        _purge_pycache(path)
        if path.read_text(encoding="utf-8") != original:
            results.append((m["why"], False, "恢复失败：文件未还原"))
            continue
        detail = (
            f"killed (pytest rc={rc}), expected kill: {m['expected_kill']}"
            if killed
            else "SURVIVED"
        )
        results.append((m["why"], killed, detail))

    all_killed = all(r[1] for r in results)
    print(f"manual mutation results ({len(results)} mutants)")
    for why, killed, detail in results:
        print(f"  [{'KILLED' if killed else 'SURVIVED':<7}] {why}  -> {detail}")
    print("overall:", "PASS (all killed)" if all_killed else "FAIL (survivor)")
    return 0 if all_killed else 1


if __name__ == "__main__":
    sys.exit(main())