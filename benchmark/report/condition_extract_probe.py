"""P1.5 condition-index probe: B1 前置的 chunk 级条件抽取验收。

对证据存储全部 chunk 运行确定性条件抽取并写回，报告：
- 各条件维度（GA/人群/技术）命中数与覆盖率；
- 抽样 GA 窗口分布（验证 15 组变体的窗口形态被还原）；
- 若干跨文档/同文档条件变体的三值分类样例（Applicable/Unknown/Inapplicable）。

只依赖 prenatal_rag.*；不改基准索引、不调 LLM。用法：
    python benchmark/report/condition_extract_probe.py [--limit N]
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from prenatal_rag.conditions import ConditionType, GaWindow, QueryConditions
from prenatal_rag.conditions.filter import classify
from prenatal_rag.conditions.schema import ChunkCondition
from prenatal_rag.evidence_store import EvidenceStore
from prenatal_rag.evidence_store.ingest import DEFAULT_EVIDENCE_STORE_DIR

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "benchmark" / "results" / "corpus-condition-20260915"


def _sample_ga(conds: list[ChunkCondition]) -> list[str]:
    return sorted(
        {
            GaWindow.parse(c.value).__str__()
            for c in conds
            if c.condition_type is ConditionType.GESTATIONAL_AGE
        }
    )


def main(limit: int | None) -> None:
    store = EvidenceStore(DEFAULT_EVIDENCE_STORE_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1) 建/重建条件索引
    written = 0
    chunk_stats: list[str] = []
    total = 0
    for i, chunk in enumerate(store.iter_chunks()):
        if limit is not None and i >= limit:
            break
        total += 1
        conds = []
        from prenatal_rag.conditions.extract import extract_conditions

        conds = extract_conditions(
            chunk.text,
            anchor_id=chunk.anchor_id,
            source_id=chunk.source_id,
            base_offset=chunk.char_start,
        )
        store.rewrite_chunk_conditions(chunk.anchor_id, conds)
        written += len(conds)
        for c in conds:
            chunk_stats.append(c.condition_type.value)

    counts = Counter(chunk_stats)
    n_chunks = total
    print(f"chunks scanned: {n_chunks:-d}  |  conditions written: {written:-d}")
    for t in ConditionType:
        c = counts.get(t.value, 0)
        print(f"  {t.value:<18} {c:-6d}  ({(c / n_chunks * 100) if n_chunks else 0:.1f}% of chunks)")

    # 2) 常见 GA 窗口分布（验证 15 组变体窗口形态被还原）
    ga_windows: Counter[str] = Counter()
    for chunk in store.iter_chunks():
        for c in store.conditions_for(chunk.anchor_id):
            if c.condition_type is ConditionType.GESTATIONAL_AGE:
                ga_windows[GaWindow.parse(c.value).__str__()] += 1
    print("\n最常用 GA 窗口（天，含无界）:")
    for window, n in ga_windows.most_common(12):
        print(f"  {window:<14} x{n}")

    # 3) 三值分类抽样：孕周变体（同文档不同窗口）
    demos = [
        # (描述, 查询, 抽取文本)
        (
            "20 周 vs 18-24周条款",
            QueryConditions(gestational_age=GaWindow.closed(140, 140)),
            "the scan is performed at 18 to 24 weeks of gestation",
        ),
        (
            "20 周 vs 11+0-13+6条款",
            QueryConditions(gestational_age=GaWindow.closed(140, 140)),
            "Nuchal translucency measured at 11+0 to 13+6 weeks",
        ),
        (
            "单胎查询 vs 双胎条款",
            QueryConditions(population=frozenset({"singleton"})),
            "in monochorionic twins surveillance",
        ),
    ]
    print("\n三值分类样例:")
    from prenatal_rag.conditions.extract import extract_conditions

    for label, query, text in demos:
        conds = extract_conditions(text, anchor_id=-1, source_id="demo", base_offset=0)
        verdict = classify(conds, query).value
        print(f"  [{verdict:<12}] {label}")

    store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    main(args.limit)