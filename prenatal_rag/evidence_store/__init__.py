"""证据真值层存储（SQLite 原型）。"""

from __future__ import annotations

from prenatal_rag.evidence_store.ingest import (
    DEFAULT_EVIDENCE_STORE_DIR,
    IngestReport,
    ingest_unified_corpus,
)
from prenatal_rag.evidence_store.store import (
    INGEST_VERSION,
    Chunk,
    DocumentIngestResult,
    EvidenceStore,
    SourceDocument,
    SpanAnchor,
    strip_watermark_lines,
)

__all__ = [
    "DEFAULT_EVIDENCE_STORE_DIR",
    "INGEST_VERSION",
    "Chunk",
    "DocumentIngestResult",
    "EvidenceStore",
    "IngestReport",
    "SourceDocument",
    "SpanAnchor",
    "strip_watermark_lines",
    "ingest_unified_corpus",
]
