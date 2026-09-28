"""证据真值层存储：SQLite 原型（主文档 §4）。

设计约束：

- 证据存储是唯一真值层；LightRAG 图与向量库是可重建投影。
  vendored LightRAG 的 chunk 级引用不足以承担 span 级锚点（续记 §1#5），
  页码与字符区间锚点相对本存储的规范化文本自洽。
- 规范化文本 = 统一语料页标记文本剥离 Wiley 下载水印行后的结果
  （审计报告 §3 遗留改进项）；剥离计数入库可审计。
- 文档身份两键制（续记 §2.1）：页首 DOI（family_id）+ 原始 PDF 哈希；
  存储内规范化文本另有 text_sha256，锚点引用原文哈希防漂移。
- 本模块刻意复制 PAGE_MARK_RE 而不导入 benchmark.common.corpus，
  保持包独立可发布。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from prenatal_rag.conditions.extract import extract_conditions
from prenatal_rag.conditions.schema import ChunkCondition, ConditionType

INGEST_VERSION = "prenatal-evidence-v1"

# 与 benchmark/common/corpus.py 的 PAGE_MARK_RE 保持一致（刻意复制，包独立）。
PAGE_MARK_RE = re.compile(r"(?m)^## Page (\d+)\s*$")
_MARKER_LINE_RE = re.compile(r"## Page (\d+)\s*")

# 统一语料文本头（corpus.py 写入的元数据行）；不属于临床证据，
# 不进入 chunk，但保留在规范化文本中以保证整文本哈希可复核。
_CORPUS_HEADER_LINE_RE = re.compile(r"^(SOURCE_ID|ORIGINAL_FILE|PDF_SHA256):")

# 条件密度探针（benchmark/report/condition_density_probe.py）的 Wiley 下载
# 水印行特征；命中行整行剥离并计数。
WATERMARK_LINE_RE = re.compile(
    r"Downloaded from|See the Terms and Conditions|OA articles are governed"
)

_CHUNK_TARGET_CHARS = 1200


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strip_watermark_lines(text: str) -> tuple[str, int]:
    """剥离 Wiley 下载水印行；返回（规范化文本, 剥离行数）。

    逐行删除（含换行符），页标记 ``## Page N`` 行不受影响；
    页内偏移以剥离后的规范化文本为准。
    """
    kept: list[str] = []
    removed = 0
    for line in text.splitlines(keepends=True):
        if WATERMARK_LINE_RE.search(line):
            removed += 1
            continue
        kept.append(line)
    return "".join(kept), removed


@dataclass(frozen=True)
class SourceDocument:
    """已入库的来源文档身份与统计。"""

    source_id: str
    family_id: str
    page1_doi: str | None
    original_file: str | None
    pdf_sha256: str | None
    text_sha256: str
    page_count: int
    text_characters: int
    watermark_lines_removed: int
    manifest_warnings: tuple[str, ...]
    ingest_version: str
    ingested_at: str


@dataclass(frozen=True)
class SpanAnchor:
    """指向规范化文本半开区间 [char_start, char_end) 的锚点。

    kind: "page"（整页区域，含页标记行）/ "chunk"（页内连续段落块）/
    "span"（locate() 的原文精确片段）。
    """

    source_id: str
    kind: str
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    text_sha256: str


@dataclass(frozen=True)
class Chunk(SpanAnchor):
    """检索用 chunk：页内连续段落块，文本恰为规范化文本的对应切片。"""

    anchor_id: int
    text: str


@dataclass(frozen=True)
class DocumentIngestResult:
    """单文档 ingest 结果；chunk_count 仅统计本次调用新建的 chunk。"""

    created: bool
    page_count: int
    chunk_count: int
    watermark_lines_removed: int


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_documents (
    source_id TEXT PRIMARY KEY,
    family_id TEXT NOT NULL,
    page1_doi TEXT,
    original_file TEXT,
    pdf_sha256 TEXT,
    text_sha256 TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    text_characters INTEGER NOT NULL,
    watermark_lines_removed INTEGER NOT NULL,
    manifest_warnings TEXT NOT NULL DEFAULT '[]',
    ingest_version TEXT NOT NULL,
    ingested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence_anchors (
    anchor_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES source_documents(source_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    page_start INTEGER NOT NULL,
    page_end INTEGER NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    text_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_anchors_source_kind
    ON evidence_anchors(source_id, kind);
CREATE TABLE IF NOT EXISTS chunk_texts (
    anchor_id INTEGER PRIMARY KEY
        REFERENCES evidence_anchors(anchor_id) ON DELETE CASCADE,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunk_conditions (
    anchor_id INTEGER NOT NULL
        REFERENCES evidence_anchors(anchor_id) ON DELETE CASCADE,
    condition_type TEXT NOT NULL,
    value TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    matched_text TEXT NOT NULL,
    pattern_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_conditions_anchor
    ON chunk_conditions(anchor_id);
CREATE INDEX IF NOT EXISTS idx_conditions_type
    ON chunk_conditions(condition_type);
"""


