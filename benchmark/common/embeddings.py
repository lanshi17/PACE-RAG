"""查询向量缓存（PACE 批次十一）。

三路召回里的 embedding 通道需要把**查询**编码成与投影同一模型的向量
（本项目为 ``text-embedding-3-large`` / 3072 维）。为了不每次探针都触网，
这里固化"编一次、之后离线复用"的缓存层：

- 缓存文件是 JSON：``{"model": …, "dimensions": …, "queries": {"<qid>": "<base64 float32>"}}``；
- :func:`load_query_vectors` 在缓存命中时**完全不触网**（门禁里的真实执行即走
  这条路径，保证离线可复现）；缓存缺失或 ``refresh=True`` 时才调用 API；
- 维度不符**立即报错**，不做静默截断——维度错了后续余弦全错。
"""

from __future__ import annotations

import base64
import json
from array import array
from collections.abc import Sequence
from pathlib import Path

from benchmark.config.environment import load_environment

BATCH = 10


def encode_vector(vector: Sequence[float]) -> str:
    """把向量编码为 base64 float32（与投影 ``matrix`` 同口径）。"""
    return base64.b64encode(array("f", vector).tobytes()).decode("ascii")


def decode_vector(payload: str) -> list[float]:
    """把 :func:`encode_vector` 的产物解码回浮点列表。"""
    decoded = array("f")
    decoded.frombytes(base64.b64decode(payload))
    return list(decoded)


def embed_queries(
    queries: Sequence[tuple[str, str]], dimensions: int
) -> dict[str, list[float]]:
    """调用 embedding API 编码查询（本模块唯一触网处）。

    Raises
    ------
    RuntimeError : 未配置 ``RAG_API_KEY``。
    ValueError : 返回维度与 ``dimensions`` 不符。
    """
    from openai import OpenAI

    env = load_environment()
    if not env.api_key:
        raise RuntimeError("缺少 RAG_API_KEY，无法生成查询向量缓存")
    client = OpenAI(api_key=env.api_key, base_url=env.api_base)
    vectors: dict[str, list[float]] = {}
    for start in range(0, len(queries), BATCH):
        batch = list(queries[start : start + BATCH])
        response = client.embeddings.create(
            model=env.embedding_model, input=[text for _, text in batch]
        )
        for (question_id, _), item in zip(batch, response.data):
            vector = list(item.embedding)
            if len(vector) != dimensions:
                raise ValueError(f"查询向量维度 {len(vector)} 与索引维度 {dimensions} 不符")
            vectors[question_id] = vector
    return vectors


def load_query_vectors(
    path: Path,
    queries: Sequence[tuple[str, str]],
    dimensions: int,
    *,
    refresh: bool = False,
) -> dict[str, list[float]]:
    """返回 ``question_id -> 查询向量``；缓存命中时不触网。"""
    if not refresh and path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        cached = {
            question_id: decode_vector(encoded)
            for question_id, encoded in payload["queries"].items()
        }
        if all(question_id in cached for question_id, _ in queries):
            return cached
    vectors = embed_queries(queries, dimensions)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "model": load_environment().embedding_model,
                "dimensions": dimensions,
                "queries": {
                    question_id: encode_vector(vector)
                    for question_id, vector in vectors.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return vectors


__all__ = [
    "BATCH",
    "decode_vector",
    "embed_queries",
    "encode_vector",
    "load_query_vectors",
]
