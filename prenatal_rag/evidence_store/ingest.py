"""统一语料 → 证据存储 ingest。

来源清单沿用 benchmark/data/corpus/corpus_manifest.json（2026-09-12 审计后
的 26 篇单份索引文本）；``status != "ok"`` 的重复记录跳过。family_id 取
页首 DOI（同文异源归并），缺失 DOI 时退化为 source_id（单副本家族）。

主文档 §4：文件系统保存原始材料、SQLite 保存版本与事务；
manifest 格式是 benchmark 侧的稳定契约，本模块本地解析清单，
保持 prenatal_rag 包不依赖 benchmark.*。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prenatal_rag.evidence_store.store import EvidenceStore

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS_DIR = REPOSITORY_ROOT / "benchmark" / "data" / "corpus"
DEFAULT_EVIDENCE_STORE_DIR = REPOSITORY_ROOT / "benchmark" / "data" / "evidence_store"


@dataclass
class IngestReport:
    """全量 ingest 汇总。"""

    ingested: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    chunk_count: int = 0
    watermark_lines_removed: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "ingested": len(self.ingested),
            "unchanged": len(self.unchanged),
            "skipped": len(self.skipped),
            "chunk_count": self.chunk_count,
            "watermark_lines_removed": self.watermark_lines_removed,
        }


def ingest_unified_corpus(
    corpus_dir: Path | None = None,
    store: EvidenceStore | None = None,
    chunk_target_chars: int = 1200,
) -> tuple[EvidenceStore, IngestReport]:
    """按 manifest 把全部 ok 文档写入证据存储（幂等；文本未变则跳过）。"""
    corpus_dir = Path(corpus_dir) if corpus_dir is not None else DEFAULT_CORPUS_DIR
    store = store if store is not None else EvidenceStore(DEFAULT_EVIDENCE_STORE_DIR)
    manifest = json.loads(
        (corpus_dir / "corpus_manifest.json").read_text(encoding="utf-8")
    )
    input_dir = corpus_dir / "input"
    report = IngestReport()

    for doc in manifest.get("documents", []):
        source_id = str(doc.get("source_id", ""))
        if not source_id or doc.get("status") != "ok":
            if source_id:
                report.skipped.append(source_id)
            continue
        text_path = input_dir / Path(doc["input_file"]).name
        text = text_path.read_text(encoding="utf-8")
        result = store.ingest_document(
            source_id,
            text,
            family_id=doc.get("page1_doi") or source_id,
            page1_doi=doc.get("page1_doi"),
            original_file=doc.get("input_file"),
            pdf_sha256=doc.get("pdf_sha256"),
            manifest_warnings=tuple(doc.get("warnings") or ()),
            chunk_target_chars=chunk_target_chars,
        )
        if result.created:
            report.ingested.append(source_id)
        else:
            report.unchanged.append(source_id)
        report.chunk_count += result.chunk_count
        report.watermark_lines_removed += result.watermark_lines_removed
    return store, report
