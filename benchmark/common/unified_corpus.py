"""Unified corpus preparation shared by all baselines.

Both baselines used to extract the same PDFs into their own ``input/``
directories with slightly different headers and duplicate rules.  The unified
layout is::

    benchmark/data/corpus/input/       # single source of truth for text
    benchmark/data/corpus/corpus_manifest.json

Each baseline keeps its own *index* artifacts (graph, vectors, storage) under
``benchmark/data/<baseline>/`` but reads the identical text files, so the two
baselines are guaranteed to be evaluated against the same corpus.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmark.common.corpus import (
    KNOWN_SOURCE_ISSUES,
    MANIFEST_NAME,
    canonical_source_id,
    extract_page1_doi,
    extract_pdf_text,
    now_iso,
    safe_slug,
    sha256_file,
    source_id_from_text,
    write_manifest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_DIR = REPOSITORY_ROOT / "benchmark" / "data" / "raw"
DEFAULT_CORPUS_DIR = REPOSITORY_ROOT / "benchmark" / "data" / "corpus"


def corpus_input_dir(corpus_dir: Path | None = None) -> Path:
    """Return the unified input directory (creating it on demand)."""
    path = (corpus_dir or DEFAULT_CORPUS_DIR).resolve() / "input"
    path.mkdir(parents=True, exist_ok=True)
    return path


def corpus_manifest_path(corpus_dir: Path | None = None) -> Path:
    return (corpus_dir or DEFAULT_CORPUS_DIR).resolve() / MANIFEST_NAME


def load_corpus_manifest(corpus_dir: Path | None = None) -> dict[str, Any]:
    """Load the unified manifest, falling back to an empty one."""
    path = corpus_manifest_path(corpus_dir)
    if not path.is_file():
        return {"documents": []}
    return json.loads(path.read_text(encoding="utf-8"))


def plan_family_duplicates(
    documents: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Decide same-article duplicate drops from page-1 DOI identity.

    Two PDFs may hold the same article with different bytes (publisher layout
    vs scanned reprint).  When their page-1 DOIs match, only the copy with the
    most extracted characters is kept; the others become duplicate records
    referencing the kept text.  Source groups that still hold several records
    with diverging or missing DOIs are reported as unresolved warnings instead
    of being merged.  Byte-identical duplicates (status ``duplicate``) and
    failures (``error``) are never candidates.
    """
    candidates = [
        record for record in documents if record["status"] in {"ok", "partial"}
    ]
    by_source: dict[str, list[dict[str, Any]]] = {}
    for record in candidates:
        by_source.setdefault(record["source_id"], []).append(record)

    duplicate_records: list[dict[str, Any]] = []
    warnings: list[tuple[str, str]] = []
    for source_id in sorted(by_source):
        group = by_source[source_id]
        by_doi: dict[str, list[dict[str, Any]]] = {}
        for record in group:
            doi = record.get("page1_doi")
            if doi:
                by_doi.setdefault(doi, []).append(record)
        dropped_names: set[str] = set()
        for doi in sorted(by_doi):
            members = by_doi[doi]
            if len(members) < 2:
                continue
            ranked = sorted(
                members,
                key=lambda record: (-record["text_characters"], record["pdf_file"]),
            )
            kept = ranked[0]
            for dropped in ranked[1:]:
                dropped_names.add(dropped["pdf_file"])
                duplicate_records.append(
                    {
                        "source_id": source_id,
                        "pdf_file": dropped["pdf_file"],
                        "pdf_sha256": dropped["pdf_sha256"],
                        "input_file": kept["input_file"],
                        "page_count": kept["page_count"],
                        "text_characters": kept["text_characters"],
                        "status": "duplicate",
                        "duplicate_of": kept["pdf_file"],
                        "duplicate_reason": "same-page1-doi",
                        "page1_doi": doi,
                        "warnings": [],
                    }
                )
        remaining = [
            record for record in group if record["pdf_file"] not in dropped_names
        ]
        distinct_dois = {record.get("page1_doi") for record in remaining}
        if len(remaining) > 1 and (None in distinct_dois or len(distinct_dois) > 1):
            warnings.append(
                (
                    source_id,
                    f"{len(remaining)} 个同 source_id 版本无法用页首 DOI 归并 "
                    f"(page1_doi: {sorted(str(doi) for doi in distinct_dois)})",
                )
            )
    return duplicate_records, warnings


