#!/usr/bin/env bash
# Gauntlet entry point for the chunk-level condition extraction task
# (old-coder skill).  Runs every layer in sequence with explicit exit-code
# handling and a layer-manifest audit; exits nonzero on the first broken
# layer.  All layers run fresh: coverage artifacts are removed first.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"
RUN=""
fail() { echo "GAUNTLET FAILED at layer: $1"; exit 1; }
mark() { RUN="$RUN $1"; }

# Freshness by mechanism: no layer may read a previous run's artifacts.
rm -f coverage.json .coverage

uv run --with pytest --with hypothesis python -m pytest tests/ \
  && mark tests || fail "full-suite"

uv run --with pytest --with hypothesis --with pytest-cov \
  python -m pytest \
  tests/test_prenatal_conditions.py \
  tests/test_prenatal_conditions_extract.py \
  tests/test_prenatal_conditions_groups.py \
  tests/test_prenatal_rag_client.py \
  tests/test_prenatal_gestational_age.py \
  tests/test_prenatal_gestational_age_unbounded.py \
  --cov=prenatal_rag --cov-branch --cov-report=term-missing \
  --cov-report=json:coverage.json \
  && mark coverage-run || fail "coverage-run"
uv run python benchmark/report/old-coder/check_changed_coverage_conditions.py coverage.json \
  && mark coverage-gate || fail "changed-line-coverage-gate"

uv run --with mypy mypy --ignore-missing-imports \
  prenatal_rag/conditions/schema.py \
  prenatal_rag/conditions/extract.py \
  prenatal_rag/conditions/filter.py \
  prenatal_rag/conditions/query.py \
  prenatal_rag/applicability/gestational_age.py \
  && mark types || fail "types-mypy"

uv run ruff check \
  prenatal_rag/conditions \
  prenatal_rag/__init__.py \
  prenatal_rag/applicability \
  benchmark/report/old-coder/mutation_conditions.py \
  benchmark/report/old-coder/property_conditions.py \
  benchmark/report/old-coder/check_changed_coverage_conditions.py \
  benchmark/report/old-coder/real_execution_conditions.py \
  tests/test_prenatal_conditions.py \
  tests/test_prenatal_conditions_extract.py \
  tests/test_prenatal_conditions_groups.py \
  tests/test_prenatal_rag_client.py \
  tests/test_prenatal_gestational_age_unbounded.py \
  && mark lint || fail "lint-ruff"

uv run --with pytest --with hypothesis python -m pytest \
  benchmark/report/old-coder/property_conditions.py \
  && mark property || fail "property-hypothesis"

uv run python benchmark/report/old-coder/mutation_conditions.py \
  && mark mutation || fail "mutation-manual"
uv run python benchmark/report/old-coder/mutation_conditions.py --negative-control \
  && mark mutation-negative-control || fail "mutation-negative-control"

uv run python benchmark/report/old-coder/real_execution_conditions.py \
  && mark real-execution || fail "real-execution"

uv run --with pytest --with hypothesis --with pytest-randomly \
  python -m pytest tests/ -p randomly --randomly-seed=20260917 \
  && mark suite-health || fail "suite-health"

for layer in tests coverage-run coverage-gate types lint property mutation \
             mutation-negative-control real-execution suite-health; do
  case " $RUN " in
    *" $layer "*) : ;;
    *) echo "GAUNTLET FAILED: layer '$layer' never ran"; exit 1 ;;
  esac
done
echo "GAUNTLET PASS — layers:$RUN"
