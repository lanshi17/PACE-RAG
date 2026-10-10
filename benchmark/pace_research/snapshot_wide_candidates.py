"""R0 宽候选快照：三路 rank 全量（M 前），保存排名/分数/来源/锚点。

产出 ``retrieval.jsonl``（每题一行：三路各自的有序候选及元数据）+ ``snapshot.json``
（配置指纹：语料/索引/模型/参数）。零 LLM——BM25/图/向量均为本地确定性计算；
查询向量从既有 ``query_embeddings.json`` 缓存读取（与批次十一同一缓存，不触网）。

用法：
  uv run python benchmark/pace_research/snapshot_wide_candidates.py \
      --out benchmark/results/pace_research/r0/snapshot \
      [--limit N] [--question-ids ID1,ID2]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "benchmark" / "baseline" / "libs" / "light_rag"))

from prenatal_rag.conditions import parse_query_conditions  # noqa: E402
from prenatal_rag.evidence_store import EvidenceStore  # noqa: E402
from prenatal_rag.retrieval import (  # noqa: E402
    Bm25Index,
    EmbeddingChannel,
    GraphChannel,
    LightRagChunkGraph,
    OverlapBridge,
    VectorIndex,
    condition_seed_anchors,
)

DEFAULT_CORPUS = REPO / "benchmark" / "data" / "corpus"
DEFAULT_EVIDENCE_STORE = REPO / "benchmark" / "data" / "evidence_store"
DEFAULT_LIGHT_RAG = REPO / "benchmark" / "data" / "light_rag_unified62" / "rag_storage" / "light_rag_unified62"
DEFAULT_QUERY_EMBEDDINGS = REPO / "benchmark" / "results" / "corpus-condition-20260915" / "query_embeddings.json"
DEFAULT_DATASET = REPO / "benchmark" / "qa" / "dataset" / "unified_62_seed42.json"
DEFAULT_M = 40


def _load_query_vectors(path: Path) -> dict[str, list[float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "queries" in payload:
        payload = payload["queries"]
    out: dict[str, list[float]] = {}
    for qid, vector in payload.items():
        if isinstance(vector, str):
            raw = base64.b64decode(vector)
            import array

            floats = array.array("f")
            floats.frombytes(raw)
            if sys.byteorder == "big":
                floats.byteswap()
            vector = list(floats)
        out[qid] = [float(x) for x in vector]
    return out


def _norm(s: str) -> str:
    import re as _re

    return _re.sub(r"\s+", " ", s)


def _load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_snapshot(out_dir: Path, *, m: int, limit: int | None, question_ids: list[str]) -> None:
    questions = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
    if question_ids:
        wanted = set(question_ids)
        questions = [q for q in questions if q["question_id"] in wanted]
    if limit is not None:
        questions = questions[:limit]
    if not questions:
        raise SystemExit("no questions selected")

    store = EvidenceStore(DEFAULT_EVIDENCE_STORE)
    bm25 = Bm25Index.from_store(store)

    vdb_path = DEFAULT_LIGHT_RAG / "vdb_chunks.json"
    graph_dir = DEFAULT_LIGHT_RAG
    import json as _json

    vdb_payload = _json.loads(vdb_path.read_text(encoding="utf-8"))
    # nano-vectordb data 行带 __id__ 与 content（chunk 全文）；用 content 归一化哈希
    # 对回真值层 chunk（LightRAG chunk 键 = md5(f"{doc_id}:{content}") 无法直接逆，
    # 故用 content 精确匹配真值层 text）。
    # LightRAG chunk 文本 = 3 行头（SOURCE_ID/ORIGINAL_FILE/PDF_SHA256）+ PDF 原文；
    # 真值层 chunk 文本是归一化后的统一语料切片，两者无子串关系可言（头/页标记/归一化）。
    # 桥接：vdb 行按头部 SOURCE_ID 前缀 → manifest source_id → 该 source 的真值层
    # chunk 池，取归一化 containment 最长（≥60 字符前缀定位 + ≥90% 覆盖）的 chunk。
    # 实测 24/26 行 ≥90%（其余 2 行为版本差异文档），468 行中 442 行无 SOURCE_ID 头
    # （LightRAG 1200-token 切分的后续段），这些行无头部信息，桥接按同 source 内
    # 已桥接行的文本连续性顺延（后续行属于同一 source 的概率由 vdb file_path 承担）。
    manifest = _load_manifest(DEFAULT_CORPUS / "corpus_manifest.json")
    store_chunks = list(store.iter_chunks())
    sids = {d["source_id"] for d in manifest.get("documents", [])}
    chunks_by_source: dict[str, list[Any]] = {}
    for chunk in store_chunks:
        chunks_by_source.setdefault(chunk.source_id, []).append(chunk)
    for key in chunks_by_source:
        chunks_by_source[key].sort(key=lambda c: (c.page_start, c.char_start))

    vdb_key_to_anchor: dict[str, int] = {}
    row_meta: dict[str, dict[str, Any]] = {}
    low_cov = 0
    for record in vdb_payload["data"]:
        content = str(record.get("content", ""))
        if not content.startswith("SOURCE_ID:"):
            # LightRAG 1200-token 切分的后续段：无 SOURCE_ID 头。source 由
            # full_doc_id 前缀解析；锚点 = 该 source 池内与正文归一化 containment
            # 最长的 chunk（与 headered 行同一逻辑，只是没有头部信息）。
            full_doc = str(record.get("full_doc_id", ""))
            cands = [s for s in sids if full_doc.startswith(s) or s.startswith(full_doc)]
            if not cands:
                row_meta[record["__id__"]] = {"bridge": "no_source", "anchor": None}
                continue
            sid = max(cands, key=len)
            body = _norm(content.replace("## Page 1", " ").replace("## Page 2", " "))
            best, best_match = None, 0
            body_prefix = body[:200]
            for chunk in chunks_by_source.get(sid, []):
                ntext = _norm(chunk.text)
                if len(ntext) < 50:
                    continue
                # 主方向：chunk 前缀出现在 body 中（chunk ⊂ body）
                prefix = ntext[:200]
                pos = body.find(prefix)
                if pos >= 0:
                    extend = len(prefix)
                    while (
                        pos + extend < len(body)
                        and extend < len(ntext)
                        and body[pos + extend] == ntext[extend]
                    ):
                        extend += 1
                    if extend > best_match:
                        best, best_match = chunk, extend
                    continue
                # 回退方向：body 前缀出现在 chunk 中（vdb 行起始于 chunk 中段）
                pos = ntext.find(body_prefix[:80])
                if pos >= 0:
                    extend = 0
                    while (
                        extend < len(body_prefix)
                        and pos + extend < len(ntext)
                        and body_prefix[extend] == ntext[pos + extend]
                    ):
                        extend += 1
                    if extend > best_match:
                        best, best_match = chunk, extend
            if best is None or best_match < 60:
                low_cov += 1
                row_meta[record["__id__"]] = {"bridge": "low_containment", "anchor": None}
                continue
            vdb_key_to_anchor[record["__id__"]] = best.anchor_id
            row_meta[record["__id__"]] = {"bridge": "ok", "anchor": best.anchor_id, "match_chars": best_match}
            continue
        first_nl = content.find("\n")
        sid_full = content[len("SOURCE_ID:") : first_nl].strip()
        cands = [s for s in sids if sid_full.startswith(s) or s.startswith(sid_full)]
        if not cands:
            row_meta[record["__id__"]] = {"bridge": "no_source", "anchor": None}
            continue
        sid = max(cands, key=len)
        parts = content.split("\n")
        body = _norm(
            ("\n".join(parts[3:])).replace("## Page 1", " ").replace("## Page 2", " ")
        )
        best, best_match = None, 0
        body_prefix = body[:200]
        for chunk in chunks_by_source.get(sid, []):
            ntext = _norm(chunk.text)
            if len(ntext) < 50:
                continue
            prefix = ntext[:200]
            pos = body.find(prefix)
            if pos >= 0:
                extend = len(prefix)
                while (
                    pos + extend < len(body)
                    and extend < len(ntext)
                    and body[pos + extend] == ntext[extend]
                ):
                    extend += 1
                if extend > best_match:
                    best, best_match = chunk, extend
                continue
            pos = ntext.find(body_prefix[:80])
            if pos >= 0:
                extend = 0
                while (
                    extend < len(body_prefix)
                    and pos + extend < len(ntext)
                    and body_prefix[extend] == ntext[pos + extend]
                ):
                    extend += 1
                if extend > best_match:
                    best, best_match = chunk, extend
        if best is None or best_match < 60:
            low_cov += 1
            row_meta[record["__id__"]] = {"bridge": "low_containment", "anchor": None}
            continue
        vdb_key_to_anchor[record["__id__"]] = best.anchor_id
        row_meta[record["__id__"]] = {"bridge": "ok", "anchor": best.anchor_id, "match_chars": best_match}
    if low_cov:
        print(f"bridge: low_containment_rows={low_cov}", flush=True)

    index = VectorIndex.from_vdb_json(vdb_path)
    bridge = OverlapBridge(vdb_key_to_anchor)
    graph = LightRagChunkGraph.from_index_dir(graph_dir)
    graph_channel = GraphChannel(graph, bridge)
    embedding_channel = EmbeddingChannel(index, bridge)
    query_vectors = _load_query_vectors(DEFAULT_QUERY_EMBEDDINGS)

    manifest = json.loads((DEFAULT_CORPUS / "corpus_manifest.json").read_text(encoding="utf-8"))
    snapshot = {
        "protocol": {
            "m_candidates": m,
            "bm25_k1_b": [bm25._k1, bm25._b],
            "graph_hops": graph_channel.hops,
            "graph_k_expand": graph_channel.k_expand,
            "embedding_dim": index.dimensions,
            "corpus_fingerprint": hashlib.sha256(
                json.dumps(
                    [
                        {
                            "source_id": d.get("source_id"),
                            "pdf_sha256": d.get("pdf_sha256"),
                            "input_file": d.get("input_file"),
                            "status": d.get("status"),
                        }
                        for d in manifest.get("documents", [])
                    ],
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
            "evidence_store_sha256": _sha256_file(DEFAULT_EVIDENCE_STORE / "evidence.db")
            if (DEFAULT_EVIDENCE_STORE / "evidence.db").is_file()
            else None,
            "vdb_sha256": _sha256_file(vdb_path),
            "query_embeddings_sha256": _sha256_file(DEFAULT_QUERY_EMBEDDINGS),
            "dataset_sha256": _sha256_file(DEFAULT_DATASET),
            "bm25_index_source": "evidence_store",
            "graph_index_source": str(graph_dir),
            "vector_index_source": str(vdb_path),
        },
        "questions": {},
    }

    missing_vectors: list[str] = []
    anchor_to_chunk = {chunk.anchor_id: chunk for chunk in store.iter_chunks()}
    out_dir.mkdir(parents=True, exist_ok=True)
    retrieval_path = out_dir / "retrieval.jsonl"

    with retrieval_path.open("w", encoding="utf-8") as stream:
        for question in questions:
            qid = question["question_id"]
            text = question["question"]
            query = parse_query_conditions(text)
            pool = set(condition_seed_anchors(store, query))

            bm25_rows = bm25.search(text, k=m)
            bm25_ranking = [r.chunk_id for r in bm25_rows]
            graph_ranking = graph_channel.rank(pool, k=m)
            vector_ranking: list[int] = []
            qv = query_vectors.get(qid)
            if qv is None:
                missing_vectors.append(qid)
            else:
                vector_ranking = embedding_channel.rank(qv, k=m, candidates=pool)

            def _enrich(ranking: list[int]) -> list[dict[str, Any]]:
                rows: list[dict[str, Any]] = []
                for rank, anchor_id in enumerate(ranking, start=1):
                    chunk = anchor_to_chunk.get(anchor_id)
                    rows.append(
                        {
                            "rank": rank,
                            "anchor_id": anchor_id,
                            "source_id": getattr(chunk, "source_id", None) if chunk else None,
                            "text_sha256": getattr(chunk, "text_sha256", None) if chunk else None,
                        }
                    )
                return rows

            row = {
                "question_id": qid,
                "pool_size": len(pool),
                "bm25": {"ranking": bm25_ranking, "scored": _enrich(bm25_ranking),
                         "scores": {str(r.chunk_id): round(r.score, 6) for r in bm25_rows}},
                "graph": {"ranking": graph_ranking, "scored": _enrich(graph_ranking)},
                "vector": {"ranking": vector_ranking, "scored": _enrich(vector_ranking)},
                "query_conditions": {
                    "gestational_age": (
                        None
                        if query.gestational_age is None
                        else {"start": query.gestational_age.start, "end": query.gestational_age.end}
                    ),
                    "population": sorted(query.population),
                    "technique": sorted(query.technique),
                },
            }
            snapshot["questions"][qid] = {
                "pool_size": len(pool),
                "has_query_vector": qv is not None,
            }
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    snapshot["missing_query_vectors"] = missing_vectors
    (out_dir / "snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {retrieval_path} ({len(questions)} questions); missing vectors: {len(missing_vectors)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--m", type=int, default=DEFAULT_M)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--question-ids", type=str, default="")
    args = parser.parse_args()
    ids = [s for s in args.question_ids.split(",") if s]
    build_snapshot(args.out, m=args.m, limit=args.limit, question_ids=ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
