"""生成端版本核验真实探针（PACE 批次 10，零 LLM）。

用真实语料 + 冻结的 B0 检索上下文检验 ``verify_version_citations`` 的两端行为：

- 合成"只引旧版"的答案（引用上下文里所有被替代来源的编号）→ 期望 ``stale_only``；
- 合成"旧版+当前版"的答案 → 期望 ``consistent``。

这验证核验器在**真实来源集合**上的判定，而非只在单测的构造数据上。真实模型答案的
分布见 B1 端到端评估的 ``version_check_summary``（需 token）。

Usage (repo root):
    PYTHONPATH=. .venv/bin/python benchmark/report/version_citation_probe.py [--out PATH]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from prenatal_rag.evidence import verify_version_citations
from prenatal_rag.evidence_store import EvidenceStore

from benchmark.common.versions import load_supersession_graph

REPO_ROOT = Path(__file__).resolve().parents[2]
B0_RESULTS = REPO_ROOT / "benchmark/results/light_rag/pace-b0-evaluation-20260914.json"
DEFAULT_OUT_DIR = REPO_ROOT / "benchmark/results/corpus-condition-20260915"
EVIDENCE_STORE_DIR = REPO_ROOT / "benchmark/data/evidence_store"


def main(out_dir: Path) -> None:
    graph = load_supersession_graph(EvidenceStore(EVIDENCE_STORE_DIR))
    data = json.loads(B0_RESULTS.read_text(encoding="utf-8"))
    superseded = set(graph.superseded_sources())
    current_versions = {graph.current_version(s) for s in superseded}

    rows: list[dict[str, Any]] = []
    for item in data.get("results", []):
        contexts = list(item.get("contexts", []))
        old_idx = [i for i, c in enumerate(contexts, 1) if c.get("source_id") in superseded]
        cur_idx = [
            i for i, c in enumerate(contexts, 1) if c.get("source_id") in current_versions
        ]
        if not old_idx:
            continue
        stale_answer = " ".join(f"[E{i}]" for i in old_idx)
        complete_answer = stale_answer + " " + " ".join(f"[E{i}]" for i in cur_idx)
        stale = verify_version_citations(stale_answer, contexts, graph)
        complete = verify_version_citations(complete_answer, contexts, graph)
        rows.append(
            {
                "question_id": item.get("question_id"),
                "n_contexts": len(contexts),
                "n_superseded_chunks": len(old_idx),
                "n_current_chunks": len(cur_idx),
                "current_available": bool(cur_idx),
                "stale_only_answer_status": stale.status.value,
                "stale_only_missing": list(stale.missing_current),
                "complete_answer_status": complete.status.value,
            }
        )

    stale_expected = sum(1 for r in rows if r["stale_only_answer_status"] == "stale_only")
    complete_expected = sum(1 for r in rows if r["complete_answer_status"] == "consistent")
    summary = {
        "questions_with_superseded_contexts": len(rows),
        "questions_with_current_version_available": sum(
            1 for r in rows if r["current_available"]
        ),
        "stale_only_answers_flagged": stale_expected,
        "complete_answers_accepted": complete_expected,
        "graph": {
            "superseded_sources": sorted(superseded),
            "current_versions": sorted(current_versions),
        },
    }

    print("=== 生成端版本核验真实探针（冻结 B0 上下文）===")
    print(f"  含被替代来源的题数: {len(rows)} / {len(data.get('results', []))}")
    print(f"  其中当前版本可得: {summary['questions_with_current_version_available']}")
    print(f"  只引旧版被标 stale_only: {stale_expected}")
    print(f"  旧版+当前版被接受: {complete_expected}")
    for row in rows[:6]:
        print(
            f"    {row['question_id']:<10} old={row['n_superseded_chunks']} "
            f"cur={row['n_current_chunks']} stale={row['stale_only_answer_status']} "
            f"complete={row['complete_answer_status']}"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "version_citation_probe.json"
    out_path.write_text(
        json.dumps({"summary": summary, "per_question": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("wrote:", out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    main(args.out)