def prepare_corpus(
    *,
    raw_dir: Path,
    corpus_dir: Path | None = None,
    dataset_path: Path | None = None,
    questions: list[Any] | None = None,
) -> dict[str, Any]:
    """Extract every PDF once into the unified corpus directory.

    The output filename embeds the PDF's sha256 so a changed PDF produces a new
    file instead of silently mutating the shared corpus.  Duplicates are
    recorded but not re-indexed: byte-identical copies by sha256, and
    same-article copies whose page-1 DOI matches (the copy with the most
    extracted text is kept).  Kept texts are written only after dedup, so
    dropped copies never touch disk.  Texts under ``input/`` that no manifest
    document references are pruned; ``pruned_text_count`` only counts
    orphans that predate this run.
    """
    raw_dir = raw_dir.resolve()
    corpus_root = (corpus_dir or DEFAULT_CORPUS_DIR).resolve()
    input_dir = corpus_input_dir(corpus_root)

    if not raw_dir.is_dir():
        raise FileNotFoundError(f"原始语料目录不存在: {raw_dir}")

    pdf_paths = sorted(
        (
            path
            for path in raw_dir.iterdir()
            if path.is_file() and path.suffix.casefold() == ".pdf"
        ),
        key=lambda path: path.name.casefold(),
    )
    if not pdf_paths:
        raise FileNotFoundError(f"原始语料目录中没有 PDF: {raw_dir}")

    if questions is None and dataset_path is not None:
        from benchmark.qa import load_questions

        questions = load_questions(dataset_path)

    documents: list[dict[str, Any]] = []
    preexisting_texts = {path.name for path in input_dir.glob("*.txt")}
    extracted_documents: dict[tuple[str, str], dict[str, Any]] = {}
    pending_bodies: dict[str, str] = {}
    for index, pdf_path in enumerate(pdf_paths, start=1):
        pdf_hash = sha256_file(pdf_path)
        source_id = canonical_source_id(pdf_path)
        output_name = f"{safe_slug(source_id)}--{pdf_hash[:12]}.txt"
        output_path = input_dir / output_name

        duplicate = extracted_documents.get((source_id, pdf_hash))
        if duplicate is not None:
            print(
                f"[{index}/{len(pdf_paths)}] 跳过重复文件 {pdf_path.name}", flush=True
            )
            documents.append(
                {
                    "source_id": source_id,
                    "pdf_file": pdf_path.name,
                    "pdf_sha256": pdf_hash,
                    "input_file": duplicate["input_file"],
                    "page_count": duplicate["page_count"],
                    "text_characters": duplicate["text_characters"],
                    "status": "duplicate",
                    "duplicate_of": duplicate["pdf_file"],
                    "duplicate_reason": "identical-bytes",
                    "page1_doi": duplicate["page1_doi"],
                    "warnings": [],
                }
            )
            continue

        print(f"[{index}/{len(pdf_paths)}] 提取 {pdf_path.name}", flush=True)
        known_issue_warnings: list[str] = []
        if pdf_path.name in KNOWN_SOURCE_ISSUES:
            known_issue_warnings.append(KNOWN_SOURCE_ISSUES[pdf_path.name])

        try:
            body, page_count, page_warnings = extract_pdf_text(pdf_path)
            if not body.strip():
                raise ValueError("未提取到可索引文本")

            status = "partial" if page_warnings else "ok"
            document = {
                "source_id": source_id,
                "pdf_file": pdf_path.name,
                "pdf_sha256": pdf_hash,
                "input_file": str(output_path.relative_to(corpus_root)),
                "page_count": page_count,
                "text_characters": len(body),
                "status": status,
                "page1_doi": extract_page1_doi(body),
                "warnings": [*page_warnings, *known_issue_warnings],
            }
            documents.append(document)
            pending_bodies[pdf_path.name] = body
            extracted_documents[(source_id, pdf_hash)] = document
        except Exception as exc:  # noqa: BLE001
            documents.append(
                {
                    "source_id": source_id,
                    "pdf_file": pdf_path.name,
                    "pdf_sha256": pdf_hash,
                    "input_file": None,
                    "page_count": 0,
                    "text_characters": 0,
                    "status": "error",
                    "page1_doi": None,
                    "warnings": [f"{type(exc).__name__}: {exc}"],
                }
            )

    duplicate_records, family_warnings = plan_family_duplicates(documents)
    if duplicate_records:
        family_dropped = {record["pdf_file"] for record in duplicate_records}
        documents = [
            record
            for record in documents
            if record["pdf_file"] not in family_dropped
            or record["status"] not in {"ok", "partial"}
        ]
        documents.extend(duplicate_records)
    for warning_source_id, message in family_warnings:
        for record in documents:
            if (
                record["source_id"] == warning_source_id
                and record["status"] in {"ok", "partial"}
            ):
                record["warnings"] = [*record["warnings"], message]
    documents.sort(key=lambda record: record["pdf_file"].casefold())

    # Materialize kept texts only after dedup: dropped copies never touch disk.
    for record in documents:
        if record["status"] not in {"ok", "partial"}:
            continue
        body = pending_bodies.pop(record["pdf_file"])
        header = "\n".join(
            [
                f"SOURCE_ID: {record['source_id']}",
                f"ORIGINAL_FILE: {record['pdf_file']}",
                f"PDF_SHA256: {record['pdf_sha256']}",
            ]
        )
        (input_dir / Path(record["input_file"]).name).write_text(
            f"{header}\n\n{body}\n", encoding="utf-8"
        )

    referenced_inputs = {
        Path(record["input_file"]).name
        for record in documents
        if record.get("input_file")
    }
    pruned_text_count = 0
    for txt_path in sorted(input_dir.glob("*.txt")):
        if txt_path.name not in referenced_inputs:
            txt_path.unlink()
            if txt_path.name in preexisting_texts:
                pruned_text_count += 1
                print(f"移除失效语料文本 {txt_path.name}", flush=True)

    successful_source_ids = {
        item["source_id"] for item in documents if item["status"] in {"ok", "partial"}
    }
    manifest: dict[str, Any] = {
        "created_at": now_iso(),
        "raw_dir": str(raw_dir),
        "corpus_dir": str(corpus_root),
        "pdf_count": len(pdf_paths),
        "indexed_document_count": sum(
            item["status"] in {"ok", "partial"} for item in documents
        ),
        "duplicate_count": sum(item["status"] == "duplicate" for item in documents),
        "error_count": sum(item["status"] == "error" for item in documents),
        "partial_count": sum(item["status"] == "partial" for item in documents),
        "pruned_text_count": pruned_text_count,
        "documents": documents,
    }
    if questions is not None:
        manifest["dataset_source_coverage"] = source_coverage(
            questions, successful_source_ids
        )
    write_manifest(corpus_root, manifest)
    return manifest


