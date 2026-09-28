"""Real-execution layer: run prepare_corpus on the actual repository corpus.

Asserts the audited end state (26 indexed articles, 7 duplicate records,
0 errors, 26 text files).  Idempotent: safe to re-run; the manifest timestamp
changes, nothing else does.

Usage:  uv run python benchmark/report/old-coder/real_execution_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from benchmark.common.unified_corpus import DEFAULT_RAW_DIR, prepare_corpus  # noqa: E402


def main() -> int:
    manifest = prepare_corpus(raw_dir=DEFAULT_RAW_DIR)
    txt_files = list((REPO_ROOT / "benchmark/data/corpus/input").glob("*.txt"))
    checks = {
        "indexed_document_count == 26": manifest["indexed_document_count"] == 26,
        "duplicate_count == 7": manifest["duplicate_count"] == 7,
        "error_count == 0": manifest["error_count"] == 0,
        "pruned_text_count == 0": manifest["pruned_text_count"] == 0,
        "input txt files == 26": len(txt_files) == 26,
    }
    for name, ok in checks.items():
        print(f"  {name}: {'ok' if ok else 'FAIL'}")
    if not all(checks.values()):
        print("real-execution layer FAILED")
        return 1
    print("real-execution: prepare_corpus ran on the real 33-PDF corpus")
    return 0


if __name__ == "__main__":
    sys.exit(main())
