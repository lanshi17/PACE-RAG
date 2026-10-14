"""Guard against public drafts being mistaken for independent hidden data."""

from copy import deepcopy
from pathlib import Path

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

    from benchmark.pace_research.verify_exposure_coverage import verify_exposure_coverage

    rep = verify_exposure_coverage(
        Path(__file__).resolve().parents[1] / "benchmark/qa/dataset/pace_conditions_v1/legacy_exposure_inventory.json"
    )
    assert rep["files_failed"] == 0
    assert rep["total_exposure_questions"] == 98
    assert rep["files_passed"] == 4


def test_ga_parsing_synonym_expressions() -> None:
    """审计 v3 §2：孕周同义表达统一解析（14周6天 == 14+6周 == 14+6 == 104天）。"""
    from benchmark.pace_research.template_overlap_audit_v3 import parse_ga_days

    assert parse_ga_days("14周6天") == {104}
    assert parse_ga_days("14+6周") == {104}
    assert parse_ga_days("14+6") == {104}
    assert parse_ga_days("15周0天") == {105}
    assert parse_ga_days("22+3周") == {157}
    assert parse_ga_days("104天") == {104}
    # 单段 '6周' = 42 天（不能把 6 周中的 6 误解析为天数修饰）
    assert parse_ga_days("6周") == {42}


def test_ga_parsing_single_week_not_day_suffix() -> None:
    """'6周' 不能被 '14周6天' 的天数模式误捕获。"""
    from benchmark.pace_research.template_overlap_audit_v3 import parse_ga_days

    # '6周' 无天数后缀 → 42 天，不含 6
    assert 6 not in parse_ga_days("6周")


def test_overlap_v3_exposure_gate() -> None:
    """重叠审计 v3 必须在暴露集覆盖通过后才运行（审计补正 §2 验收）。"""
    from benchmark.pace_research.verify_exposure_coverage import verify_exposure_coverage

    rep = verify_exposure_coverage(
        Path(__file__).resolve().parents[1] / "benchmark/qa/dataset/pace_conditions_v1/legacy_exposure_inventory.json"
    )
    assert rep["files_failed"] == 0, "exposure gate must pass before overlap audit"


def test_anchor_v3_counterexamples() -> None:
    """审计 v4 §1：锚点校验反例检出——错来源、缺失锚点、非零退出码。"""
    import json
    import tempfile
    from pathlib import Path

    from benchmark.pace_research.verify_anchors_v3 import verify_anchors_v3

    repo = Path(__file__).resolve().parents[1]

    evidence = json.loads(
        (repo / "benchmark/qa/dataset/pace_conditions_v1/evidence_candidates.json").read_text(
            encoding="utf-8"
        )
    )
    bad1 = dict(evidence["records"][0])
    bad1["evidence_id"] = "TEST-MISSING-ANCHOR"
    bad1["evidence_store_anchor_id"] = "99999"
    bad2 = dict(evidence["records"][1])
    bad2["evidence_id"] = "TEST-WRONG-SOURCE"
    bad2["input_file"] = evidence["records"][2]["input_file"]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "evidence.json").write_text(
            json.dumps({**evidence, "records": evidence["records"] + [bad1, bad2]}, ensure_ascii=False),
            encoding="utf-8",
        )
        rep = verify_anchors_v3(tmp_path / "evidence.json", repo / "benchmark/data/evidence_store", repo / "benchmark/data/corpus")
    assert rep["fail_count"] >= 2
    fails = [r for r in rep["results"] if r["verdict"] == "fail"]
    assert any("snapshot_anchor_missing" in r["failures"] for r in fails)
    assert any(any("wrong_source" in f for f in r["failures"]) for r in fails)
    assert rep["snapshot_identity"]["chunk_count"] == 341


def test_ga_synonym_feature_equivalence() -> None:
    """审计 v4 §2：完整特征层同义孕周等价（无 num 泄漏）。"""
    from benchmark.pace_research.template_overlap_audit_v3 import extract_features_v3

    f1 = extract_features_v3("14周6天")
    f2 = extract_features_v3("14+6周")
    f3 = extract_features_v3("14+6")
    assert f1 == f2 == f3, f"feature sets differ: {f1} vs {f2} vs {f3}"
    assert "num:6" not in f1
    assert "ga_days:104" in f1


def test_anchor_v3_cli_nonzero_exit_on_failure() -> None:
    """审计 v4 §1：CLI 层反例产生非零退出码。"""
    import json
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    evidence_path = repo / "benchmark/qa/dataset/pace_conditions_v1/evidence_candidates.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    bad = dict(evidence["records"][0])
    bad["evidence_id"] = "TEST-CLI-FAIL"
    bad["evidence_store_anchor_id"] = "99999"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "evidence.json").write_text(
            json.dumps({**evidence, "records": evidence["records"] + [bad]}, ensure_ascii=False),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(repo / "benchmark/pace_research/verify_anchors_v3.py"), "--evidence", str(tmp_path / "evidence.json"), "--out", str(tmp_path / "out.json")],
            capture_output=True,
            text=True,
            cwd=repo,
        )
        assert result.returncode != 0, f"expected nonzero exit, got {result.returncode}"
        out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    fails = [r for r in out["results"] if r["verdict"] == "fail"]
    assert any("snapshot_anchor_missing" in r["failures"] for r in fails)