class EvidenceStore:
    """SQLite 证据存储；文本权威副本落盘在 ``<root>/texts/<source_id>.txt``。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.texts_dir = self.root / "texts"
        self.texts_dir.mkdir(exist_ok=True)
        self.db_path = self.root / "evidence.sqlite3"
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.executemany(
            "INSERT OR IGNORE INTO schema_meta(key, value) VALUES (?, ?)",
            [("schema_version", "1"), ("ingest_version", INGEST_VERSION)],
        )
        self._conn.commit()

    # ── 生命周期 ────────────────────────────────────────────────────────────
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "EvidenceStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ── 写入 ────────────────────────────────────────────────────────────────
    def ingest_document(
        self,
        source_id: str,
        text: str,
        *,
        family_id: str,
        page1_doi: str | None = None,
        original_file: str | None = None,
        pdf_sha256: str | None = None,
        manifest_warnings: Sequence[str] = (),
        chunk_target_chars: int = _CHUNK_TARGET_CHARS,
    ) -> DocumentIngestResult:
        """规范化并写入一份文档；文本未变化时为幂等 no-op。

        同 source_id 但文本变化时整份替换（删除旧锚点与旧文本文件），
        支持证据撤回后的重投影语义。
        """
        canonical, watermark_removed = strip_watermark_lines(text)
        text_sha = _sha256(canonical)

        existing = self._conn.execute(
            "SELECT text_sha256, page_count, watermark_lines_removed"
            " FROM source_documents WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if existing is not None and existing["text_sha256"] == text_sha:
            return DocumentIngestResult(
                created=False,
                page_count=existing["page_count"],
                chunk_count=0,
                watermark_lines_removed=existing["watermark_lines_removed"],
            )

        regions = _page_regions(canonical)
        self._conn.execute(
            "DELETE FROM source_documents WHERE source_id = ?", (source_id,)
        )
        text_path = self._text_path(source_id)
        if text_path.exists():
            text_path.unlink()

        self._conn.execute(
            "INSERT INTO source_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source_id,
                family_id,
                page1_doi,
                original_file,
                pdf_sha256,
                text_sha,
                len(regions),
                len(canonical),
                watermark_removed,
                json.dumps(list(manifest_warnings), ensure_ascii=False),
                INGEST_VERSION,
                _now_iso(),
            ),
        )

        for page_no, start, end in regions:
            self._insert_anchor(
                source_id,
                kind="page",
                page_start=page_no,
                page_end=page_no,
                char_start=start,
                char_end=end,
                segment=canonical[start:end],
            )

        chunk_count = 0
        for page_no, start, end in regions:
            for chunk_start, chunk_end in _pack_paragraphs(
                canonical, start, end, chunk_target_chars
            ):
                self._insert_anchor(
                    source_id,
                    kind="chunk",
                    page_start=page_no,
                    page_end=page_no,
                    char_start=chunk_start,
                    char_end=chunk_end,
                    segment=canonical[chunk_start:chunk_end],
                )
                chunk_count += 1

        text_path.write_text(canonical, encoding="utf-8")
        self._conn.commit()
        return DocumentIngestResult(
            created=True,
            page_count=len(regions),
            chunk_count=chunk_count,
            watermark_lines_removed=watermark_removed,
        )

    def _insert_anchor(
        self,
        source_id: str,
        *,
        kind: str,
        page_start: int,
        page_end: int,
        char_start: int,
        char_end: int,
        segment: str,
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO evidence_anchors"
            " (source_id, kind, page_start, page_end, char_start, char_end, text_sha256)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                source_id,
                kind,
                page_start,
                page_end,
                char_start,
                char_end,
                _sha256(segment),
            ),
        )
        lastrowid = cursor.lastrowid
        if lastrowid is None:  # pragma: no cover — INSERT 成功必返回 rowid
            raise RuntimeError("sqlite3 INSERT 未返回 lastrowid")
        if kind == "chunk":
            self._conn.execute(
                "INSERT INTO chunk_texts(anchor_id, text) VALUES (?, ?)",
                (lastrowid, segment),
            )
        return lastrowid

    def _text_path(self, source_id: str) -> Path:
        return self.texts_dir / f"{source_id}.txt"

    # ── 读取 ────────────────────────────────────────────────────────────────
    def documents(self) -> list[SourceDocument]:
        rows = self._conn.execute(
            "SELECT * FROM source_documents ORDER BY source_id"
        ).fetchall()
        return [_row_to_document(row) for row in rows]

    def document(self, source_id: str) -> SourceDocument | None:
        row = self._conn.execute(
            "SELECT * FROM source_documents WHERE source_id = ?", (source_id,)
        ).fetchone()
        return _row_to_document(row) if row is not None else None

    def load_text(self, source_id: str) -> str:
        """读取规范化文本；未入库文档抛 FileNotFoundError。"""
        return self._text_path(source_id).read_text(encoding="utf-8")

    def page_text(self, source_id: str, page: int) -> str:
        """返回整页区域切片（含 ``## Page N`` 标记行）。"""
        row = self._conn.execute(
            "SELECT char_start, char_end FROM evidence_anchors"
            " WHERE source_id = ? AND kind = 'page' AND page_start = ?",
            (source_id, page),
        ).fetchone()
        if row is None:
            raise KeyError(f"{source_id} 不存在页锚点: page={page}")
        text = self.load_text(source_id)
        return text[row["char_start"] : row["char_end"]]

    def page_anchors(self, source_id: str) -> list[SpanAnchor]:
        """返回整页锚点（按字符偏移升序）；区域无缝平铺规范化文本。"""
        rows = self._conn.execute(
            "SELECT page_start, char_start, char_end, text_sha256"
            " FROM evidence_anchors WHERE source_id = ? AND kind = 'page'"
            " ORDER BY char_start",
            (source_id,),
        ).fetchall()
        return [
            SpanAnchor(
                source_id=source_id,
                kind="page",
                page_start=row["page_start"],
                page_end=row["page_start"],
                char_start=row["char_start"],
                char_end=row["char_end"],
                text_sha256=row["text_sha256"],
            )
            for row in rows
        ]

    def iter_chunks(self, source_id: str | None = None) -> Iterator[Chunk]:
        sql = (
            "SELECT a.anchor_id, a.source_id, a.page_start, a.page_end,"
            " a.char_start, a.char_end, a.text_sha256, t.text"
            " FROM evidence_anchors a JOIN chunk_texts t ON t.anchor_id = a.anchor_id"
        )
        params: tuple[str, ...] = ()
        if source_id is not None:
            sql += " WHERE a.source_id = ?"
            params = (source_id,)
        sql += " ORDER BY a.source_id, a.anchor_id"
        for row in self._conn.execute(sql, params):
            yield Chunk(
                source_id=row["source_id"],
                kind="chunk",
                page_start=row["page_start"],
                page_end=row["page_end"],
                char_start=row["char_start"],
                char_end=row["char_end"],
                text_sha256=row["text_sha256"],
                anchor_id=row["anchor_id"],
                text=row["text"],
            )

    # ── chunk 条件（B1 过滤器前置）─────────────────────────────────────────
    def rewrite_chunk_conditions(
        self, anchor_id: int, conditions: Sequence[ChunkCondition]
    ) -> None:
        """整份替换某个 chunk 的已抽条件（支持重复运行与抽取器迭代）。"""
        self._conn.execute(
            "DELETE FROM chunk_conditions WHERE anchor_id = ?", (anchor_id,)
        )
        self._conn.executemany(
            "INSERT INTO chunk_conditions"
            " (anchor_id, condition_type, value, char_start, char_end,"
            "  matched_text, pattern_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [c.to_row() for c in conditions],
        )
        self._conn.commit()

    def conditions_for(self, anchor_id: int) -> list[ChunkCondition]:
        rows = self._conn.execute(
            "SELECT c.anchor_id, a.source_id, c.condition_type, c.value,"
            " c.char_start, c.char_end, c.matched_text, c.pattern_id"
            " FROM chunk_conditions c"
            " JOIN evidence_anchors a ON a.anchor_id = c.anchor_id"
            " WHERE c.anchor_id = ? ORDER BY c.condition_type, c.char_start",
            (anchor_id,),
        ).fetchall()
        return [_row_to_condition(row) for row in rows]

    def iter_conditions(
        self, source_id: str | None = None
    ) -> Iterator[ChunkCondition]:
        sql = (
            "SELECT c.anchor_id, a.source_id, c.condition_type, c.value,"
            " c.char_start, c.char_end, c.matched_text, c.pattern_id"
            " FROM chunk_conditions c"
            " JOIN evidence_anchors a ON a.anchor_id = c.anchor_id"
        )
        params: tuple[str, ...] = ()
        if source_id is not None:
            sql += " WHERE a.source_id = ?"
            params = (source_id,)
        sql += " ORDER BY a.source_id, c.anchor_id, c.condition_type, c.char_start"
        for row in self._conn.execute(sql, params):
            yield _row_to_condition(row)

    def build_condition_index(self, source_id: str | None = None) -> int:
        """对存储中全部（或单来源）chunk 抽取条件并写回；返回写入条数。

        便捷入口，等价于 ``conditions.extract.index_conditions``；
        base_offset 取各 chunk 在规范化文本内的绝对偏移，span 锚点自洽。
        """
        written = 0
        for chunk in self.iter_chunks(source_id):
            conds = extract_conditions(
                chunk.text,
                anchor_id=chunk.anchor_id,
                source_id=chunk.source_id,
                base_offset=chunk.char_start,
            )
            self.rewrite_chunk_conditions(chunk.anchor_id, conds)
            written += len(conds)
        return written

    def locate(self, source_id: str, snippet: str) -> list[SpanAnchor]:
        """在规范化文本中精确定位原文片段（全部出现位置，按偏移升序）。

        精确匹配语义：claim 核验的来源检查以此为真值起点；
        改写/翻译后的陈述需先回溯到原文片段再定位。
        """
        if not snippet:
            return []
        text = self.load_text(source_id)
        regions = _page_regions(text)
        anchors: list[SpanAnchor] = []
        idx = text.find(snippet)
        while idx != -1:
            page_no = _page_for(regions, idx)
            anchors.append(
                SpanAnchor(
                    source_id=source_id,
                    kind="span",
                    page_start=page_no,
                    page_end=page_no,
                    char_start=idx,
                    char_end=idx + len(snippet),
                    text_sha256=_sha256(snippet),
                )
            )
            idx = text.find(snippet, idx + 1)
        return anchors