def source_coverage(
    questions: list[Any],
    available_source_ids: set[str],
) -> dict[str, Any]:
    """Check how many questions' gold sources exist in the corpus."""
    required = {
        source.guide for question in questions for source in question.gold_sources
    }
    fully_covered = 0
    uncovered_questions: list[str] = []
    for question in questions:
        question_sources = {source.guide for source in question.gold_sources}
        if question_sources <= available_source_ids:
            fully_covered += 1
        else:
            uncovered_questions.append(question.question_id)

    return {
        "required_source_ids": sorted(required),
        "available_source_ids": sorted(required & available_source_ids),
        "missing_source_ids": sorted(required - available_source_ids),
        "fully_covered_questions": fully_covered,
        "total_questions": len(questions),
        "uncovered_question_ids": uncovered_questions,
    }


def read_corpus_documents(
    corpus_dir: Path | None = None,
) -> list[tuple[str, Path, str]]:
    """Read unified corpus texts as ``(source_id, path, text)`` tuples."""
    input_dir = corpus_input_dir(corpus_dir)
    documents: list[tuple[str, Path, str]] = []
    for path in sorted(input_dir.glob("*.txt"), key=lambda p: p.name.casefold()):
        text = path.read_text(encoding="utf-8")
        source_id = source_id_from_text(text) or path.stem
        documents.append((source_id, path, text))
    if not documents:
        raise FileNotFoundError(f"统一语料目录中没有文本文件: {input_dir}")
    return documents


__all__ = [
    "DEFAULT_CORPUS_DIR",
    "DEFAULT_RAW_DIR",
    "corpus_input_dir",
    "corpus_manifest_path",
    "load_corpus_manifest",
    "prepare_corpus",
    "read_corpus_documents",
    "source_coverage",
]
