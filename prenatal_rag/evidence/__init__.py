"""证据证据集合选择（§5.2）。"""

from __future__ import annotations

from prenatal_rag.evidence.selection import (
    EvidenceBucket,
    EvidenceCandidate,
    EvidenceRole,
    SelectedEvidence,
    select_evidence,
)
from prenatal_rag.evidence.supersession import SupersessionGraph
from prenatal_rag.evidence.version_citations import (
    VersionCitationReport,
    VersionCitationStatus,
    verify_version_citations,
)

__all__ = [
    "EvidenceBucket",
    "EvidenceCandidate",
    "EvidenceRole",
    "SelectedEvidence",
    "SupersessionGraph",
    "VersionCitationReport",
    "VersionCitationStatus",
    "select_evidence",
    "verify_version_citations",
]