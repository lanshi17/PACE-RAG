"""BM25 召回通道（prenatal_rag.retrieval.bm25）测试。"""

from __future__ import annotations

import pytest

from prenatal_rag.evidence_store import EvidenceStore, ingest_unified_corpus
from prenatal_rag.retrieval import Bm25Index, tokenize


class TestTokenize:
    def test_english_words_lowercased(self) -> None:
        assert tokenize("Nuchal Translucency 11+0") == ["nuchal", "translucency", "11", "0"]

    def test_cjk_single_chars(self) -> None:
        assert tokenize("胎儿心脏") == ["胎", "儿", "心", "脏"]

    def test_mixed_query(self) -> None:
        assert tokenize("NT测量 nuchal") == ["nt", "测", "量", "nuchal"]


class TestBm25Index:
    @pytest.fixture()
    def index(self) -> Bm25Index:
        return Bm25Index.build(
            [
                (1, "doc-a", "nuchal translucency measurement at 11 weeks"),
                (2, "doc-b", "fetal cardiac screening includes nuchal translucency views"),
                (3, "doc-c", "twin pregnancy chorionicity and growth monitoring"),
            ]
        )

    def test_build_counts_documents(self, index: Bm25Index) -> None:
        assert len(index) == 3

    def test_duplicate_chunk_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="chunk_id 重复"):
            Bm25Index.build([(1, "a", "x"), (1, "b", "y")])

    def test_relevant_document_ranks_first(self, index: Bm25Index) -> None:
        results = index.search("chorionicity", k=3)
        assert results[0].source_id == "doc-c"
        assert results[0].rank == 1

    def test_ranking_is_ordered_and_capped(self, index: Bm25Index) -> None:
        results = index.search("nuchal translucency", k=2)
        assert len(results) == 2
        assert [r.rank for r in results] == [1, 2]
        assert results[0].score >= results[1].score
        # doc-a 更短（长度归一化），应排在同样含两词的 doc-b 之前
        assert results[0].source_id == "doc-a"

    def test_no_match_returns_empty(self, index: Bm25Index) -> None:
        assert index.search("zanzibar", k=5) == []

    def test_empty_query_returns_empty(self, index: Bm25Index) -> None:
        assert index.search("", k=5) == []
        assert index.search("!!!", k=5) == []

    def test_zero_k_returns_empty(self, index: Bm25Index) -> None:
        assert index.search("nuchal", k=0) == []

    def test_deterministic_tie_break_by_chunk_id(self) -> None:
        index = Bm25Index.build(
            [(7, "d1", "alpha beta"), (3, "d2", "alpha beta")]
        )
        results = index.search("alpha", k=5)
        assert [r.chunk_id for r in results] == [3, 7]

    def test_empty_index(self) -> None:
        assert Bm25Index.build([]).search("anything") == []


class TestFromStore:
    def test_index_built_from_evidence_store(self, tmp_path) -> None:
        corpus_dir = tmp_path / "corpus"
        (corpus_dir / "input").mkdir(parents=True)
        (corpus_dir / "corpus_manifest.json").write_text(
            '{"documents": [{"source_id": "Doc-A", "status": "ok",'
            ' "input_file": "Doc-A.txt", "page1_doi": null,'
            ' "pdf_sha256": null, "page_count": 1,'
            ' "text_characters": 10, "warnings": []}]}',
            encoding="utf-8",
        )
        (corpus_dir / "input" / "Doc-A.txt").write_text(
            "SOURCE_ID: Doc-A\n\n"
            "## Page 1\n\n"
            "chorionicity determines twin surveillance intervals\n\n",
            encoding="utf-8",
        )
        store = EvidenceStore(tmp_path / "store")
        ingest_unified_corpus(corpus_dir, store)
        index = Bm25Index.from_store(store)
        results = index.search("chorionicity twin", k=5)
        assert results
        assert results[0].source_id == "Doc-A"
        assert all(r.chunk_id > 0 for r in results)
