"""Changed-line coverage gate for the conditions gauntlet.

Reads a pytest-cov JSON report and asserts every executable line of the
SPEC-listed functions is covered.  Fail-closed: an unreadable report, a
target missing from the report, or any missing line inside a target function
exits nonzero (1 = uncovered lines, 2 = report unreadable).

Usage (from repo root, after the coverage run):
    uv run python benchmark/report/old-coder/check_changed_coverage_conditions.py \
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

from prenatal_rag.conditions.filter import (  # noqa: E402
    _classify_ga,
    _classify_token,
    _same,
    _window_direction,
    classify,
    classify_text,
    filter_chunks,
)
from prenatal_rag.conditions.query import (  # noqa: E402
    _cond_values,
    _ga_windows,
    parse_query_conditions,
)
from prenatal_rag.applicability.gestational_age import (  # noqa: E402
    GestationalAgeInterval,
    _le,
    _lower_le,
    _upper_ge,
    apply_ga_interval,
    apply_ga_point,
)
from prenatal_rag.conditions.extract import (  # noqa: E402
    ConditionExtractor,
    _build_closed,
    _fold,
    _plausible,
    extract_conditions,
    index_conditions,
)
from prenatal_rag.conditions.schema import GaWindow  # noqa: E402

TARGETS: list[tuple[str, Any]] = [
    ("prenatal_rag/conditions/extract.py", _fold),
    ("prenatal_rag/conditions/extract.py", _build_closed),
    ("prenatal_rag/conditions/extract.py", _plausible),
    ("prenatal_rag/conditions/extract.py", extract_conditions),
    ("prenatal_rag/conditions/extract.py", index_conditions),
    ("prenatal_rag/conditions/extract.py", ConditionExtractor.extract),
    ("prenatal_rag/conditions/extract.py", ConditionExtractor._merge_condition),
    ("prenatal_rag/conditions/extract.py", ConditionExtractor._extract_ga),
    ("prenatal_rag/conditions/extract.py", ConditionExtractor._extract_tokens),
    ("prenatal_rag/conditions/schema.py", GaWindow.serialize),
    ("prenatal_rag/conditions/schema.py", GaWindow.parse),
    ("prenatal_rag/conditions/schema.py", GaWindow.overlaps),
    ("prenatal_rag/conditions/schema.py", GaWindow.covers),
    ("prenatal_rag/applicability/gestational_age.py", _lower_le),
    ("prenatal_rag/applicability/gestational_age.py", _upper_ge),
    ("prenatal_rag/applicability/gestational_age.py", _le),
    ("prenatal_rag/applicability/gestational_age.py", apply_ga_point),
    ("prenatal_rag/applicability/gestational_age.py", apply_ga_interval),
    ("prenatal_rag/conditions/filter.py", _window_direction),
    ("prenatal_rag/conditions/filter.py", _same),
    ("prenatal_rag/conditions/filter.py", _classify_ga),
    ("prenatal_rag/conditions/filter.py", _classify_token),
    ("prenatal_rag/conditions/filter.py", classify),
    ("prenatal_rag/conditions/filter.py", classify_text),
    ("prenatal_rag/conditions/filter.py", filter_chunks),
    ("prenatal_rag/conditions/query.py", _ga_windows),
    ("prenatal_rag/conditions/query.py", _cond_values),
    ("prenatal_rag/conditions/query.py", parse_query_conditions),
]


def _interval_methods() -> list[tuple[str, Any]]:
    names = [
        "_effective_bounds",
        "contains_point",
        "covers",
        "overlaps",
        "parse",
        "parse_weeks",
    ]
    return [
        ("prenatal_rag/applicability/gestational_age.py", getattr(GestationalAgeInterval, name))
        for name in names
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
    targets = TARGETS + _interval_methods()
    for rel, func in targets:
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
                f"{getattr(func, '__qualname__', func)} ({rel}:{start}-{end})"
                f" missing lines: {bad}"
            )

    if failures:
        print("CHANGED-LINE COVERAGE GATE FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        "changed-line coverage gate: "
        f"{len(targets)} target functions fully covered (no missing lines)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
