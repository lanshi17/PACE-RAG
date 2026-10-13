"""Validate the public R2 authoring scaffold without model or network calls.

This checks draft structure and optional local source integrity. It is not a
clinical, semantic leakage, access-control, or confirmatory-freeze validator.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import unicodedata

REPO = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE = REPO / "benchmark/qa/dataset/pace_conditions_v1"
FILES = {
    "tasks": "task_blueprint.json",
    "dev": "dev_families.json",
    "evidence": "evidence_candidates.json",
    "hidden": "hidden_allocation.json",
    "legacy": "legacy_exposure_inventory.json",
}
STATUSES = {
    "tasks": "planning",
    "dev": "public_unreviewed_development_drafts",
    "evidence": "development_evidence_candidates",
    "hidden": "allocation_only_not_hidden_dataset",
    "legacy": "exposure_inventory_not_semantic_dedup",
}


def load_bundle(directory: Path) -> dict[str, Any]:
    return {
        key: json.loads((directory / filename).read_text(encoding="utf-8"))
        for key, filename in FILES.items()
    }


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).casefold().split())


def _local_path(repo: Path, value: str, prefix: str) -> Path:
    path = (repo / value).resolve()
    path.relative_to((repo / prefix).resolve())
    return path


def validate_bundle(
    bundle: dict[str, Any], *, repo: Path = REPO, check_corpus: bool = False
) -> dict[str, Any]:
    """Return errors and actual counts; never certify that hidden data is ready."""
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    for key, status in STATUSES.items():
        require(bundle[key]["schema_version"] == "r2-scaffold-v1", f"{key}: schema")
        require(bundle[key]["status"] == status, f"{key}: must remain public draft")

    tasks = bundle["tasks"]["tasks"]
    task_ids = {task["task_id"] for task in tasks}
    require(task_ids == {"GA", "PM", "UN", "VC", "CE"}, "five task categories required")
    require(len(tasks) == len(task_ids), "duplicate task category")
    require(bundle["tasks"]["hidden_gold_frozen"] is False, "hidden gold not frozen")
    require(bundle["tasks"]["independent_unit"] == "scenario_family", "family inference unit")
    dev = bundle["dev"]["records"]
    evidence = bundle["evidence"]["records"]
    evidence_ids = {item["evidence_id"] for item in evidence}
    require(len(evidence) == len(evidence_ids), "duplicate evidence ID")

    legacy_ids: set[str] = set()
    legacy_texts: set[str] = set()
    for item in bundle["legacy"]["records"]:
        path = _local_path(repo, item["path"], "benchmark/qa/dataset")
        raw = path.read_bytes()
        require(_digest(raw) == item["sha256"], f"legacy fingerprint changed: {path.name}")
        records = json.loads(raw)
        ids = [row["question_id"] for row in records]
        require(ids == item["question_ids"], f"legacy IDs changed: {path.name}")
        require(len(records) == item["question_count"], f"legacy count: {path.name}")
        legacy_ids.update(ids)
        legacy_texts.update(_normalize(row["question"]) for row in records)

    family_ids: set[str] = set()
    template_ids: set[str] = set()
    question_ids: set[str] = set()
    question_texts: set[str] = set()
    drafted = 0
    for family in dev:
        fid = family["scenario_family_id"]
        template = family["clinical_template_id"]
        require(fid not in family_ids, f"duplicate family: {fid}")
        require(template not in template_ids, f"duplicate development template: {template}")
        family_ids.add(fid)
        template_ids.add(template)
        require(family["task_id"] in task_ids, f"unknown task: {fid}")
        require(family["split"] == "dev", f"public family cannot be hidden: {fid}")
        require(family["gold"] is None, f"draft gold must be empty: {fid}")
        require(family["review_records"] == [], f"draft review status changed: {fid}")
        require(family["template_overlap_review"] == "pending", f"overlap review pending: {fid}")
        require(
            family["exposure"] == "public_development_never_promote_to_hidden",
            f"exposure policy: {fid}",
        )
        require(set(family["candidate_evidence_ids"]) <= evidence_ids, f"missing evidence: {fid}")
        if family["status"] == "blocked_missing_bilateral_sources":
            require(family["variants"] == [], f"blocked family has questions: {fid}")
            require(family["candidate_evidence_ids"] == [], f"blocked source state: {fid}")
            continue
        require(family["status"] == "draft_for_pilot", f"unrecognized draft status: {fid}")
        drafted += 1
        variants = {v["variant_type"]: v for v in family["variants"]}
        require(
            set(variants) == {"base", "condition_change", "invariant_control"}
            and len(family["variants"]) == 3,
            f"three distinct variants required: {fid}",
        )
        if set(variants) != {"base", "condition_change", "invariant_control"}:
            continue
        base = variants["base"]["known_conditions"]
        changed = variants["condition_change"]["known_conditions"]
        invariant = variants["invariant_control"]["known_conditions"]
        changed_keys = {key for key in base.keys() | changed.keys() if base.get(key) != changed.get(key)}
        require(base.keys() == changed.keys(), f"condition fields differ: {fid}")
        require(changed_keys == {family["change_axis"]}, f"not a single condition change: {fid}")
        require(base == invariant, f"invariant control changed conditions: {fid}")
        require(bool(family["candidate_evidence_ids"]), f"no candidate evidence: {fid}")
        for variant in family["variants"]:
            qid = variant["draft_question_id"]
            text = _normalize(variant["question"])
            require(bool(text), f"empty draft question: {qid}")
            require(qid not in question_ids | legacy_ids, f"duplicate question ID: {qid}")
            require(text not in question_texts | legacy_texts, f"exact question reuse: {qid}")
            question_ids.add(qid)
            question_texts.add(text)

    hidden = bundle["hidden"]
    require(hidden["gold_frozen"] is False, "hidden allocation cannot be frozen")
    require(hidden["actual_assigned_families"] == 0, "hidden family assignment is private")
    require(hidden["actual_authored_questions"] == 0, "no hidden questions authored here")
    slot_ids: set[str] = set()
    for slot in hidden["slots"]:
        sid = slot["allocation_slot_id"]
        require(sid not in slot_ids, f"duplicate allocation slot: {sid}")
        slot_ids.add(sid)
        expected = {
            "allocation_slot_id": sid, "task_id": slot["task_id"], "status": "unassigned",
            "coverage_dimension": slot["coverage_dimension"],
            "scenario_family_id": None, "clinical_template_id": None, "question_ids": [],
            "source_family_ids": [], "version_chain_ids": [],
        }
        require(slot == expected, f"public hidden slot contains assigned/private content: {sid}")
        require(slot["task_id"] in task_ids, f"unknown hidden task: {sid}")
    dev_counts = Counter(family["task_id"] for family in dev)
    hidden_counts = Counter(slot["task_id"] for slot in hidden["slots"])
    for task in tasks:
        tid = task["task_id"]
        require(dev_counts[tid] == task["planned_dev_families"], f"dev quota: {tid}")
        require(hidden_counts[tid] == task["planned_hidden_families"], f"hidden quota: {tid}")
        require(task["planned_variants_per_family"] == 3, f"three variants planned: {tid}")
        planned_strata = {
            item["coverage_dimension"]: item["family_slots"]
            for item in task["planned_hidden_substrata"]
        }
        actual_strata = Counter(
            slot["coverage_dimension"] for slot in hidden["slots"] if slot["task_id"] == tid
        )
        require(dict(actual_strata) == planned_strata, f"hidden mechanism quotas: {tid}")
        require(set(planned_strata) == set(task["coverage_dimensions"]), f"coverage dimensions: {tid}")
    require(len(slot_ids) == hidden["planned_family_slots"], "hidden planning count")
    require(hidden["planned_variants_per_family"] == 3, "hidden variants planned")

    for item in evidence:
        eid = item["evidence_id"]
        require(item["clinical_review_status"] == "pending", f"clinical review pending: {eid}")
        # 2026-10-12 audit: anchors verified & mapped (int ids). Keep as str for schema compat.
        require(
            item["evidence_store_anchor_id"] is not None
            and str(item["evidence_store_anchor_id"]).isdigit(),
            f"anchor mapped: {eid}",
        )
        require(
            item["locator_status"].startswith("text_verified_anchor_mapped"),
            f"locator mapped: {eid}",
        )
        require(item["coordinate_system"] == "raw_corpus_text_unicode_codepoints_half_open", f"coordinates: {eid}")
        require(item["char_end"] - item["char_start"] == len(item["excerpt"]), f"span length: {eid}")
        require(_digest(item["excerpt"].encode()) == item["excerpt_sha256"], f"excerpt digest: {eid}")

    if check_corpus:
        meta = bundle["evidence"]
        manifest_path = _local_path(repo, meta["manifest_path"], "benchmark/data/corpus")
        raw = manifest_path.read_bytes()
        require(_digest(raw) == meta["manifest_sha256"], "corpus manifest changed")
        docs = {row["source_id"]: row for row in json.loads(raw)["documents"] if row.get("status") == "ok"}
        for item in evidence:
            eid = item["evidence_id"]
            source = docs[item["source_id"]]
            path = _local_path(repo, item["input_file"], "benchmark/data/corpus/input")
            require(path == (manifest_path.parent / source["input_file"]).resolve(), f"source file identity: {eid}")
            text = path.read_text(encoding="utf-8")
            require(_digest(text.encode()) == item["input_text_sha256"], f"source text changed: {eid}")
            require(source["pdf_sha256"] == item["pdf_sha256"], f"PDF manifest identity: {eid}")
            require(source["page1_doi"] == item["doi"], f"DOI identity: {eid}")
            start, end = item["char_start"], item["char_end"]
            require(0 <= start < end <= len(text), f"span bounds: {eid}")
            require(text[start:end] == item["excerpt"], f"source excerpt mismatch: {eid}")
            markers = [(m.start(), int(m.group(1))) for m in re.finditer(r"(?m)^## Page (\d+)\s*$", text)]
            for offset, key in ((start, "page_start"), (end - 1, "page_end")):
                page = max((number for pos, number in markers if pos <= offset), default=1)
                require(page == item[key], f"source page mismatch: {eid}")

    return {
        "scaffold_valid": not errors,
        "hidden_dataset_ready": False,
        "clinical_review_performed": False,
        "semantic_overlap_review_performed": False,
        "corpus_checked": check_corpus,
        "counts": {
            "task_categories": len(task_ids), "dev_planned_families": len(dev),
            "dev_drafted_families": drafted, "dev_blocked_families": len(dev) - drafted,
            "dev_draft_questions": len(question_ids), "evidence_spans": len(evidence),
            "source_documents": len({item["source_id"] for item in evidence}),
            "hidden_unassigned_slots": len(slot_ids), "hidden_authored_questions": 0,
        },
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--check-corpus", action="store_true")
    args = parser.parse_args()
    try:
        report = validate_bundle(load_bundle(args.bundle), check_corpus=args.check_corpus)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        report = {"scaffold_valid": False, "hidden_dataset_ready": False, "errors": [str(exc)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["scaffold_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