def _row_to_condition(row: sqlite3.Row) -> ChunkCondition:
    return ChunkCondition(
        anchor_id=row["anchor_id"],
        source_id=row["source_id"],
        condition_type=ConditionType(row["condition_type"]),
        value=row["value"],
        char_start=row["char_start"],
        char_end=row["char_end"],
        matched_text=row["matched_text"],
        pattern_id=row["pattern_id"],
    )


def _row_to_document(row: sqlite3.Row) -> SourceDocument:
    return SourceDocument(
        source_id=row["source_id"],
        family_id=row["family_id"],
        page1_doi=row["page1_doi"],
        original_file=row["original_file"],
        pdf_sha256=row["pdf_sha256"],
        text_sha256=row["text_sha256"],
        page_count=row["page_count"],
        text_characters=row["text_characters"],
        watermark_lines_removed=row["watermark_lines_removed"],
        manifest_warnings=tuple(json.loads(row["manifest_warnings"])),
        ingest_version=row["ingest_version"],
        ingested_at=row["ingested_at"],
    )


def _page_regions(text: str) -> list[tuple[int, int, int]]:
    """把文本切为连续页区域 [(page_no, start, end))，无缝平铺整个文本。

    ``## Page N`` 标记行为区域起点；首标记前的文件头行
    （SOURCE_ID/ORIGINAL_FILE/PDF_SHA256）并入页 1 区域，页号不重复。
    无任何标记时整体记为 page 1。
    """
    matches = list(PAGE_MARK_RE.finditer(text))
    if not matches:
        return [(1, 0, len(text))]
    regions: list[tuple[int, int, int]] = []
    for i, match in enumerate(matches):
        start = match.start() if i > 0 else 0
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        regions.append((int(match.group(1)), start, end))
    return regions


