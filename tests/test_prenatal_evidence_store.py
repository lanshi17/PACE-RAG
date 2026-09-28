"""证据存储（prenatal_rag.evidence_store）测试。

用合成小语料覆盖：水印剥离、页区域平铺、chunk 精确切片、页/span 定位、
幂等 ingest 与文本变化时的整份替换。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from prenatal_rag.evidence_store import (
    EvidenceStore,
    ingest_unified_corpus,
    strip_watermark_lines,
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


HEADER = "SOURCE_ID: {sid}\nORIGINAL_FILE: {sid}.pdf\nPDF_SHA256: abc\n\n"

DOC_A = (
    HEADER.format(sid="Doc-A")
    + "## Page 1\n\n"
    + "Downloaded from Wiley Online Library by test\n"
    + "Intro paragraph about nuchal translucency measurement at 11+0 to 13+6 weeks.\n\n"
    + "Second paragraph on page one.\n\n"
    + "## Page 2\n\n"
    + "See the Terms and Conditions on Wiley Online Library\n"
    + "Fetal cardiac screening text lives here.\n\n"
)

DOC_B = HEADER.format(sid="Doc-B") + "## Page 1\n\n" + "Twin pregnancy chorionicity text.\n\n"

MANIFEST = {
    "documents": [
        {
            "source_id": "Doc-A",
            "status": "ok",
            "input_file": "Doc-A--hash1.txt",
            "page1_doi": "10.1002/uog.99999",
            "pdf_sha256": "a" * 64,
            "page_count": 2,
            "text_characters": len(DOC_A),
            "warnings": ["测试警告"],
        },
        {
            "source_id": "Doc-A-dup",
            "status": "duplicate",
            "input_file": "Doc-A--hash2.txt",
            "page1_doi": "10.1002/uog.99999",
            "pdf_sha256": "b" * 64,
            "page_count": 2,
            "text_characters": len(DOC_A),
            "warnings": [],
        },
        {
            "source_id": "Doc-B",
            "status": "ok",
            "input_file": "Doc-B--hash1.txt",
            "page1_doi": None,
            "pdf_sha256": "c" * 64,
            "page_count": 1,
            "text_characters": len(DOC_B),
            "warnings": [],
        },
    ]
}


@pytest.fixture()
def corpus_dir(tmp_path: Path) -> Path:
    (tmp_path / "input").mkdir()
    (tmp_path / "corpus_manifest.json").write_text(
        json.dumps(MANIFEST), encoding="utf-8"
    )
    (tmp_path / "input" / "Doc-A--hash1.txt").write_text(DOC_A, encoding="utf-8")
    (tmp_path / "input" / "Doc-B--hash1.txt").write_text(DOC_B, encoding="utf-8")
    return tmp_path


@pytest.fixture()
def store(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(tmp_path / "store")


class TestStripWatermarks:
    def test_removes_matching_lines_and_counts(self) -> None:
        cleaned, removed = strip_watermark_lines("keep\nDownloaded from x\nmore\n")
        assert removed == 1
        assert cleaned == "keep\nmore\n"

    def test_no_watermarks_is_noop(self) -> None:
        text = "keep\nmore\n"
        assert strip_watermark_lines(text) == (text, 0)


class TestIngestCorpus:
    def test_ingests_ok_documents_only(self, store: EvidenceStore, corpus_dir: Path) -> None:
        _, report = ingest_unified_corpus(corpus_dir, store)
        assert report.ingested == ["Doc-A", "Doc-B"]
        assert report.skipped == ["Doc-A-dup"]
        assert report.watermark_lines_removed == 2
        docs = {doc.source_id: doc for doc in store.documents()}
        assert set(docs) == {"Doc-A", "Doc-B"}
        assert docs["Doc-A"].family_id == "10.1002/uog.99999"
        assert docs["Doc-A"].page1_doi == "10.1002/uog.99999"
        assert docs["Doc-A"].manifest_warnings == ("测试警告",)
        # 缺 DOI 的单副本家族退化为 source_id
        assert docs["Doc-B"].family_id == "Doc-B"
        assert report.summary()["chunk_count"] > 0

    def test_watermark_lines_absent_from_stored_text(
        self, store: EvidenceStore, corpus_dir: Path
    ) -> None:
        ingest_unified_corpus(corpus_dir, store)
        text = store.load_text("Doc-A")
        assert "Downloaded from" not in text
        assert "See the Terms and Conditions" not in text
        assert "## Page 1" in text and "## Page 2" in text
        assert "nuchal translucency" in text

    def test_chunk_text_is_exact_slice(self, store: EvidenceStore, corpus_dir: Path) -> None:
        ingest_unified_corpus(corpus_dir, store)
        text = store.load_text("Doc-A")
        for chunk in store.iter_chunks("Doc-A"):
            assert chunk.page_start == chunk.page_end
            assert chunk.text == text[chunk.char_start : chunk.char_end]
            assert chunk.text_sha256 == _sha(chunk.text)
            assert "## Page" not in chunk.text

    def test_pages_tile_text_without_gaps(
        self, store: EvidenceStore, corpus_dir: Path
    ) -> None:
        ingest_unified_corpus(corpus_dir, store)
        text = store.load_text("Doc-A")
        pages = store.page_anchors("Doc-A")
        assert [p.page_start for p in pages] == [1, 2]
        assert pages[0].char_start == 0 and pages[-1].char_end == len(text)
        for prev, nxt in zip(pages, pages[1:]):
            assert nxt.char_start == prev.char_end
        assert "nuchal translucency" in store.page_text("Doc-A", 1)
        assert "cardiac screening" in store.page_text("Doc-A", 2)

    def test_locates_snippet_with_page(self, store: EvidenceStore, corpus_dir: Path) -> None:
        ingest_unified_corpus(corpus_dir, store)
        snippet = "Fetal cardiac screening text lives here."
        anchors = store.locate("Doc-A", snippet)
        assert len(anchors) == 1
        anchor = anchors[0]
        assert anchor.page_start == 2
        assert anchor.char_end - anchor.char_start == len(snippet)
        assert anchor.text_sha256 == _sha(snippet)

    def test_locate_multiple_occurrences_and_missing(
        self, store: EvidenceStore, corpus_dir: Path
    ) -> None:
        ingest_unified_corpus(corpus_dir, store)
        text = store.load_text("Doc-B")
        (corpus_dir / "input" / "Doc-B--hash1.txt").write_text(
            text + "Repeat marker.\nmid marker\nRepeat marker.\n", encoding="utf-8"
        )
        store2, _ = ingest_unified_corpus(corpus_dir, store)
        assert len(store2.locate("Doc-B", "Repeat marker.")) == 2
        assert store.locate("Doc-B", "不存在的内容") == []

    def test_reingest_is_idempotent(self, store: EvidenceStore, corpus_dir: Path) -> None:
        _, first = ingest_unified_corpus(corpus_dir, store)
        chunks_after_first = list(store.iter_chunks())
        _, second = ingest_unified_corpus(corpus_dir, store)
        assert second.unchanged == ["Doc-A", "Doc-B"]
        assert not second.ingested
        assert second.chunk_count == 0
        assert list(store.iter_chunks()) == chunks_after_first
        assert first.chunk_count == len(chunks_after_first)

    def test_changed_text_replaces_document(
        self, store: EvidenceStore, corpus_dir: Path
    ) -> None:
        ingest_unified_corpus(corpus_dir, store)
        old_doc = store.document("Doc-A")
        (corpus_dir / "input" / "Doc-A--hash1.txt").write_text(
            DOC_A + "## Page 3\n\nAppended retraction notice text.\n\n",
            encoding="utf-8",
        )
        _, report = ingest_unified_corpus(corpus_dir, store)
        assert report.ingested == ["Doc-A"]
        new_doc = store.document("Doc-A")
        assert new_doc is not None and old_doc is not None
        assert new_doc.text_sha256 != old_doc.text_sha256
        assert new_doc.page_count == 3
        anchors = store.locate("Doc-A", "Appended retraction notice text.")
        assert len(anchors) == 1 and anchors[0].page_start == 3

    def test_duplicate_corpus_reuses_family(self, tmp_path: Path) -> None:
        """同文异源的两个 PDF 归并到同一 family_id（续记 §2.1 两键身份）。"""
        manifest = {
            "documents": [
                {
                    "source_id": "Same-A",
                    "status": "ok",
                    "input_file": "Same-A.txt",
                    "page1_doi": "10.1002/uog.11111",
                    "pdf_sha256": "1" * 64,
                    "page_count": 1,
                    "text_characters": 10,
                    "warnings": [],
                },
                {
                    "source_id": "Same-B",
                    "status": "ok",
                    "input_file": "Same-B.txt",
                    "page1_doi": "10.1002/uog.11111",
                    "pdf_sha256": "2" * 64,
                    "page_count": 1,
                    "text_characters": 10,
                    "warnings": [],
                },
            ]
        }
        (tmp_path / "input").mkdir()
        (tmp_path / "corpus_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        for sid in ("Same-A", "Same-B"):
            (tmp_path / "input" / f"{sid}.txt").write_text(
                f"SOURCE_ID: {sid}\n\n## Page 1\n\nshared body text\n", encoding="utf-8"
            )
        store = EvidenceStore(tmp_path / "store")
        _, report = ingest_unified_corpus(tmp_path, store)
        assert report.ingested == ["Same-A", "Same-B"]
        families = {doc.source_id: doc.family_id for doc in store.documents()}
        assert families["Same-A"] == families["Same-B"] == "10.1002/uog.11111"
