"""Tests for the unified corpus layout."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from benchmark.common.corpus import KNOWN_SOURCE_ISSUES
from benchmark.common.unified_corpus import (
    corpus_input_dir,
    corpus_manifest_path,
    load_corpus_manifest,
    plan_family_duplicates,
    prepare_corpus,
    read_corpus_documents,
    source_coverage,
)


class TestCorpusPaths:
    def test_input_dir_is_created(self, tmp_path: Path) -> None:
        path = corpus_input_dir(tmp_path)

        assert path == tmp_path / "input"
        assert path.is_dir()

    def test_manifest_path(self, tmp_path: Path) -> None:
        assert corpus_manifest_path(tmp_path) == tmp_path / "corpus_manifest.json"

    def test_load_missing_manifest_is_empty(self, tmp_path: Path) -> None:
        assert load_corpus_manifest(tmp_path) == {"documents": []}


class _FakeSource:
    def __init__(self, guide: str) -> None:
        self.guide = guide


class _FakeQuestion:
    def __init__(self, question_id: str, guides: list[str]) -> None:
        self.question_id = question_id
        self.gold_sources = [_FakeSource(guide) for guide in guides]


class TestSourceCoverage:
    def test_coverage_counts(self) -> None:
        questions = [
            _FakeQuestion("q1", ["A", "B"]),
            _FakeQuestion("q2", ["C"]),
        ]
        coverage = source_coverage(questions, {"A", "B", "D"})

        assert coverage["fully_covered_questions"] == 1
        assert coverage["missing_source_ids"] == ["C"]
        assert coverage["uncovered_question_ids"] == ["q2"]


@pytest.fixture()
def fake_pdf(tmp_path: Path) -> Path:
    """Minimal valid PDF recognized by pypdf."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    pdf = raw_dir / "guide.pdf"
    # 最小合法 PDF：一页、无文本
    pdf.write_bytes(
        b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
    )
    return raw_dir


def _family_doc(
    status: str,
    source_id: str,
    pdf_file: str,
    chars: int,
    doi: str | None,
    sha: str = "a" * 64,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "pdf_file": pdf_file,
        "pdf_sha256": sha,
        "input_file": f"input/{pdf_file}.txt",
        "page_count": 3,
        "text_characters": chars,
        "status": status,
        "page1_doi": doi,
        "warnings": [],
    }


class TestPlanFamilyDuplicates:
    def test_same_doi_drops_smaller_copy(self) -> None:
        drops, warnings = plan_family_duplicates(
            [
                _family_doc("ok", "g-1", "a.pdf", 80_000, "10.1002/x.1"),
                _family_doc("ok", "g-1", "b.pdf", 61_000, "10.1002/x.1", sha="b" * 64),
            ]
        )

        assert len(drops) == 1
        assert drops[0]["pdf_file"] == "b.pdf"
        assert drops[0]["duplicate_of"] == "a.pdf"
        assert drops[0]["duplicate_reason"] == "same-page1-doi"
        assert drops[0]["input_file"] == "input/a.pdf.txt"
        assert warnings == []

    def test_diverging_dois_are_reported_not_merged(self) -> None:
        drops, warnings = plan_family_duplicates(
            [
                _family_doc("ok", "g-1", "a.pdf", 80_000, "10.1002/x.1"),
                _family_doc("ok", "g-1", "b.pdf", 61_000, "10.1002/x.2", sha="b" * 64),
            ]
        )

        assert drops == []
        assert warnings and warnings[0][0] == "g-1"

    def test_missing_doi_in_multi_group_warns(self) -> None:
        drops, warnings = plan_family_duplicates(
            [
                _family_doc("ok", "g-1", "a.pdf", 80_000, None),
                _family_doc("ok", "g-1", "b.pdf", 61_000, None, sha="b" * 64),
            ]
        )

        assert drops == []
        assert warnings and warnings[0][0] == "g-1"

    def test_duplicates_and_errors_are_never_candidates(self) -> None:
        drops, warnings = plan_family_duplicates(
            [
                _family_doc("duplicate", "g-1", "a.pdf", 80_000, "10.1002/x.1"),
                _family_doc("error", "g-1", "c.pdf", 0, "10.1002/x.1"),
                _family_doc("ok", "g-1", "b.pdf", 61_000, "10.1002/x.1"),
            ]
        )

        assert drops == []
        assert warnings == []

    def test_equal_size_tie_breaks_by_filename(self) -> None:
        drops, _ = plan_family_duplicates(
            [
                _family_doc("ok", "g-1", "b.pdf", 50_000, "10.1002/x.1", sha="b" * 64),
                _family_doc("ok", "g-1", "a.pdf", 50_000, "10.1002/x.1"),
            ]
        )

        assert drops[0]["duplicate_of"] == "a.pdf"


