"""Manual mutation layer for the corpus-identity gauntlet (old-coder skill).

Applies each SPEC-listed mutant one at a time, runs the corpus test files,
and requires every mutant to be killed (pytest exit code 1).  Fail-closed:
a pattern that does not match exactly once, a mutant that does not change the
file bytes, a restore mismatch, or any pytest exit code other than 0/1 aborts
the layer with a nonzero exit.

Execution proof per mutant (gauntlet.md): unique-pattern assertion before
apply, byte-hash delta assertion after apply, ``__pycache__`` deletion before
each run (guards against same-size mutants sharing stale bytecode), and a
byte-identical restore check afterwards.

Usage:
    uv run python benchmark/report/old-coder/mutation_corpus_identity.py
    uv run python benchmark/report/old-coder/mutation_corpus_identity.py \
        --negative-control
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS = REPO_ROOT / "benchmark" / "common" / "corpus.py"
UNIFIED = REPO_ROOT / "benchmark" / "common" / "unified_corpus.py"
PYCACHE = REPO_ROOT / "benchmark" / "common" / "__pycache__"
TEST_ARGS = [
    "uv",
    "run",
    "pytest",
    "tests/test_common_corpus.py",
    "tests/test_common_unified_corpus.py",
    "-q",
    "-x",
]

MUTANTS: list[dict[str, str]] = [
    {
        "name": "M1-keep-smaller-copy",
        "file": str(UNIFIED),
        "old": 'key=lambda record: (-record["text_characters"], record["pdf_file"]),',
        "new": 'key=lambda record: (record["text_characters"], record["pdf_file"]),',
    },
    {
        "name": "M2-ignore-page1-doi",
        "file": str(UNIFIED),
        "old": "by_doi.setdefault(doi, []).append(record)",
        "new": "by_doi.setdefault(source_id, []).append(record)",
    },
    {
        "name": "M3-duplicates-become-candidates",
        "file": str(UNIFIED),
        "old": 'candidates = [\n        record for record in documents if record["status"] in {"ok", "partial"}\n    ]',
        "new": 'candidates = [\n        record\n        for record in documents\n        if record["status"] in {"ok", "partial", "duplicate"}\n    ]',
    },
    {
        "name": "M4-doi-search-whole-text",
        "file": str(CORPUS),
        "old": "doi = DOI_RE.search(page1)",
        "new": "doi = DOI_RE.search(text)",
    },
    {
        "name": "M5-keep-trailing-period",
        "file": str(CORPUS),
        "old": 'return doi.group(0).rstrip(".") if doi else None',
        "new": "return doi.group(0) if doi else None",
    },
    {
        "name": "M6-prune-kept-files",
        "file": str(UNIFIED),
        "old": "if txt_path.name not in referenced_inputs:",
        "new": "if txt_path.name in referenced_inputs:",
    },
]

NEGATIVE_CONTROL: dict[str, str] = {
    "name": "C0-docstring-noop",
    "file": str(UNIFIED),
    "old": "Decide same-article duplicate drops from page-1 DOI identity.",
    "new": "Decide same-article duplicate drops from page-1 DOI identity (manual).",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_mutant(mutant: dict[str, str]) -> str:
    path = Path(mutant["file"])
    original = path.read_bytes()
    text = original.decode("utf-8")

    count = text.count(mutant["old"])
    if count != 1:
        print(f"    PATTERN-ERROR: {mutant['name']} matches {count} times")
        return "pattern-error"

    path.write_text(text.replace(mutant["old"], mutant["new"]), encoding="utf-8")
    try:
        mutated = path.read_bytes()
        if digest(mutated) == digest(original):
            print(f"    PATTERN-ERROR: {mutant['name']} did not change the file")
            return "pattern-error"
        if PYCACHE.exists():
            shutil.rmtree(PYCACHE)
        proc = subprocess.run(
            TEST_ARGS,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=600,
        )
    finally:
        path.write_bytes(original)
        if path.read_bytes() != original:
            print(f"    RESTORE-ERROR: {mutant['name']} left the tree mutated")
            return "restore-error"

    if proc.returncode == 1:
        return "killed"
    if proc.returncode == 0:
        return "survived"
    print(f"    UNEXPECTED-RC: pytest exit {proc.returncode}")
    return "error"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--negative-control",
        action="store_true",
        help="prepend the behavior-preserving control mutant (must SURVIVE)",
    )
    args = parser.parse_args()

    mutants = ([NEGATIVE_CONTROL] if args.negative_control else []) + MUTANTS
    results: dict[str, str] = {}
    for mutant in mutants:
        print(f"  mutant {mutant['name']} ...")
        results[mutant["name"]] = run_mutant(mutant)

    print("\nmutation results:")
    failures: list[str] = []
    for name, status in results.items():
        print(f"  {name:<34} {status}")
        expected = "survived" if name == NEGATIVE_CONTROL["name"] else "killed"
        if status != expected:
            failures.append(name)

    if failures:
        print(f"\nMUTATION LAYER FAILED: {failures}")
        return 1
    if args.negative_control:
        print("\nnegative control behaved as expected (survived); real mutants killed")
    else:
        print(f"\nmanual mutation: {len(MUTANTS)}/{len(MUTANTS)} killed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
