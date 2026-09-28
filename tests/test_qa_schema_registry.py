"""GUIDELINE_REGISTRY 结构完整性测试（2026-09-14 批次新增条目）。"""

from __future__ import annotations

import re

from benchmark.qa.schema import GUIDELINE_REGISTRY

NEW_ENTRIES = (
    "ISPD-nipt-2023",
    "ISPD-genome-wide-sequencing-2022",
    "SMFM-consult-57-soft-markers-2021",
    "SMFM-cfdna-ultrasound-2017",
    "ISUOG-fetal-mri-2017",
    "ISUOG-fetal-mri-2023",
    "ISUOG-basic-cardiac-screening-2006",
    "ISUOG-sonographic-screening-fetal-heart-2013",
)

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def test_new_entries_present() -> None:
    for key in NEW_ENTRIES:
        assert key in GUIDELINE_REGISTRY, key


def test_new_entries_carry_doi_and_year() -> None:
    for key in NEW_ENTRIES:
        entry = GUIDELINE_REGISTRY[key]
        assert entry.get("doi"), f"{key} 缺 DOI"
        assert DOI_RE.match(entry["doi"]), f"{key} DOI 格式异常: {entry['doi']}"
        assert isinstance(entry.get("year"), int), f"{key} 缺年份"


def test_superseded_by_targets_exist() -> None:
    for key, entry in GUIDELINE_REGISTRY.items():
        target = entry.get("superseded_by")
        if target is not None:
            assert target in GUIDELINE_REGISTRY, f"{key} 的 superseded_by 未知: {target}"


def test_version_chains_are_wired() -> None:
    """已核验版本链：MRI 2017→2023；心脏 2006→2013→2023。"""
    assert (
        GUIDELINE_REGISTRY["ISUOG-fetal-mri-2017"]["superseded_by"]
        == "ISUOG-fetal-mri-2023"
    )
    assert (
        GUIDELINE_REGISTRY["ISUOG-basic-cardiac-screening-2006"]["superseded_by"]
        == "ISUOG-sonographic-screening-fetal-heart-2013"
    )
    assert (
        GUIDELINE_REGISTRY["ISUOG-sonographic-screening-fetal-heart-2013"][
            "superseded_by"
        ]
        == "ISUOG-fetal-cardiac-screening-2023"
    )


def test_smfm_consult_57_records_replaces_list() -> None:
    note = GUIDELINE_REGISTRY["SMFM-consult-57-soft-markers-2021"]["note"]
    assert "Replaces Consults #10" in note