class TestPrepareCorpus:
    def test_prepare_writes_manifest_and_records_error(
        self, tmp_path: Path, fake_pdf: Path
    ) -> None:
        corpus_dir = tmp_path / "corpus"

        manifest = prepare_corpus(
            raw_dir=fake_pdf,
            corpus_dir=corpus_dir,
        )

        # 空文本页 -> status=error 但流程不中断
        assert manifest["pdf_count"] == 1
        assert manifest["error_count"] == 1
        assert manifest["documents"][0]["status"] == "error"
        assert (corpus_dir / "corpus_manifest.json").is_file()


class TestReadCorpusDocuments:
    def test_reads_unified_input_with_source_id(self, tmp_path: Path) -> None:
        input_dir = corpus_input_dir(tmp_path)
        (input_dir / "guide--abc.txt").write_text(
            "SOURCE_ID: ISUOG-cns-2020\n\nbody text", encoding="utf-8"
        )

        documents = read_corpus_documents(tmp_path)

        assert len(documents) == 1
        source_id, path, text = documents[0]
        assert source_id == "ISUOG-cns-2020"
        assert path.name == "guide--abc.txt"
        assert "body text" in text

    def test_empty_input_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            read_corpus_documents(tmp_path)


def _text_pdf_bytes(*lines: str) -> bytes:
    """Minimal single-page PDF whose extracted text is exactly ``lines``."""
    stream_lines = []
    for index, line in enumerate(lines):
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        stream_lines.append(f"BT /F1 12 Tf 72 {750 - 20 * index} Td ({escaped}) Tj ET")
    stream = "\n".join(stream_lines).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
        + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_position = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_position}\n%%EOF\n"
    ).encode()
    return bytes(out)