def _page_for(regions: list[tuple[int, int, int]], offset: int) -> int:
    for page_no, start, end in regions:
        if start <= offset < end:
            return page_no
    return regions[-1][0]


def _paragraph_spans(
    text: str, region_start: int, region_end: int
) -> list[tuple[int, int]]:
    """页区域内的段落 [start, end) 区间；跳过页标记行、文件头行与空行。"""
    spans: list[tuple[int, int]] = []
    pos = region_start
    para_start: int | None = None
    para_end = 0
    for line in text[region_start:region_end].splitlines(keepends=True):
        line_end = pos + len(line)
        stripped = line.strip()
        is_marker = _MARKER_LINE_RE.fullmatch(stripped) is not None
        is_header = _CORPUS_HEADER_LINE_RE.match(stripped) is not None
        if not stripped or is_marker or is_header:
            if para_start is not None:
                spans.append((para_start, para_end))
                para_start = None
        else:
            if para_start is None:
                para_start = pos
            para_end = line_end
        pos = line_end
    if para_start is not None:
        spans.append((para_start, para_end))
    return spans


def _pack_paragraphs(
    text: str,
    region_start: int,
    region_end: int,
    target_chars: int,
) -> list[tuple[int, int]]:
    """段落贪心装箱：当前块达到 target 后在下一新段落处断开。

    chunk 不跨页（页区域是天然边界）；超长单段落独立成块。
    返回相对整篇文本的 [start, end) 区间，文本切片保证精确可还原。
    """
    packed: list[tuple[int, int]] = []
    start: int | None = None
    end = 0
    for para_start, para_end in _paragraph_spans(text, region_start, region_end):
        if start is None:
            start, end = para_start, para_end
            continue
        if end - start >= target_chars:
            packed.append((start, end))
            start, end = para_start, para_end
        else:
            end = para_end
    if start is not None:
        packed.append((start, end))
    return packed
