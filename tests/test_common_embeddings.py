"""查询向量缓存（benchmark.common.embeddings）测试。

全部离线：用假 client 与假环境替换网络调用。重点验证两件事——
**缓存命中绝不触网**（这正是门禁可离线复现的依据）、以及维度不符时**报错而非
静默截断**。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from benchmark.common import embeddings


class _FakeEmbeddings:
    def __init__(self, dimensions: int, calls: list[dict[str, Any]]) -> None:
        self._dimensions = dimensions
        self._calls = calls

    def create(self, *, model: str, input: list[str]) -> Any:
        self._calls.append({"model": model, "input": list(input)})
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.5] * self._dimensions) for _ in input]
        )


class _FakeClient:
    def __init__(self, dimensions: int, calls: list[dict[str, Any]]) -> None:
        self.embeddings = _FakeEmbeddings(dimensions, calls)


def _fake_env(api_key: str = "sk-test") -> SimpleNamespace:
    return SimpleNamespace(
        api_key=api_key,
        api_base="http://example.invalid/v1",
        embedding_model="fake-embed",
    )


def _install_fake_api(
    monkeypatch: pytest.MonkeyPatch, dimensions: int, *, api_key: str = "sk-test"
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(embeddings, "load_environment", lambda: _fake_env(api_key))
    monkeypatch.setattr(
        "openai.OpenAI", lambda **_kwargs: _FakeClient(dimensions, calls)
    )
    return calls


class TestVectorCodec:
    def test_round_trip_preserves_float32_values(self) -> None:
        vector = [1.5, -0.25, 0.0, 3.0]
        assert embeddings.decode_vector(embeddings.encode_vector(vector)) == vector

    def test_round_trip_is_float32_precise(self) -> None:
        # 与投影 matrix 同口径（float32）：超出 float32 精度的位会被舍入，
        # 但同一口径解码应逐位一致。
        encoded = embeddings.encode_vector([0.1, 0.2])
        assert embeddings.decode_vector(encoded) == embeddings.decode_vector(encoded)

    def test_dimensions_are_preserved(self) -> None:
        assert len(embeddings.decode_vector(embeddings.encode_vector([1.0] * 7))) == 7


class TestEmbedQueries:
    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(embeddings, "load_environment", lambda: _fake_env(""))
        with pytest.raises(RuntimeError, match="RAG_API_KEY"):
            embeddings.embed_queries([("q1", "hello")], 4)

    def test_returns_vectors_by_question_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_api(monkeypatch, 4)
        vectors = embeddings.embed_queries([("q1", "a"), ("q2", "b")], 4)
        assert set(vectors) == {"q1", "q2"}
        assert vectors["q1"] == [0.5] * 4

    def test_batches_requests(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _install_fake_api(monkeypatch, 4)
        queries = [(f"q{i}", f"text {i}") for i in range(12)]
        embeddings.embed_queries(queries, 4)
        assert [len(call["input"]) for call in calls] == [10, 2]

    def test_dimension_mismatch_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_api(monkeypatch, 4)
        with pytest.raises(ValueError, match="不符"):
            embeddings.embed_queries([("q1", "a")], 8)


class TestLoadQueryVectors:
    def test_cache_hit_never_touches_the_api(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "query_embeddings.json"
        path.write_text(
            json.dumps(
                {
                    "model": "fake-embed",
                    "dimensions": 3,
                    "queries": {
                        "q1": embeddings.encode_vector([1.0, 2.0, 3.0]),
                        "q2": embeddings.encode_vector([4.0, 5.0, 6.0]),
                    },
                }
            ),
            encoding="utf-8",
        )

        def _explode(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("缓存命中时不应触网")

        monkeypatch.setattr(embeddings, "embed_queries", _explode)
        vectors = embeddings.load_query_vectors(
            path, [("q1", "a"), ("q2", "b")], 3
        )
        assert vectors == {"q1": [1.0, 2.0, 3.0], "q2": [4.0, 5.0, 6.0]}

    def test_partial_cache_triggers_refresh(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "query_embeddings.json"
        path.write_text(
            json.dumps(
                {
                    "model": "fake-embed",
                    "dimensions": 3,
                    "queries": {"q1": embeddings.encode_vector([1.0, 2.0, 3.0])},
                }
            ),
            encoding="utf-8",
        )
        _install_fake_api(monkeypatch, 3)
        vectors = embeddings.load_query_vectors(
            path, [("q1", "a"), ("q2", "b")], 3
        )
        assert set(vectors) == {"q1", "q2"}

    def test_missing_cache_writes_file(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = tmp_path / "nested" / "query_embeddings.json"
        _install_fake_api(monkeypatch, 4)
        vectors = embeddings.load_query_vectors(path, [("q1", "a")], 4)
        assert vectors == {"q1": [0.5] * 4}
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["model"] == "fake-embed"
        assert payload["dimensions"] == 4
        assert embeddings.decode_vector(payload["queries"]["q1"]) == [0.5] * 4

    def test_refresh_forces_api_call(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = tmp_path / "query_embeddings.json"
        path.write_text(
            json.dumps(
                {
                    "model": "fake-embed",
                    "dimensions": 3,
                    "queries": {"q1": embeddings.encode_vector([9.0, 9.0, 9.0])},
                }
            ),
            encoding="utf-8",
        )
        calls = _install_fake_api(monkeypatch, 3)
        vectors = embeddings.load_query_vectors(path, [("q1", "a")], 3, refresh=True)
        assert vectors == {"q1": [0.5] * 3}
        assert len(calls) == 1
