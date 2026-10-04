"""门禁：五框架 unified62 产物 benchmark_conditions 两两可比性校验。

用法：uv run python benchmark/unified62/check_conditions.py
退出码 0 = §2 门禁字段全部一致；非 0 = 列出不一致字段并拒绝汇总。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from benchmark.common.benchmark_protocol import assert_comparable_conditions  # noqa: E402

FRAMEWORKS = ["graphrag", "lightrag", "pathrag", "kag", "hipporag"]

# 预注册 §2 门禁字段：处理变量 requested_search_method 允许不同，其余必须一致。
GATE_FIELDS = [
    "dataset_sha256",
    "corpus_fingerprint",
    "scoring_config_sha256",
    "judge_mode",
    "judge_model",
    "completion_model",
    "embedding_model",
    "top_k",
]


def _load_conditions(framework: str) -> dict:
    path = REPO / "benchmark" / "results" / "unified62" / framework / "evaluation.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))["metadata"]
    return {
        key: metadata["benchmark_conditions"][key]
        for key in GATE_FIELDS
        if key in metadata["benchmark_conditions"]
    }


def main() -> int:
    available = [
        fw
        for fw in FRAMEWORKS
        if (REPO / "benchmark" / "results" / "unified62" / fw / "evaluation.json").is_file()
    ]
    if len(available) < 2:
        print(f"门禁跳过：仅 {len(available)} 个框架产物，需 ≥2 个才能校验。")
        return 2
    conditions = {fw: _load_conditions(fw) for fw in available}
    base, *rest = available
    failed = False
    for other in rest:
        try:
            assert_comparable_conditions(conditions[base], conditions[other])
            print(f"OK  {base} == {other}")
        except ValueError as exc:
            failed = True
            print(f"FAIL {base} != {other}: {exc}")
    if failed:
        print("门禁拒绝：按预注册 §2 不得汇总。", file=sys.stderr)
        return 1
    print(f"门禁通过：{len(available)} 框架统一条件一致，可以汇总（{', '.join(available)}）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
