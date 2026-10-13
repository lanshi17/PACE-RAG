"""Guard against public drafts being mistaken for independent hidden data."""

from copy import deepcopy

import pytest

from benchmark.pace_research.validate_r2_scaffold import (
    DEFAULT_BUNDLE,
    load_bundle,
    validate_bundle,
)


@pytest.fixture
def bundle():
    return deepcopy(load_bundle(DEFAULT_BUNDLE))


def test_scaffold_counts_do_not_claim_hidden_readiness(bundle):
    report = validate_bundle(bundle)
    assert report["scaffold_valid"], report["errors"]
    assert report["counts"]["dev_draft_questions"] == 27
    assert report["counts"]["dev_blocked_families"] == 1
    assert report["counts"]["hidden_unassigned_slots"] == 60
    assert report["counts"]["hidden_authored_questions"] == 0
    assert not report["hidden_dataset_ready"]


def test_public_dev_family_cannot_be_promoted_to_hidden(bundle):
    bundle["dev"]["records"][0]["split"] = "hidden"
    report = validate_bundle(bundle)
    assert not report["scaffold_valid"]
    assert any("public family cannot be hidden" in e for e in report["errors"])


@pytest.mark.parametrize("key,value", [("question", "private question"), ("gold", "private answer")])
def test_public_hidden_allocation_rejects_private_payload(bundle, key, value):
    bundle["hidden"]["slots"][0][key] = value
    report = validate_bundle(bundle)
    assert not report["scaffold_valid"]
    assert any("assigned/private content" in e for e in report["errors"])


def test_two_changed_conditions_are_not_a_single_variable_pair(bundle):
    bundle["dev"]["records"][0]["variants"][1]["known_conditions"]["procedure"] = "other"
    report = validate_bundle(bundle)
    assert not report["scaffold_valid"]
    assert any("not a single condition change" in e for e in report["errors"])


def test_invariant_control_must_preserve_known_conditions(bundle):
    bundle["dev"]["records"][0]["variants"][2]["known_conditions"]["gestational_age_days"] = 120
    report = validate_bundle(bundle)
    assert not report["scaffold_valid"]
    assert any("invariant control changed conditions" in e for e in report["errors"])


def test_draft_cannot_claim_frozen_gold(bundle):
    bundle["hidden"]["gold_frozen"] = True
    bundle["dev"]["records"][0]["gold"] = {"answer": "unreviewed"}
    report = validate_bundle(bundle)
    assert not report["scaffold_valid"]
    assert any("cannot be frozen" in e for e in report["errors"])
    assert any("draft gold must be empty" in e for e in report["errors"])


def test_legacy_rewording_still_needs_semantic_review_and_exact_reuse_fails(bundle):
    from benchmark.pace_research.validate_r2_scaffold import REPO
    import json

    legacy = json.loads((REPO / bundle["legacy"]["records"][0]["path"]).read_text())
    bundle["dev"]["records"][0]["variants"][0]["question"] = "  " + legacy[0]["question"]
    report = validate_bundle(bundle)
    assert not report["scaffold_valid"]
    assert any("exact question reuse" in e for e in report["errors"])
    assert not report["semantic_overlap_review_performed"]


def test_evidence_excerpt_mutation_is_detected(bundle):
    bundle["evidence"]["records"][0]["excerpt"] += " changed"
    report = validate_bundle(bundle)
    assert not report["scaffold_valid"]
    assert any("excerpt digest" in e for e in report["errors"])


def test_exposure_coverage_four_files_98_records() -> None:
    """审计 v2 §2：暴露集覆盖必须 4/4 文件通过、共 98 条。"""
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from benchmark.pace_research.verify_exposure_coverage import verify_exposure_coverage

    rep = verify_exposure_coverage(
        repo / "benchmark/qa/dataset/pace_conditions_v1/legacy_exposure_inventory.json"
    )
    assert rep["files_failed"] == 0
    assert rep["total_exposure_questions"] == 98
    assert rep["files_passed"] == 4