class TestPrepareCorpusIdentity:
    @staticmethod
    def _two_copy_raw(tmp_path: Path) -> Path:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        long_alias = "ISUOG-Practice-Guidelines-routine-mid-trimester-fetal-ultrasound.pdf"
        long_lines = [
            "Ultrasound Obstet Gynecol 2022; 59: 840-856",
            "DOI: 10.1002/uog.24888",
        ]
        long_lines += [
            f"body line {index} of the longer publisher copy" for index in range(40)
        ]
        (raw_dir / "ISUOG_2022_routine-mid-trimester-scan.pdf").write_bytes(
            _text_pdf_bytes(*long_lines)
        )
        (raw_dir / long_alias).write_bytes(
            _text_pdf_bytes(
                "Ultrasound Obstet Gynecol 2022; 59: 840-856",
                "DOI: 10.1002/uog.24888",
                "shorter scan copy",
            )
        )
        return raw_dir

    def test_same_doi_copies_collapse_end_to_end(self, tmp_path: Path) -> None:
        corpus_dir = tmp_path / "corpus"

        manifest = prepare_corpus(
            raw_dir=self._two_copy_raw(tmp_path), corpus_dir=corpus_dir
        )

        assert manifest["indexed_document_count"] == 1
        assert manifest["duplicate_count"] == 1
        kept = next(d for d in manifest["documents"] if d["status"] == "ok")
        dropped = next(d for d in manifest["documents"] if d["status"] == "duplicate")
        assert kept["pdf_file"] == "ISUOG_2022_routine-mid-trimester-scan.pdf"
        assert dropped["duplicate_of"] == kept["pdf_file"]
        assert dropped["duplicate_reason"] == "same-page1-doi"
        assert dropped["input_file"] == kept["input_file"]
        assert kept["page1_doi"] == "10.1002/uog.24888"
        txts = list((corpus_dir / "input").glob("*.txt"))
        assert [p.name for p in txts] == [Path(kept["input_file"]).name]
        assert txts[0].read_text(encoding="utf-8").splitlines()[0] == (
            "SOURCE_ID: ISUOG-midtrimester-2022"
        )

    def test_stale_orphan_text_is_pruned(self, tmp_path: Path) -> None:
        corpus_dir = tmp_path / "corpus"
        prepare_corpus(raw_dir=self._two_copy_raw(tmp_path), corpus_dir=corpus_dir)
        input_dir = corpus_dir / "input"
        (input_dir / "stale--deadbeef.txt").write_text(
            "SOURCE_ID: ghost\n", encoding="utf-8"
        )

        manifest = prepare_corpus(raw_dir=tmp_path / "raw", corpus_dir=corpus_dir)

        assert manifest["pruned_text_count"] == 1
        assert not (input_dir / "stale--deadbeef.txt").exists()
        referenced = [
            d["input_file"] for d in manifest["documents"] if d["status"] == "ok"
        ]
        assert all((corpus_dir / ref).is_file() for ref in referenced)

    def test_known_source_issue_warning_is_injected(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        (raw_dir / "ISPD_2023_genome-wide-sequencing-position.pdf").write_bytes(
            _text_pdf_bytes(
                "Position statement on non-invasive prenatal testing",
                "DOI: 10.1002/pd.6357",
                "Prenat Diagn 2023",
            )
        )

        manifest = prepare_corpus(raw_dir=raw_dir, corpus_dir=tmp_path / "corpus")

        doc = manifest["documents"][0]
        assert doc["source_id"] == "ISPD-nipt-2023"
        assert KNOWN_SOURCE_ISSUES[
            "ISPD_2023_genome-wide-sequencing-position.pdf"
        ] in doc["warnings"]

    def test_diverging_dois_are_kept_with_warning(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        long_name = "ISUOG-Practice-Guidelines-CNS-part-1-targeted-neurosonography.pdf"
        (raw_dir / "ISUOG_2020_fetal-CNS-part1.pdf").write_bytes(
            _text_pdf_bytes("ISUOG CNS part 1 copy A", "DOI: 10.1002/uog.11111")
        )
        (raw_dir / long_name).write_bytes(
            _text_pdf_bytes("ISUOG CNS part 1 copy B", "DOI: 10.1002/uog.22222")
        )

        manifest = prepare_corpus(raw_dir=raw_dir, corpus_dir=tmp_path / "corpus")

        assert manifest["indexed_document_count"] == 2
        assert manifest["duplicate_count"] == 0
        for doc in manifest["documents"]:
            assert any("page1_doi" in warning for warning in doc["warnings"])

    def test_dataset_path_branch_builds_source_coverage(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        (raw_dir / "ISPD_2023_genome-wide-sequencing-position.pdf").write_bytes(
            _text_pdf_bytes("NIPT position statement", "DOI: 10.1002/pd.6357")
        )
        dataset_path = (
            Path(__file__).resolve().parents[1]
            / "benchmark"
            / "qa"
            / "dataset"
            / "preclinical_challenge_draft.json"
        )

        manifest = prepare_corpus(
            raw_dir=raw_dir,
            corpus_dir=tmp_path / "corpus",
            dataset_path=dataset_path,
        )

        coverage = manifest["dataset_source_coverage"]
        assert coverage["total_questions"] == 12
        assert coverage["available_source_ids"] == []
        assert "China-screening-2022" in coverage["missing_source_ids"]
        assert "ISUOG-11-14w-2023" in coverage["missing_source_ids"]

    def test_missing_raw_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="原始语料目录不存在"):
            prepare_corpus(raw_dir=tmp_path / "nope", corpus_dir=tmp_path / "corpus")

    def test_empty_raw_dir_raises(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="原始语料目录中没有 PDF"):
            prepare_corpus(raw_dir=raw_dir, corpus_dir=tmp_path / "corpus")

    def test_byte_identical_pair_collapses_with_reason(
        self, tmp_path: Path
    ) -> None:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        alias = (
            "ISUOG-Practice-Guidelines-Updated-performance-of-"
            "11-14-week-ultrasound-scan.pdf"
        )
        pdf_bytes = _text_pdf_bytes(
            "DOI: 10.1002/uog.26106", "11-14 week scan body"
        )
        (raw_dir / "ISUOG_2023_11-14-week-ultrasound-scan.pdf").write_bytes(pdf_bytes)
        (raw_dir / alias).write_bytes(pdf_bytes)

        manifest = prepare_corpus(raw_dir=raw_dir, corpus_dir=tmp_path / "corpus")

        assert manifest["indexed_document_count"] == 1
        assert manifest["duplicate_count"] == 1
        dropped = next(
            d for d in manifest["documents"] if d["status"] == "duplicate"
        )
        assert dropped["duplicate_reason"] == "identical-bytes"
        assert dropped["page1_doi"] == "10.1002/uog.26106"

    def test_family_warning_skips_duplicate_records(
        self, tmp_path: Path
    ) -> None:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        long_name = "ISUOG-Practice-Guidelines-CNS-part-1-targeted-neurosonography.pdf"
        alias = (
            "ISUOG-Practice-Guidelines-Updated-performance-of-"
            "11-14-week-ultrasound-scan.pdf"
        )
        (raw_dir / "ISUOG_2020_fetal-CNS-part1.pdf").write_bytes(
            _text_pdf_bytes("ISUOG CNS part 1 copy A", "DOI: 10.1002/uog.11111")
        )
        (raw_dir / long_name).write_bytes(
            _text_pdf_bytes("ISUOG CNS part 1 copy B", "DOI: 10.1002/uog.22222")
        )
        pair_bytes = _text_pdf_bytes("DOI: 10.1002/uog.26106", "scan body")
        (raw_dir / "ISUOG_2023_11-14-week-ultrasound-scan.pdf").write_bytes(
            pair_bytes
        )
        (raw_dir / alias).write_bytes(pair_bytes)

        manifest = prepare_corpus(raw_dir=raw_dir, corpus_dir=tmp_path / "corpus")

        duplicates = [
            d for d in manifest["documents"] if d["status"] == "duplicate"
        ]
        ok_docs = [d for d in manifest["documents"] if d["status"] == "ok"]
        assert len(ok_docs) == 3
        assert len(duplicates) == 1
        assert duplicates[0]["duplicate_reason"] == "identical-bytes"
        assert duplicates[0]["warnings"] == []
        warned = [d for d in ok_docs if d["source_id"] == "ISUOG-cns-2020"]
        assert warned
        assert all(
            any("page1_doi" in warning for warning in doc["warnings"])
            for doc in warned
        )
