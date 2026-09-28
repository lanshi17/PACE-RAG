"""chunk 条件物化测试：存储往返保真、跨 anchor 隔离、重摄取级联（verifier F-2/F-3/F-5）。

使用 tmp 存储；真实 gitignored 存储仅在 real-execution 层以副本方式读取。
"""

from __future__ import annotations

from pathlib import Path

from prenatal_rag.conditions import ConditionType, extract_conditions
from prenatal_rag.evidence_store.store import EvidenceStore


def _ingest(store: EvidenceStore, source_id: str, text: str) -> int:
    store.ingest_document(source_id, text, family_id=f"fam-{source_id}")
    return next(
        chunk.anchor_id
        for chunk in store.iter_chunks(source_id)
    )


def _index(store: EvidenceStore, chunk_text: str, anchor_id: int, source_id: str) -> None:
    conds = extract_conditions(
        chunk_text,
        anchor_id=anchor_id,
        source_id=source_id,
        base_offset=0,
    )
    store.rewrite_chunk_conditions(anchor_id, conds)


class TestRoundTripFidelity:
    def test_conditions_for_returns_exact_written_conditions(self, tmp_path: Path) -> None:
        # F-2：to_row() 列序或值列互换必须在读取端暴露。
        store = EvidenceStore(tmp_path / "es")
        try:
            text = "scan 11+0 to 13+6 weeks for monochorionic twins with cfDNA screening"
            anchor_id = _ingest(store, "Doc", f"## Page 1\n\n{text}")
            _index(store, text, anchor_id, "Doc")

            written = extract_conditions(text, anchor_id=anchor_id, source_id="Doc")
            stored = store.conditions_for(anchor_id)

            assert len(stored) == len(written) > 0
            key = lambda c: (  # noqa: E731
                c.condition_type.value, c.value, c.matched_text, c.pattern_id
            )
            assert sorted(map(key, stored)) == sorted(map(key, written))
            for c in stored:
                assert c.anchor_id == anchor_id
                assert c.source_id == "Doc"
                assert text[c.char_start : c.char_end] == c.matched_text
            # 孕周 value 必须仍是可解析的 GaWindow 序列化串（列互换会在此崩溃）。
            ga_values = [c.value for c in stored if c.condition_type is ConditionType.GESTATIONAL_AGE]
            assert "77:97" in ga_values
        finally:
            store.close()


class TestCrossAnchorIsolation:
    def test_conditions_for_returns_only_that_anchor(self, tmp_path: Path) -> None:
        # F-3：两个文档各自摄取后，conditions_for 不得串 anchor。
        store = EvidenceStore(tmp_path / "es")
        try:
            text_a = "screening 11+0 to 13+6 weeks"
            text_b = "follow-up at 20 weeks"
            anchor_a = _ingest(store, "DocA", f"## Page 1\n\n{text_a}")
            anchor_b = _ingest(store, "DocB", f"## Page 1\n\n{text_b}")
            _index(store, text_a, anchor_a, "DocA")
            _index(store, text_b, anchor_b, "DocB")

            rows_a = store.conditions_for(anchor_a)
            rows_b = store.conditions_for(anchor_b)
            assert rows_a and rows_b
            assert {c.source_id for c in rows_a} == {"DocA"}
            assert {c.source_id for c in rows_b} == {"DocB"}
            assert {c.anchor_id for c in rows_a} == {anchor_a}
            assert {c.anchor_id for c in rows_b} == {anchor_b}
        finally:
            store.close()



class TestReingestCascade:
    def test_reingest_changed_text_drops_stale_conditions(self, tmp_path: Path) -> None:
        # F-5：文本变化 → 整份替换锚点；旧 anchor 的条件行必须随 CASCADE 消失。
        store = EvidenceStore(tmp_path / "es")
        try:
            old_text = "scan 11+0 to 13+6 weeks for monochorionic twins"
            anchor_old = _ingest(store, "Doc", f"## Page 1\n\n{old_text}")
            _index(store, old_text, anchor_old, "Doc")
            assert store.conditions_for(anchor_old)

            new_text = "revised protocol with different content entirely"
            store.ingest_document("Doc", f"## Page 1\n\n{new_text}", family_id="fam-Doc")
            # 旧锚点已删除：条件行随之消失（CASCADE），读取不得抛错；
            # 全存储层面也不得残留 Doc 的孤儿条件行。
            assert store.conditions_for(anchor_old) == []
            assert all(c.anchor_id != anchor_old for c in store.iter_conditions())
            # 新锚点重新物化后恢复。
            chunk = next(store.iter_chunks("Doc"))
            _index(store, chunk.text, chunk.anchor_id, "Doc")
            stored = store.conditions_for(chunk.anchor_id)
            assert all(c.source_id == "Doc" for c in stored)
        finally:
            store.close()


class TestPersistenceAcrossReopen:
    def test_conditions_persist_after_close_and_reopen(self, tmp_path: Path) -> None:
        # F-R3-2：物化条件必须在 close/reopen 后仍在（commit 语义；
        # commit 被删除的突变体在 close 时静默丢失全部条件行）。
        store = EvidenceStore(tmp_path / "es")
        text = "scan 11+0 to 13+6 weeks for monochorionic twins"
        store.ingest_document("Doc", f"## Page 1\n\n{text}", family_id="fam-Doc")
        assert store.build_condition_index() > 0
        anchor = next(chunk.anchor_id for chunk in store.iter_chunks("Doc"))
        before = store.conditions_for(anchor)
        assert before
        key = lambda c: (  # noqa: E731
            c.condition_type.value, c.value, c.char_start, c.char_end,
            c.matched_text, c.pattern_id,
        )
        expected = sorted(map(key, before))
        store.close()

        reopened = EvidenceStore(tmp_path / "es")
        try:
            after = reopened.conditions_for(anchor)
            assert sorted(map(key, after)) == expected
        finally:
            reopened.close()


class TestIndexBaseOffset:
    def test_build_condition_index_uses_absolute_offsets(self, tmp_path: Path) -> None:
        # F-R3-3：build_condition_index 的 base_offset 必须取 chunk 在规范化
        # 文本内的绝对偏移——否则 char_start>0 的 chunk 来源 span 全部错位。
        store = EvidenceStore(tmp_path / "es")
        try:
            page1 = "## Page 1\n\n" + "filler content. " * 90 + "\n"
            page2 = "## Page 2\n\nscan 11+0 to 13+6 weeks for monochorionic twins.\n"
            store.ingest_document("Doc", page1 + page2, family_id="f")
            target = next(c for c in store.iter_chunks("Doc") if "11+0" in c.text)
            assert target.char_start > 0
            store.build_condition_index()
            ga = next(
                c
                for c in store.conditions_for(target.anchor_id)
                if c.condition_type is ConditionType.GESTATIONAL_AGE
            )
            relative = target.text.index("11+0")
            assert ga.char_start == target.char_start + relative
            assert (
                target.text[ga.char_start - target.char_start : ga.char_end - target.char_start]
                == ga.matched_text
            )
        finally:
            store.close()
