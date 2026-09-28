"""受控生成器：对给定上下文集合调用 LLM 生成答案。

``llm_func`` 可注入（测试用 stub，真实运行用 LightRAG 默认补全），
使管道可在不消耗 token 的情况下被验证。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from benchmark.baseline.prenatal_rag_client.prompting import build_generation_messages

LlmFunc = Callable[[str, str], Awaitable[Any]]


def _coerce_text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict) and raw.get("content") is not None:
        return str(raw["content"]).strip()
    return str(raw).strip()


async def _lightrag_complete(system_prompt: str, user_prompt: str) -> Any:
    """真实补全：复用 LightRAGClient 的默认补全（读 benchmark/.env）。"""
    from benchmark.baseline.light_rag_client import LightRAGClient

    return await LightRAGClient._default_llm(
        user_prompt,
        system_prompt=system_prompt,
    )


async def a_generate(
    question: Any,
    contexts: list[dict[str, str]],
    *,
    llm_func: LlmFunc | None = None,
) -> str:
    """异步受控生成：由 ``contexts`` 构造提示词并调用 ``llm_func``。

    ``llm_func`` 签名 ``async (system_prompt, user_prompt) -> raw``。
    隐式 None 时为真实补全（需 API）。
    """
    system_prompt, user_prompt = build_generation_messages(question, contexts)
    fn: LlmFunc = llm_func if llm_func is not None else _lightrag_complete
    raw = await fn(system_prompt, user_prompt)
    return _coerce_text(raw)


def generate_with_context(
    question: Any,
    contexts: list[dict[str, str]],
    *,
    llm_func: Callable[[str, str], Any] | None = None,
) -> str:
    """同步包装：在独立事件循环里执行 ``a_generate``。"""
    import asyncio

    async def _wrap(system_prompt: str, user_prompt: str) -> Any:
        # 允许传入同步 stub：逐字返回
        if llm_func is None:
            return await _lightrag_complete(system_prompt, user_prompt)
        result = llm_func(system_prompt, user_prompt)
        if isinstance(result, Awaitable):
            return await result
        return result

    return asyncio.run(
        a_generate(question, contexts, llm_func=_wrap)  # type: ignore[arg-type]
    )