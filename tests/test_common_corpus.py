"""Tests for shared corpus helpers."""

from __future__ import annotations

from pathlib import Path

from benchmark.common.corpus import (
    KNOWN_SOURCE_ISSUES,
    canonical_source_id,
    extract_page1_doi,
    extract_pdf_text,
    safe_slug,
    source_id_from_text,
)


class TestCanonicalSourceId:
    def test_known_pdf_maps_to_dataset_id(self) -> None:
        assert (
            canonical_source_id(Path("ISUOG_2022_routine-mid-trimester-scan.pdf"))
            == "ISUOG-midtrimester-2022"
        )

    def test_alias_pdf_maps_to_same_id(self) -> None:
        alias = Path(
            "ISUOG-Practice-Guidelines-Updated-performance-of-11-14-week-"
            "ultrasound-scan.pdf"
        )
        assert canonical_source_id(alias) == "ISUOG-11-14w-2023"

    def test_unknown_pdf_falls_back_to_slug(self) -> None:
        assert canonical_source_id(Path("Some_Other Guide.pdf")) == "Some_Other-Guide"


class TestCanonicalSourceIdFamilies:
    def test_same_article_long_names_map_to_family_ids(self) -> None:
        assert (
            canonical_source_id(
                Path(
                    "ISUOG-Practice-Guidelines-routine-mid-trimester-fetal-ultrasound.pdf"
                )
            )
            == "ISUOG-midtrimester-2022"
        )
        assert (
            canonical_source_id(
                Path("ISUOG-Practice-Guidelines-intrapartum-ultrasound.pdf")
            )
            == "ISUOG_2018_intrapartum-ultrasound"
        )
        assert (
            canonical_source_id(
                Path("ISUOG-Practice-Guidelines-ultrasound-fetal-biometry-growth.pdf")
            )
            == "ISUOG_2019_fetal-biometry-growth"
        )
        assert (
            canonical_source_id(
                Path(
                    "ISUOG-Practice-Guidelines-invasive-procedures-prenatal-diagnosis.pdf"
                )
            )
            == "ISUOG_2016_invasive-prenatal-diagnosis"
        )

    def test_mislabeled_ispd_pdf_resolves_to_nipt_id(self) -> None:
        assert (
            canonical_source_id(Path("ISPD_2023_genome-wide-sequencing-position.pdf"))
            == "ISPD-nipt-2023"
        )
        assert "ISPD_2023_genome-wide-sequencing-position.pdf" in KNOWN_SOURCE_ISSUES


class TestSafeSlug:
    def test_chinese_only_falls_back_to_document(self) -> None:
        # CJK 字符被 NFKD/ASCII 过滤后无剩余内容
        assert safe_slug("产前 超声指南") == "document"

    def test_mixed_content_keeps_ascii(self) -> None:
        assert safe_slug("ISUOG 2022 指南") == "ISUOG-2022"

    def test_empty_falls_back_to_document(self) -> None:
        assert safe_slug("???") == "document"

    def test_length_is_capped(self) -> None:
        assert len(safe_slug("a" * 500)) == 120


class TestSourceIdFromText:
    def test_header_is_extracted(self) -> None:
        text = "SOURCE_ID: ISUOG-cns-2020\n\nbody"
        assert source_id_from_text(text) == "ISUOG-cns-2020"

    def test_missing_header_returns_none(self) -> None:
        assert source_id_from_text("no header here") is None


class TestExtractPage1Doi:
    @staticmethod
    def _corpus_text(*pages: str) -> str:
        header = "SOURCE_ID: x\nORIGINAL_FILE: x.pdf\nPDF_SHA256: ab\n"
        body = "\n\n".join(
            f"## Page {number}\n\n{content}"
            for number, content in enumerate(pages, start=1)
        )
        return f"{header}\n{body}\n"

    def test_doi_on_first_page_is_found(self) -> None:
        text = self._corpus_text(
            "Ultrasound Obstet Gynecol 2022; 59: 840–856\nDOI: 10.1002/uog.24888",
            "later page mentions 10.1002/other.99999",
        )
        assert extract_page1_doi(text) == "10.1002/uog.24888"

    def test_doi_on_later_pages_is_ignored(self) -> None:
        text = self._corpus_text("no doi here", "DOI: 10.1002/later.12345")
        assert extract_page1_doi(text) is None

    def test_missing_doi_returns_none(self) -> None:
        assert extract_page1_doi(self._corpus_text("nothing here")) is None

    def test_trailing_period_is_stripped(self) -> None:
        text = self._corpus_text("reference. DOI: 10.1002/uog.24888.")
        assert extract_page1_doi(text) == "10.1002/uog.24888"

    def test_fallback_without_page_markers(self) -> None:
        assert (
            extract_page1_doi("plain text with DOI: 10.1002/uog.99999 inside")
            == "10.1002/uog.99999"
        )


class TestExtractPdfText:
    def test_non_pdf_returns_empty(self, tmp_path: Path) -> None:
        fake = tmp_path / "fake.pdf"
        fake.write_text("not a pdf", encoding="utf-8")

        text, pages, warnings = extract_pdf_text(fake)

        assert text == ""
        assert pages == 0
        assert warnings  # pypdf 无法解析时记录告警而非崩溃
