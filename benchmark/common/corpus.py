"""Corpus preparation helpers shared by all baselines.

PDF extraction, canonical source IDs, and manifest writing used to be
duplicated in every baseline entry point; the canonical mapping and the
page-level extraction rules live here now.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_NAME = "corpus_manifest.json"

CANONICAL_SOURCE_FILES: dict[str, str] = {
    "ISUOG_2020_fetal-CNS-part1.pdf": "ISUOG-cns-2020",
    "ISUOG_2022_routine-mid-trimester-scan.pdf": "ISUOG-midtrimester-2022",
    "ISUOG_2023_11-14-week-ultrasound-scan.pdf": "ISUOG-11-14w-2023",
    "ISUOG_2023_fetal-cardiac-screening.pdf": "ISUOG-fetal-cardiac-screening-2023",
    "ISUOG-Practice-Guidelines-CNS-part-1-targeted-neurosonography.pdf": (
        "ISUOG-cns-2020"
    ),
    "ISUOG-Practice-Guidelines-Updated-performance-of-11-14-week-ultrasound-scan.pdf": (
        "ISUOG-11-14w-2023"
    ),
    "UOG-2023-Carvalho-ISUOG-Practice-Guidelines-updated-fetal-cardiac-screening.pdf": (
        "ISUOG-fetal-cardiac-screening-2023"
    ),
    "ISUOG-Practice-Guidelines-routine-mid-trimester-fetal-ultrasound.pdf": (
        "ISUOG-midtrimester-2022"
    ),
    "ISUOG-Practice-Guidelines-intrapartum-ultrasound.pdf": (
        "ISUOG_2018_intrapartum-ultrasound"
    ),
    "ISUOG-Practice-Guidelines-ultrasound-fetal-biometry-growth.pdf": (
        "ISUOG_2019_fetal-biometry-growth"
    ),
    "ISUOG-Practice-Guidelines-invasive-procedures-prenatal-diagnosis.pdf": (
        "ISUOG_2016_invasive-prenatal-diagnosis"
    ),
    "ISPD_2023_genome-wide-sequencing-position.pdf": "ISPD-nipt-2023",
}


KNOWN_SOURCE_ISSUES: dict[str, str] = {
    "ISPD_2023_genome-wide-sequencing-position.pdf": (
        "文件名指向 genome-wide sequencing 声明，但正文为 NIPT 立场声明"
        "（Prenat Diagn 2023;43:814–828，DOI 10.1002/pd.6357）；"
        "source_id 已由历史 ID ISPD_2023_genome-wide-sequencing-position 更正为 ISPD-nipt-2023。"
    ),
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def safe_slug(value: str, max_length: int = 120) -> str:
    """ASCII slug usable as a filename fragment for any baseline."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_value)
    slug = re.sub(r"-{2,}", "-", slug).strip("-._")
    return (slug or "document")[:max_length]


def canonical_source_id(pdf_path: Path) -> str:
    """Map a known corpus PDF to the stable dataset source ID."""
    return CANONICAL_SOURCE_FILES.get(pdf_path.name, safe_slug(pdf_path.stem))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_pdf_text(pdf_path: Path) -> tuple[str, int, list[str]]:
    """Extract page-tagged text from a PDF using pypdf.

    Returns ``(text, page_count, warnings)``.  Per-page failures are collected
    as warnings instead of aborting the whole document.
    """
    from pypdf import PdfReader

    reader: Any
    try:
        reader = PdfReader(str(pdf_path), strict=False)
    except Exception as exc:  # noqa: BLE001
        return "", 0, [f"open: {type(exc).__name__}: {exc}"]

    page_sections: list[str] = []
    warnings: list[str] = []

    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"page {page_number}: {type(exc).__name__}: {exc}")
            continue
        text = text.replace("\x00", "")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{4,}", "\n\n\n", text).strip()
        if text:
            page_sections.append(f"## Page {page_number}\n\n{text}")

    return "\n\n".join(page_sections), len(reader.pages), warnings


def source_id_from_text(text: str) -> str | None:
    """Recover the ``SOURCE_ID`` header written during corpus preparation."""
    match = re.search(r"(?m)^SOURCE_ID:\s*(\S+)\s*$", text)
    return match.group(1) if match else None


DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
PAGE_MARK_RE = re.compile(r"(?m)^## Page (\d+)\s*$")


def extract_page1_doi(text: str) -> str | None:
    """Return the DOI printed on page 1 of an extracted corpus text.

    Content-level identity signal: two PDFs of the same article print the same
    DOI even when their bytes differ (publisher layout vs scanned reprint).
    Falls back to the first 6000 characters when no page marker exists.
    """
    matches = list(PAGE_MARK_RE.finditer(text))
    if matches:
        start = matches[0].end()
        end = matches[1].start() if len(matches) > 1 else len(text)
        page1 = text[start:end]
    else:
        page1 = text[:6000]
    doi = DOI_RE.search(page1)
    return doi.group(0).rstrip(".") if doi else None


def write_manifest(project_dir: Path, manifest: dict) -> Path:
    """Persist the corpus manifest atomically enough for benchmark use."""
    manifest_path = project_dir / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path
