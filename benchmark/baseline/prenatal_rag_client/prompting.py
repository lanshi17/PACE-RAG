"""受控生成提示词构造（确定性、无副作用）。"""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = (
    "你是一名产前超声诊断循证助手。仅依据给定的【证据片段】回答临床问题，"
    "不引入片段之外的知识。每条证据带编号 [E1..En] 与来源标识。回答需给出结论，"
    "并引用所依据的证据编号与来源。若证据不足以回答，明确说明信息不充分，不得臆测。"
)


def build_generation_messages(
    question: Any,
    contexts: list[dict[str, str]],
) -> tuple[str, str]:
    """构造 ``(system_prompt, user_prompt)``。

    ``contexts`` 为 benchmark 上下文记录（含 ``text`` 与 ``source_id``）。
    仅使用记录内容；确定性格式，保证同输入同输出。
    """
    evidence_lines = []
    for index, context in enumerate(contexts, 1):
        source_id = str(context.get("source_id") or "?")
        text = str(context.get("text") or "").strip()
        evidence_lines.append(f"[E{index}] (来源:{source_id}) {text}")
    evidence_block = "\n\n".join(evidence_lines) if evidence_lines else "（无可用证据片段）"
    user_prompt = (
        f"临床问题：{question.question}\n\n"
        f"证据片段：\n{evidence_block}"
    )
    return SYSTEM_PROMPT, user_prompt