"""score_question required Judge 失败语义测试（r4-design §1.2）。"""

from __future__ import annotations

from typing import Any

import pytest

from benchmark.qa.scoring import score_question


def _question() -> Any:
    from benchmark.qa import load_questions
    from pathlib import Path

    qs = load_questions(Path("benchmark/qa/dataset/sample_questions.json"))
    return qs[0]


def _judge_result_with_error() -> dict:
    return {
        "model": "gpt-5",
        "error": "InternalServerError: Connection error",
        "usage": {"request_count": 1, "failed_request_count": 1},
    }


def test_required_raises_on_judge_error() -> None:
    with pytest.raises(ValueError, match="judge_mode=required"):
        score_question(
            _question(),
            "answer",
            [],
            "",
            judge_result=_judge_result_with_error(),
            judge_mode="required",
        )


def test_optional_falls_back_on_judge_error() -> None:
    result = score_question(
        _question(),
        "answer",
        [],
        "",
        judge_result=_judge_result_with_error(),
        judge_mode="optional",
    )
    assert result.scoring_method != "judge"
