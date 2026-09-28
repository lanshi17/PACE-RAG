"""Property layer: invariants of plan_family_duplicates (hypothesis, ephemeral).

I1  Two kept records never share (source_id, page1_doi) with a non-null DOI.
I2  Every drop references a kept record of the same source_id whose
    text_characters is greater than or equal to the dropped record's.
I3  Records with page1_doi None are never dropped.
I4  Conservation: candidates = kept + drops.
I5  Idempotence: re-planning the merged set yields no further drops.

Run by gauntlet.sh as:  uv run --with hypothesis python \
    benchmark/report/old-coder/property_plan_family.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from hypothesis import given, settings, strategies as st  # type: ignore[import-not-found]

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from benchmark.common.unified_corpus import plan_family_duplicates  # noqa: E402

record_spec = st.fixed_dictionaries(
    {
        "source_id": st.sampled_from(["s1", "s2", "s3"]),
        "status": st.sampled_from(
            ["ok", "ok", "ok", "partial", "duplicate", "error"]
        ),
        "doi": st.sampled_from(["10.1/a", "10.1/b", None, None]),
        "chars": st.integers(min_value=1, max_value=200),
    }
)


def build_documents(specs: list[dict[str, object]]) -> list[dict[str, object]]:
    documents: list[dict[str, object]] = []
    for index, spec in enumerate(specs):
        documents.append(
            {
                "source_id": spec["source_id"],
                "pdf_file": f"doc{index}.pdf",
                "pdf_sha256": f"hash{index}",
                "input_file": f"input/doc{index}.txt",
                "page_count": 1,
                "text_characters": spec["chars"],
                "status": spec["status"],
                "page1_doi": spec["doi"],
                "warnings": [],
            }
        )
    return documents


@settings(max_examples=300, deadline=None)
@given(specs=st.lists(record_spec, min_size=1, max_size=9))
def test_plan_family_invariants(specs: list[dict[str, object]]) -> None:
    documents = build_documents(specs)
    drops, _warnings = plan_family_duplicates(documents)  # type: ignore[arg-type]

    candidates = [
        doc for doc in documents if doc["status"] in {"ok", "partial"}  # type: ignore[operator]
    ]
    dropped_names = {drop["pdf_file"] for drop in drops}
    kept = [doc for doc in candidates if doc["pdf_file"] not in dropped_names]

    # I4 conservation.
    assert len(kept) + len(drops) == len(candidates)

    # I3 None-DOI records are never dropped.
    by_file = {doc["pdf_file"]: doc for doc in documents}
    for drop in drops:
        assert by_file[drop["pdf_file"]]["page1_doi"] is not None

    # I1 kept records unique per (source_id, page1_doi).
    seen = {
        (doc["source_id"], doc["page1_doi"])
        for doc in kept
        if doc["page1_doi"] is not None
    }
    doi_kept = [doc for doc in kept if doc["page1_doi"] is not None]
    assert len(seen) == len(doi_kept)

    # I2 drops reference a kept same-source record with >= characters.
    for drop in drops:
        original = by_file[drop["pdf_file"]]
        target = by_file[drop["duplicate_of"]]
        assert target["source_id"] == drop["source_id"] == original["source_id"]
        assert target["text_characters"] >= original["text_characters"]
        assert target["status"] in {"ok", "partial"}
        assert original["page1_doi"] is not None

    # I5 idempotence on the merged set.
    merged = [
        doc for doc in documents if doc["pdf_file"] not in dropped_names
    ]
    second_drops, _ = plan_family_duplicates(merged)  # type: ignore[arg-type]
    assert second_drops == []


def main() -> int:
    try:
        test_plan_family_invariants()
    except Exception as exc:  # noqa: BLE001
        print(f"property plan_family_duplicates: FALSIFIED - {exc}")
        return 1
    print("property plan_family_duplicates: invariants held (300 examples)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
