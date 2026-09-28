"""Manual mutation layer for the conditions gauntlet (old-coder skill).

Applies each SPEC-listed mutant one at a time, runs the conditions test
files, and requires every mutant to be killed (pytest exit code 1).
Fail-closed: a pattern that does not match exactly once, a mutant that does
not change the file bytes, a restore mismatch, or any pytest exit code other
than 0/1 aborts the layer with a nonzero exit.

Execution proof per mutant: unique-pattern assertion before apply, byte-hash
delta assertion after apply, __pycache__ deletion before each run (guards
against same-size mutants sharing stale bytecode), and a byte-identical
restore check afterwards.

Usage:
    uv run python benchmark/report/old-coder/mutation_conditions.py
    uv run python benchmark/report/old-coder/mutation_conditions.py --negative-control
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EXTRACT = REPO_ROOT / "prenatal_rag" / "conditions" / "extract.py"
SCHEMA = REPO_ROOT / "prenatal_rag" / "conditions" / "schema.py"
GEST_AGE = REPO_ROOT / "prenatal_rag" / "applicability" / "gestational_age.py"
PYCACHE_DIRS = [
    REPO_ROOT / "prenatal_rag" / "conditions" / "__pycache__",
    REPO_ROOT / "prenatal_rag" / "applicability" / "__pycache__",
]
TEST_ARGS = [
    "uv",
    "run",
    "--with",
    "pytest",
    "--with",
    "hypothesis",
    "python",
    "-m",
    "pytest",
    "tests/test_prenatal_conditions.py",
    "tests/test_prenatal_conditions_extract.py",
    "tests/test_prenatal_conditions_materialize.py",
    "tests/test_prenatal_rag_client.py",
    "tests/test_prenatal_gestational_age.py",
    "tests/test_prenatal_gestational_age_unbounded.py",
    "-q",
]

MUTANTS: list[dict[str, str]] = [
    {
        "name": "M1-guard-days-zeroed",
        "file": str(EXTRACT),
        "old": "_GUARD_DAYS = 42  # viability 前的天数不构成孕周窗口",
        "new": "_GUARD_DAYS = 0  # viability 前的天数不构成孕周窗口",
    },
    {
        "name": "M2-serialize-separator",
        "file": str(SCHEMA),
        "old": 'return f"{lower}:{upper}"',
        "new": 'return f"{lower}-{upper}"',
    },
    {
        "name": "M3-before-boundary-inclusive",
        "file": str(EXTRACT),
        "old": "    return GaWindow.at_most(_day_component(match) - 1)",
        "new": "    return GaWindow.at_most(_day_component(match))",
    },
    {
        "name": "M4-upper-days-dropped",
        "file": str(EXTRACT),
        "old": 'upper = int(groups["b"]) * 7 + (int(groups["bd"]) if groups.get("bd") else 0)',
        "new": 'upper = int(groups["b"]) * 7',
    },
    {
        "name": "M5-merge-containment-strict",
        "file": str(EXTRACT),
        "old": "if any(\n            c.char_start <= start and end <= c.char_end for c in accepted\n        ):",
        "new": "if any(\n            c.char_start < start and end < c.char_end for c in accepted\n        ):",
    },
    {
        "name": "M6-point-day-off-by-one",
        "file": str(EXTRACT),
        "old": "    day = int(match.group(\"a\")) * 7\n    return GaWindow.closed(day, day)",
        "new": "    day = int(match.group(\"a\")) * 7 + 1\n    return GaWindow.closed(day, day)",
    },
    {
        "name": "M7-interval-upper-ge-strict",
        "file": str(GEST_AGE),
        "old": "    return b is not None and a >= b",
        "new": "    return b is not None and a > b",
    },
    {
        "name": "M8-guard-41",
        "file": str(EXTRACT),
        "old": "_GUARD_DAYS = 42  # viability 前的天数不构成孕周窗口",
        "new": "_GUARD_DAYS = 41  # viability 前的天数不构成孕周窗口",
    },
    {
        "name": "M9-guard-36",
        "file": str(EXTRACT),
        "old": "_GUARD_DAYS = 42  # viability 前的天数不构成孕周窗口",
        "new": "_GUARD_DAYS = 36  # viability 前的天数不构成孕周窗口",
    },
]

NEGATIVE_CONTROL: dict[str, str] = {
    "name": "C0-docstring-noop",
    "file": str(EXTRACT),
    "old": "；无 LLM、无网络、不依赖 ``benchmark.*``。",
    "new": "；无 LLM、无网络、不依赖 ``benchmark.*``（negative control）。",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clear_pycache() -> None:
    for pycache in PYCACHE_DIRS:
        if pycache.exists():
            shutil.rmtree(pycache)


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
        clear_pycache()
        proc = subprocess.run(
            TEST_ARGS,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=1200,
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
        help="Run the no-op control instead of the mutants; it must SURVIVE.",
    )
    args = parser.parse_args()

    if args.negative_control:
        outcome = run_mutant(NEGATIVE_CONTROL)
        print(f"negative-control {NEGATIVE_CONTROL['name']}: {outcome}")
        if outcome != "survived":
            print("NEGATIVE CONTROL FAILED: a no-op mutant must survive.")
            return 1
        return 0

    survived: list[str] = []
    for mutant in MUTANTS:
        outcome = run_mutant(mutant)
        print(f"{mutant['name']}: {outcome}")
        if outcome == "survived":
            survived.append(mutant["name"])
        elif outcome != "killed":
            return 1

    if survived:
        print(f"MUTATION LAYER FAILED: {len(survived)} survivor(s): {survived}")
        return 1
    print(f"MUTATION LAYER PASSED: {len(MUTANTS)}/{len(MUTANTS)} killed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
