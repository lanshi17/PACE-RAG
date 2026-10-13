"""锚点校验 v3（审计补正 §1）：统一生成入口、统一 JSON 格式、失败退出码、
快照与内容身份指纹、前缀命中改记候选。

用法：
  uv run python benchmark/pace_research/verify_anchors_v3.py \
      [--evidence PATH] [--store PATH] [--corpus PATH] [--out PATH]

退出码：0 = 全部通过；1 = 存在失败记录。
产物 JSON 同时保存：快照指纹（chunk 文本哈希列表）、逐记录校验结果
（pass / fail + failures）、前缀命中记为候选（candidate_anchors，非"多锚点覆盖"）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from prenatal_rag.evidence_store import EvidenceStore  # noqa: E402


def _norm(s: str) -> str:
    return " ".join(s.split())


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def verify_anchors_v3(
    evidence_path: Path,
    store_path: Path,
    corpus_dir: Path,
) -> dict:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    store = EvidenceStore(store_path)
    chunks = {c.anchor_id: c for c in store.iter_chunks()}
    manifest = json.loads(
        (corpus_dir / "corpus_manifest.json").read_text(encoding="utf-8")
    )
    manifest_by_file = {
        doc["input_file"].split("/")[-1]: doc["source_id"]
        for doc in manifest.get("documents", [])
    }

    # 快照身份：全部 chunk 的 (anchor_id, source_id, text_sha256) 有序列表哈希
    snapshot_identity = {
        "chunk_count": len(chunks),
        "content_fingerprint": hashlib.sha256(
            json.dumps(
                sorted(
                    (a, c.source_id, c.text_sha256) for a, c in chunks.items()
                ),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest(),
    }

    results = []
    for r in evidence.get("records", []):
        eid = r["evidence_id"]
        failures: list[str] = []
        fname = r["input_file"].split("/")[-1]
        fpath = corpus_dir / "input" / fname

        # step1: 来源文档存在 + 指纹一致
        text = ""
        if not fpath.is_file():
            failures.append("source_file_missing")
        else:
            text = fpath.read_text(encoding="utf-8")
            if _sha256_text(text) != r["input_text_sha256"]:
                failures.append("input_text_sha256_mismatch")

        # step2: 证据库快照中有声明锚点
        aid_raw = r.get("evidence_store_anchor_id")
        aid = int(aid_raw) if aid_raw not in (None, "", "None") else None
        chunk = chunks.get(aid) if aid is not None else None
        if chunk is None:
            failures.append("snapshot_anchor_missing")
            results.append(
                {
                    "evidence_id": eid,
                    "declared_anchor_id": aid_raw,
                    "verdict": "fail",
                    "failures": failures,
                    "candidate_anchors": [],
                    "source_document": {
                        "file": fname,
                        "sha256": _sha256_text(text) if text else None,
                    },
                }
            )
            continue

        # step2b: chunk 来源与 manifest 一致（错来源反例）
        expected_sid = manifest_by_file.get(fname)
        if chunk.source_id != expected_sid:
            failures.append(
                f"wrong_source: chunk={chunk.source_id} manifest={expected_sid}"
            )

        # step3: 完整摘录包含于锚点 chunk 文本
        norm = _norm
        excerpt = norm(r["excerpt"])
        chunk_text = norm(chunk.text)
        full_containment = excerpt in chunk_text
        if not full_containment:
            failures.append("full_excerpt_not_contained")

        # step4: 前缀命中 → 记为候选（非"多锚点覆盖"——多锚点不能直接称覆盖）
        prefix = excerpt[:80]
        candidate_anchors = sorted(
            a for a, c in chunks.items() if a != aid and prefix in norm(c.text)
        )

        results.append(
            {
                "evidence_id": eid,
                "declared_anchor_id": aid,
                "verdict": "pass" if not failures else "fail",
                "failures": failures,
                "candidate_anchors": candidate_anchors,
                "source_document": {
                    "file": fname,
                    "sha256": _sha256_text(text),
                    "manifest_source_id": expected_sid,
                },
                "anchor_chunk": {
                    "source_id": chunk.source_id,
                    "text_sha256": chunk.text_sha256,
                },
            }
        )

    ok = sum(1 for r in results if r["verdict"] == "pass")
    return {
        "schema_version": "anchor-verify-v3",
        "reproducible": ok,
        "total": len(results),
        "fail_count": len(results) - ok,
        "snapshot_identity": snapshot_identity,
        "exit_code_meaning": "0 = all pass; 1 = at least one fail record",
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=REPO / "benchmark/qa/dataset/pace_conditions_v1/evidence_candidates.json",
    )
    parser.add_argument(
        "--store", type=Path, default=REPO / "benchmark/data/evidence_store"
    )
    parser.add_argument(
        "--corpus", type=Path, default=REPO / "benchmark/data/corpus"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO
        / "benchmark/qa/dataset/pace_conditions_v1/anchor_verification_v3.json",
    )
    args = parser.parse_args()
    report = verify_anchors_v3(args.evidence, args.store, args.corpus)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"reproducible: {report['reproducible']}/{report['total']} "
        f"| fails: {report['fail_count']} | wrote {args.out}"
    )
    # 失败 → 非零退出码（验收 §1）
    return 0 if report["fail_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
