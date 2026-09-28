"""Real-execution layer for the conditions gauntlet (old-coder skill).

Runs the extractor + store condition index over a TEMP COPY of the real
evidence store (gitignored, 26 ingested documents), asserting sane corpus-level
results.  Side-effect-safe: the original store is never written.

Usage:
    uv run python benchmark/report/old-coder/real_execution_conditions.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from prenatal_rag.conditions import (  # noqa: E402
    ConditionType,
    extract_conditions,
)
from prenatal_rag.evidence_store.ingest import (  # noqa: E402
    DEFAULT_EVIDENCE_STORE_DIR,
)
from prenatal_rag.evidence_store.store import EvidenceStore  # noqa: E402


def main() -> int:
    source = DEFAULT_EVIDENCE_STORE_DIR
    if not (source / "evidence.sqlite3").is_file():
        print(f"real-execution: real store missing at {source}")
        return 2

    with tempfile.TemporaryDirectory(prefix="pace-real-exec-") as tmp:
        copy_root = Path(tmp) / "evidence_store"
        shutil.copytree(source, copy_root)
        store = EvidenceStore(copy_root)
        try:
            chunks = list(store.iter_chunks())
            source_ids = {chunk.source_id for chunk in chunks}
            chunk_rows = len(chunks)

            started = time.perf_counter()
            written = store.build_condition_index()
            elapsed = time.perf_counter() - started

            counts: dict[str, int] = {}
            nipt_population: list[tuple[str, str]] = []
            for condition in store.iter_conditions():
                counts[condition.condition_type.value] = (
                    counts.get(condition.condition_type.value, 0) + 1
                )
                if (
                    "nipt" in condition.source_id.lower()
                    and condition.condition_type is ConditionType.POPULATION
                    and len(nipt_population) < 3
                ):
                    nipt_population.append((condition.matched_text, condition.value))

            print(
                json.dumps(
                    {
                        "source_documents": len(source_ids),
                        "chunk_anchors": chunk_rows,
                        "conditions_written": written,
                        "by_type": counts,
                        "elapsed_seconds": round(elapsed, 3),
                        "nipt_population_sample": nipt_population,
                    },
                    ensure_ascii=False,
                    indent=1,
                )
            )

            failures: list[str] = []
            if len(source_ids) != 26:
                failures.append(f"expected 26 documents, got {len(source_ids)}")
            if chunk_rows == 0:
                failures.append("no chunk anchors found")
            if counts.get(ConditionType.GESTATIONAL_AGE.value, 0) == 0:
                failures.append("zero gestational_age conditions across corpus")
            if counts.get(ConditionType.POPULATION.value, 0) == 0:
                failures.append("zero population conditions across corpus")
            if counts.get(ConditionType.TECHNIQUE.value, 0) == 0:
                failures.append("zero technique conditions across corpus")
            if elapsed > 60:
                failures.append(
                    f"indexing too slow: {elapsed:.1f}s for {chunk_rows} chunks"
                )
            # 抽查：批次文档验证过的 ISPD-nipt-2023 "singleton pregnancies" 命中。
            if not any("singleton" in matched for matched, _ in nipt_population):
                failures.append("expected 'singleton' hit in ISPD-nipt document sample")
            probe = extract_conditions(
                "screening between 11+0 and 13+6 weeks for monochorionic twins",
                anchor_id=-1,
                source_id="probe",
                base_offset=0,
            )
            windows = [
                c.value
                for c in probe
                if c.condition_type is ConditionType.GESTATIONAL_AGE
            ]
            if "77:97" not in windows:
                failures.append("live probe failed to recover the 11+0–13+6 window")
            if failures:
                print("REAL-EXECUTION FAILED:")
                for failure in failures:
                    print(f"  - {failure}")
                return 1
            print("REAL-EXECUTION PASSED")
            return 0
        finally:
            store.close()


if __name__ == "__main__":
    sys.exit(main())
