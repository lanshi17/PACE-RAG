#!/usr/bin/env bash
# Gauntlet entry point for the corpus-identity change (old-coder skill).
# Runs every layer in sequence with explicit exit-code handling and a
# layer-manifest audit; exits nonzero on the first broken layer.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"
RUN=""
fail() { echo "GAUNTLET FAILED at layer: $1"; exit 1; }
mark() { RUN="$RUN $1"; }

# Freshness by mechanism: no layer may read a previous run's artifacts.
rm -f coverage.json .coverage

uv run pytest -q && mark tests || fail "full-suite"

rm -f coverage.json
uv run --with pytest-cov pytest tests/test_common_corpus.py \
  tests/test_common_unified_corpus.py \
  --cov=benchmark.common --cov-branch --cov-report=term-missing \
  --cov-report=json:coverage.json && mark coverage-run || fail "coverage-run"
uv run python benchmark/report/old-coder/check_changed_coverage.py coverage.json \
  && mark coverage-gate || fail "changed-line-coverage-gate"

uv run --with mypy mypy --ignore-missing-imports \
  benchmark/common/corpus.py benchmark/common/unified_corpus.py \
  && mark types || fail "types-mypy"

uv run ruff check \
  benchmark/common/corpus.py \
  benchmark/common/unified_corpus.py \
  benchmark/report/corpus_diff_probe.py \
  benchmark/report/condition_density_probe.py \
  tests/test_common_corpus.py \
  tests/test_common_unified_corpus.py \
  benchmark/report/old-coder && mark lint || fail "lint-ruff"

uv run --with hypothesis python benchmark/report/old-coder/property_doi.py \
  && mark property || fail "property-doi"

uv run python benchmark/report/old-coder/mutation_corpus_identity.py \
  && mark mutation || fail "mutation-manual"
uv run --with hypothesis python benchmark/report/old-coder/property_plan_family.py \
  && mark property || fail "property-plan-family"

uv run python benchmark/report/old-coder/real_execution_check.py \
  && mark real-execution || fail "real-execution"

uv run --with pytest-randomly pytest -q -p randomly --randomly-seed=20260914 \
  && mark suite-health || fail "suite-health"

for layer in tests coverage-run coverage-gate types lint property mutation \
             real-execution suite-health; do
  case " $RUN " in
    *" $layer "*) : ;;
    *) echo "GAUNTLET FAILED: layer '$layer' never ran"; exit 1 ;;
  esac
done
echo "GAUNTLET PASS — layers:$RUN"
