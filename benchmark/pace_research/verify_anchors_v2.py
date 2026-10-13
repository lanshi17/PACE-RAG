"""锚点可复现校验 v2（预注册 pace-research-plan.md §5.2 / 审计补正 §1）。

双向校验：来源文档 → 证据库快照 → 锚点 → 完整摘录。
反例检出：错来源、仅前缀相同的候选（多锚点覆盖允许，单前缀独占不允许）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from prenatal_rag.evidence_store import EvidenceStore  # noqa: E402


def verify_anchors(
    evidence_path: Path,
    store_path: Path,
    corpus_dir: Path,
) -> dict:
    """对 evidence_candidates 全部记录执行四步校验。

    返回逐记录结果 + 汇总。反例：声明锚点的 chunk 缺失、完整摘录不包含、
    chunk 来源与 manifest 不一致 → 记 failure。多锚点覆盖（其他 chunk 也含
    摘录前缀）允许，但逐条记录。
    """
    import hashlib

    d = json.loads(evidence_path.read_text(encoding="utf-8"))
    store = EvidenceStore(store_path)
    chunks = {c.anchor_id: c for c in store.iter_chunks()}
    manifest = json.loads(
        (corpus_dir / "corpus_manifest.json").read_text(encoding="utf-8")
    )
    manifest_by_file = {
        doc["input_file"].split("/")[-1]: doc["source_id"]
        for doc in manifest.get("documents", [])
    }

    results = []
    for r in d["records"]:
        eid = r["evidence_id"]
        fname = r["input_file"].split("/")[-1]
        failures: list[str] = []

        # step1: 来源文档存在且指纹一致
        fpath = corpus_dir / "input" / fname
        if not fpath.is_file():
            results.append({"evidence_id": eid, "verdict": "fail", "failures": ["file_missing"]})
            continue
        text = fpath.read_text(encoding="utf-8")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != r["input_text_sha256"]:
            failures.append("input_text_sha256_mismatch")

        # step2: 证据库快照中有声明锚点的 chunk
        aid = int(r["evidence_store_anchor_id"])
        chunk = chunks.get(aid)
        if chunk is None:
            failures.append("snapshot_anchor_missing")
        else:
            # step2b: chunk 来源与 manifest 一致（错来源反例）
            expected_sid = manifest_by_file.get(fname)
            if chunk.source_id != expected_sid:
                failures.append(
                    f"wrong_source: chunk={chunk.source_id} manifest={expected_sid}"
                )

        # step3: 完整摘录包含于锚点 chunk 文本（空白归一化）
        def _norm(s: str) -> str:
            return " ".join(s.split())

        excerpt = _norm(r["excerpt"])
        chunk_text = _norm(chunk.text) if chunk else ""
        if excerpt not in chunk_text:
            failures.append("full_excerpt_not_contained")

        # step4: 反例——仅前缀相同的其他锚点（多锚点覆盖允许，逐条记录）
        prefix = excerpt[:80]
        others = [
            a for a, c in chunks.items() if a != aid and prefix in _norm(c.text)
        ]

        results.append(
            {
                "evidence_id": eid,
                "anchor_id": aid,
                "verdict": "pass" if not failures else "fail",
                "failures": failures,
                "chunk_source_id": chunk.source_id if chunk else None,
                "manifest_source_id": manifest_by_file.get(fname),
                "multi_anchor_coverage": {"count": len(others), "anchor_ids": others},
            }
        )

    ok = sum(1 for r in results if r["verdict"] == "pass")
    multi = sum(1 for r in results if r["multi_anchor_coverage"]["count"] > 0)
    return {
        "schema_version": "anchor-verify-v2",
        "reproducible": ok,
        "total": len(results),
        "multi_anchor_coverage_rows": multi,
        "fail_examples": [r for r in results if r["verdict"] == "fail"],
        "results": results,
    }


if __name__ == "__main__":
    rep = verify_anchors(
        REPO / "benchmark/qa/dataset/pace_conditions_v1/evidence_candidates.json",
        REPO / "benchmark/data/evidence_store",
        REPO / "benchmark/data/corpus",
    )
    print(f"reproducible: {rep['reproducible']}/{rep['total']}")
    print(f"multi-anchor coverage rows: {rep['multi_anchor_coverage_rows']}")
    for f in rep["fail_examples"]:
        print("FAIL:", f)