def test_material_hash_consistency() -> None:
    """审计 v4 §1：三份审核包绑定的材料哈希与当前文件一致；材料变化必须使检查失败。"""
    import hashlib
    import json
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    base = repo / "benchmark/qa/dataset/pace_conditions_v1"
    files = ["dev_families.json", "evidence_candidates.json", "template_overlap_audit_v3.json", "legacy_exposure_inventory.json"]
    actual = {f: hashlib.sha256((base / f).read_bytes()).hexdigest() for f in files}
    for pkg_name in ("review_package_A.json", "review_package_B.json", "merge_arbitration_template.json"):
        pkg = json.loads((base / pkg_name).read_text(encoding="utf-8"))
        bound = pkg["material_version"]["files"]
        for f in files:
            assert bound[f]["sha256"] == actual[f], f"{pkg_name} bound hash mismatch for {f}"


def test_overlap_v3_match_reason_uses_hist_text() -> None:
    """审计 v4 §2：非零分数行的 match_reason 必须含实际历史题文本（非来源标签）。"""
    import json
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    base = repo / "benchmark/qa/dataset/pace_conditions_v1"
    ovl = json.loads((base / "template_overlap_audit_v3.json").read_text(encoding="utf-8"))
    nonzero = [r for r in ovl["rows"] if r["heuristic_candidate_score"] > 0]
    assert nonzero, "expected nonzero-score rows"
    for r in nonzero:
        reason = r.get("match_reason") or ""
        assert "hist question:" in reason, f"{r['draft_question_id']} missing hist text in reason"
        # 来源标签如 'hist50' 不应单独作为理由内容
        assert not reason.strip().startswith("hist"), f"{r['draft_question_id']} reason starts with source label"


def _write_anchor_fixture(tmp_path: Path, repo: Path, mutate) -> tuple[Path, Path]:
    """审计 v5：构造隔离的锚点校验材料（复制语料文件到临时目录）。"""
    import json
    import shutil

    evidence = json.loads(
        (repo / "benchmark/qa/dataset/pace_conditions_v1/evidence_candidates.json").read_text(
            encoding="utf-8"
        )
    )
    records = [dict(r) for r in evidence["records"]]
    # 修改 input_file 指向临时语料目录（相对路径保持结构）
    for r in records:
        r["input_file"] = "TMP/input/" + r["input_file"].split("/")[-1]
    mutate(records, tmp_path, repo)
    (tmp_path / "evidence.json").write_text(
        json.dumps({**evidence, "records": records}, ensure_ascii=False), encoding="utf-8"
    )
    # 复制语料文件到 tmp/input/（未 mutate 修改的文件保持原内容）
    corpus_input = repo / "benchmark/data/corpus/input"
    (tmp_path / "input").mkdir(exist_ok=True)
    shutil.copy(repo / "benchmark/data/corpus/corpus_manifest.json", tmp_path / "corpus_manifest.json")
    for r in records:
        fname = r["input_file"].split("/")[-1]
        src = corpus_input / fname
        if src.is_file() and not (tmp_path / "input" / fname).exists():
            shutil.copy(src, tmp_path / "input" / fname)
    return tmp_path / "evidence.json", tmp_path


def test_anchor_v3_prefix_only_and_missing_file() -> None:
    """审计 v5 §1：前缀相同后文不同 → full_excerpt_not_contained；文件缺失 → source_file_missing；CLI exit 1。"""
    import json
    import subprocess
    import sys
    import tempfile

    repo = Path(__file__).resolve().parents[1]

    def mutate_prefix(records, tmp_path, repo):
        # 摘录前 80 字符与真实语料相同，但补上不同的后文 → 完整摘录不再包含
        records[0]["excerpt"] = records[0]["excerpt"][:80] + "【被篡改的后文，与原文不同】"

    def mutate_missing(records, tmp_path, repo):
        # 不写 input/ 下的文件 → source_file_missing（fixture 只复制存在的原文件，
        # 这里把第一条指向一个不存在的文件名）
        records[0]["input_file"] = "TMP/input/definitely_missing_source.txt"

    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
        for mutate in (mutate_prefix, mutate_missing):
            ev_path, tmp = _write_anchor_fixture(Path(tmp1 if mutate is mutate_prefix else tmp2), repo, mutate)
            result = subprocess.run(
                [
                    sys.executable,
                    str(repo / "benchmark/pace_research/verify_anchors_v3.py"),
                    "--evidence",
                    str(ev_path),
                    "--store",
                    str(repo / "benchmark/data/evidence_store"),
                    "--corpus",
                    str(tmp),
                    "--out",
                    str(tmp / "out.json"),
                ],
                capture_output=True,
                text=True,
                cwd=repo,
            )
            assert result.returncode == 1, f"expected exit 1, got {result.returncode}: {result.stdout}"
            out = json.loads((tmp / "out.json").read_text(encoding="utf-8"))
            fails = [r for r in out["results"] if r["verdict"] == "fail"]
            expected = "full_excerpt_not_contained" if mutate is mutate_prefix else "source_file_missing"
            assert any(expected in r["failures"] for r in fails), f"{expected} not in {fails}"


