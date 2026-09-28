#!/usr/bin/env bash
# old-coder gauntlet entry point for prenatal_rag (Tier 2/3 + property/mutation).
# Fail-closed: any layer failing aborts (set -e). Run from repo root.
set -euo pipefail
cd "$(dirname "$0")/../.."

# 沙箱/宿主 /tmp 可能不可写；pytest tmp_path 需要可写临时目录。
mkdir -p .gauntlet_tmp
export TMPDIR="$PWD/.gauntlet_tmp"

echo "=====[1/6] pytest: full non-baseline suite (baseline fixtures excluded) ====="
.venv/bin/python -m pytest -q --ignore=tests/baseline

echo "=====[2/6] ruff: lint + format drift ====="
ruff check prenatal_rag/ benchmark/report/condition_extract_probe.py \
  benchmark/report/manual_mutation_prenatal.py \
  benchmark/report/b1_retrieval_ablation.py benchmark/report/graph_channel_probe.py \
  benchmark/report/b1_condition_pairs.py benchmark/qa/build_condition_pairs.py \
  benchmark/report/supersedes_probe.py benchmark/common/versions.py \
  benchmark/report/version_citation_probe.py \
  benchmark/report/embedding_channel_probe.py \
  benchmark/report/three_channel_ablation.py \
  benchmark/report/three_channel_end_to_end.py \
  benchmark/common/embeddings.py \
  benchmark/baseline/prenatal_rag_client/benchmark.py \
  benchmark/baseline/prenatal_rag_client/evaluate.py \
  tests/test_prenatal_conditions.py tests/test_prenatal_rrf.py \
  tests/test_prenatal_evidence.py tests/test_prenatal_graph.py \
  tests/test_prenatal_bridge.py tests/test_prenatal_pipeline.py \
  tests/test_prenatal_supersession.py tests/test_prenatal_version_citations.py \
  tests/test_prenatal_vectors.py tests/test_common_embeddings.py

echo "=====[3/6] pyright: static types ====="
pyright prenatal_rag/

echo "=====[4/6] coverage: conditions + retrieval, fail-under 100 ====="
.venv/bin/python -m coverage erase
.venv/bin/python -m coverage run -m pytest tests/test_prenatal_*.py -q
.venv/bin/python -m coverage report -m --fail-under=100 \
  prenatal_rag/conditions/schema.py prenatal_rag/conditions/extract.py \
  prenatal_rag/conditions/filter.py prenatal_rag/conditions/query.py \
  prenatal_rag/conditions/__init__.py
.venv/bin/python -m coverage erase
.venv/bin/python -m coverage run -m pytest tests/test_prenatal_rrf.py -q
.venv/bin/python -m coverage report -m --fail-under=100 \
  prenatal_rag/retrieval/rrf.py
.venv/bin/python -m coverage erase
.venv/bin/python -m coverage run -m pytest tests/test_prenatal_evidence.py \
  tests/test_prenatal_supersession.py -q
.venv/bin/python -m coverage report -m --fail-under=100 \
  prenatal_rag/evidence/selection.py prenatal_rag/evidence/supersession.py \
  prenatal_rag/evidence/__init__.py
.venv/bin/python -m coverage erase
.venv/bin/python -m coverage run -m pytest tests/test_prenatal_version_citations.py -q
.venv/bin/python -m coverage report -m --fail-under=100 \
  prenatal_rag/evidence/version_citations.py
.venv/bin/python -m coverage erase
.venv/bin/python -m coverage run -m pytest tests/test_prenatal_graph.py -q
.venv/bin/python -m coverage report -m --fail-under=100 \
  prenatal_rag/retrieval/graph.py
.venv/bin/python -m coverage erase
.venv/bin/python -m coverage run -m pytest tests/test_prenatal_bridge.py -q
.venv/bin/python -m coverage report -m --fail-under=100 \
  prenatal_rag/retrieval/bridge.py
.venv/bin/python -m coverage erase
.venv/bin/python -m coverage run -m pytest tests/test_prenatal_pipeline.py -q
.venv/bin/python -m coverage report -m --fail-under=100 \
  prenatal_rag/retrieval/pipeline.py
.venv/bin/python -m coverage erase
.venv/bin/python -m coverage run -m pytest tests/test_prenatal_vectors.py -q
.venv/bin/python -m coverage report -m --fail-under=100 \
  prenatal_rag/retrieval/vectors.py

echo "=====[5/6] manual mutation (49 mutants must all be killed) ====="
PYTHONPATH=. .venv/bin/python benchmark/report/manual_mutation_prenatal.py

# 缓存完整性哨兵：等长变异若在同一秒写回原文，CPython 的 mtime+size 校验会
# 认为旧 .pyc 仍有效，使后续层静默运行"变异体"。这里断言时间轴行为正确。
PYTHONPATH=. .venv/bin/python -c "
from prenatal_rag.evidence import SupersessionGraph
g = SupersessionGraph({'a': 'b', 'b': 'c'}, years={'a': 2000, 'b': 2010, 'c': 2020})
assert g.current_version_at('a', 2005) == 'a', 'bytecode cache poisoned'
assert g.current_version_at('a', 2015) == 'b', 'bytecode cache poisoned'
assert g.current_version_at('a', 2025) == 'c', 'bytecode cache poisoned'
print('cache sentinel OK')
"

echo "=====[6/6] real execution ====="
PYTHONPATH=. .venv/bin/python benchmark/report/condition_extract_probe.py | tail -6
PYTHONPATH=. .venv/bin/python benchmark/report/b1_retrieval_ablation.py | tail -9
PYTHONPATH=. .venv/bin/python benchmark/report/graph_channel_probe.py | tail -12
PYTHONPATH=. .venv/bin/python benchmark/qa/build_condition_pairs.py
PYTHONPATH=. .venv/bin/python benchmark/report/b1_condition_pairs.py | tail -18
PYTHONPATH=. .venv/bin/python benchmark/report/supersedes_probe.py | tail -8
PYTHONPATH=. .venv/bin/python benchmark/report/version_citation_probe.py | tail -9
# 走 query_embeddings.json 缓存，离线可复现；仅在缓存缺失时才触网。
PYTHONPATH=. .venv/bin/python benchmark/report/embedding_channel_probe.py | tail -7
PYTHONPATH=. .venv/bin/python benchmark/report/three_channel_ablation.py | tail -6
# 端到端两臂的**接线**验证（stub 生成器 + judge off = 零 token）；真实判定运行
# 需 API（约 1 小时），不进本脚本。--out 指到临时目录，避免覆盖真实结果。
PYTHONPATH=. .venv/bin/python benchmark/report/three_channel_end_to_end.py \
  --dry-run --limit 3 --out .gauntlet_tmp | tail -5

echo "ALL LAYERS PASS"