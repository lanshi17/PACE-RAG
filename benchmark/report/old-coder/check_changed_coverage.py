"""Changed-line coverage gate for the corpus-identity gauntlet.

Reads a pytest-cov JSON report and asserts every executable line of the
SPEC-listed functions is covered.  Fail-closed: an unreadable report, a
target missing from the report, or any missing line inside a target function
exits nonzero (1 = uncovered lines, 2 = report unreadable).

Usage (from repo root, after the coverage run):
    uv run python benchmark/report/old-coder/check_changed_coverage.py \
        coverage.json
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from benchmark.common.corpus import canonical_source_id, extract_page1_doi  # noqa: E402
from benchmark.common.unified_corpus import (  # noqa: E402
    plan_family_duplicates,
    prepare_corpus,
)

TARGETS: list[tuple[str, Any]] = [
    ("benchmark/common/corpus.py", extract_page1_doi),
    ("benchmark/common/corpus.py", canonical_source_id),
    ("benchmark/common/unified_corpus.py", plan_family_duplicates),
    ("benchmark/common/unified_corpus.py", prepare_corpus),
]


def function_range(func: Any) -> tuple[int, int]:
    lines, start = inspect.getsourcelines(func)
    return start, start + len(lines) - 1


def main() -> int:
    report_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "coverage.json"
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"coverage gate: cannot read {report_path}: {exc}")
        return 2

    files = data.get("files", {})
    if not files:
        print("coverage gate: report contains no files")
        return 2

    failures: list[str] = []
    for rel, func in TARGETS:
        entry = files.get(rel)
        if entry is None:
            matches = [key for key in files if key.endswith(rel)]
            entry = files[matches[0]] if len(matches) == 1 else None
        if entry is None:
            failures.append(f"{rel}: target missing from coverage report")
            continue
        start, end = function_range(func)
        missing = set(entry.get("missing_lines", []))
        bad = sorted(line for line in missing if start <= line <= end)
        if bad:
            failures.append(
                f"{func.__qualname__} ({rel}:{start}-{end}) missing lines: {bad}"
            )

    if failures:
        print("CHANGED-LINE COVERAGE GATE FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        "changed-line coverage gate: "
        f"{len(TARGETS)} target functions fully covered (no missing lines)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