def test_exposure_gate_failure_paths() -> None:
    """审计 v6：file_missing / 仅哈希变化（记录数不变）→ 覆盖失败 + 重叠入口 exit 2 + 实际 --out 未被覆盖。"""
    import json
    import subprocess
    import sys
    import tempfile

    repo = Path(__file__).resolve().parents[1]
    base = repo / "benchmark/qa/dataset/pace_conditions_v1"
    inv = json.loads((base / "legacy_exposure_inventory.json").read_text(encoding="utf-8"))
    repo_overlap_path = base / "template_overlap_audit_v3.json"
    repo_overlap_before = repo_overlap_path.read_bytes()
    SENTINEL = b"SENTINEL-overlap-product-must-not-be-overwritten"

    def run_gate(tmp: Path, mutate_records) -> tuple[subprocess.CompletedProcess, Path]:
        inv2 = {**inv, "records": [dict(r) for r in inv["records"]]}
        mutate_records(inv2["records"], tmp)
        inv_path = tmp / "inv.json"
        inv_path.write_text(json.dumps(inv2, ensure_ascii=False), encoding="utf-8")
        out_path = tmp / "overlap_out.json"
        out_path.write_bytes(SENTINEL)
        result = subprocess.run(
            [
                sys.executable,
                str(repo / "benchmark/pace_research/template_overlap_audit_v3.py"),
                "--inventory",
                str(inv_path),
                "--out",
                str(out_path),
            ],
            capture_output=True,
            text=True,
            cwd=repo,
        )
        return result, out_path

    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
        # 场景 1：文件缺失
        def mutate_missing(records, tmp):
            records[0]["path"] = str(tmp / "no_such_file.json")

        r1, out1 = run_gate(Path(tmp1), mutate_missing)
        assert r1.returncode == 2, f"expected exit 2, got {r1.returncode}: {r1.stderr[:200]}"
        assert "file_missing" in r1.stderr or "file_missing" in r1.stdout
        # 实际 --out 目标的字节完全不变
        assert out1.read_bytes() == SENTINEL, "actual --out target was overwritten (file_missing)"

        # 场景 2：仅内容改变、记录数不变 → count_match=True, sha_match=False
        def mutate_sha(records, tmp):
            src = repo / records[0]["path"]
            tampered = tmp / "tampered.json"
            data = json.loads(src.read_text(encoding="utf-8"))
            # 修改第一条记录内容，记录数保持不变
            if isinstance(data, list):
                data[0] = {**data[0], "_tampered": True}
            else:
                raise AssertionError("expected list-shaped exposure file for tampering")
            tampered.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            records[0]["path"] = str(tampered)

        r2, out2 = run_gate(Path(tmp2), mutate_sha)
        assert r2.returncode == 2, f"expected exit 2, got {r2.returncode}: {r2.stderr[:200]}"
        assert "sha256_mismatch" in r2.stderr or "sha256_mismatch" in r2.stdout
        # 直接验证覆盖检查的内部结果：记录数相同但哈希不符
        from benchmark.pace_research.verify_exposure_coverage import verify_exposure_coverage

        inv_sha = {**inv, "records": [dict(r) for r in inv["records"]]}
        tampered_path = Path(tmp2) / "tampered.json"
        original = json.loads((repo / inv["records"][0]["path"]).read_text(encoding="utf-8"))
        tampered_path.write_text(
            json.dumps([{**original[0], "_tampered": True}] + original[1:], ensure_ascii=False),
            encoding="utf-8",
        )
        inv_sha["records"][0]["path"] = str(tampered_path)
        inv_sha_path = Path(tmp2) / "inv_sha.json"
        inv_sha_path.write_text(json.dumps(inv_sha, ensure_ascii=False), encoding="utf-8")
        rep = verify_exposure_coverage(inv_sha_path)
        entry = rep["results"][0]
        assert entry["count_match"] is True, f"count must match: {entry}"
        assert entry["sha_match"] is False, f"sha must mismatch: {entry}"
        assert out2.read_bytes() == SENTINEL, "actual --out target was overwritten (sha256_mismatch)"

    # 仓库真实产物未被覆盖
    assert repo_overlap_path.read_bytes() == repo_overlap_before, "repo overlap product was overwritten"
