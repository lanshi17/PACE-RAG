#!/usr/bin/env bash
# Record the audited source state for the conditions task (old-coder EVIDENCE).
# No checkpoint commits (user decision): identify the state by sha256 of every
# task file plus the HEAD and dirty-entry count of the surrounding tree.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../.."
echo "HEAD=$(git rev-parse HEAD)"
echo "dirty_entries=$(git status --porcelain | wc -l)"
for f in \
  prenatal_rag/__init__.py \
  prenatal_rag/applicability/__init__.py \
  prenatal_rag/applicability/gestational_age.py \
  prenatal_rag/conditions/__init__.py \
  prenatal_rag/conditions/schema.py \
  prenatal_rag/conditions/extract.py \
  prenatal_rag/conditions/filter.py \
  prenatal_rag/conditions/query.py \
  prenatal_rag/evidence_store/__init__.py \
  prenatal_rag/evidence_store/store.py \
  prenatal_rag/evidence_store/ingest.py \
  prenatal_rag/retrieval/__init__.py \
  prenatal_rag/retrieval/bm25.py \
  tests/test_prenatal_conditions.py \
  tests/test_prenatal_conditions_materialize.py \
  tests/test_prenatal_conditions_extract.py \
  tests/test_prenatal_conditions_groups.py \
  tests/test_prenatal_rag_client.py \
  tests/test_prenatal_gestational_age.py \
  tests/test_prenatal_gestational_age_unbounded.py \
  tests/test_prenatal_evidence_store.py \
  tests/test_prenatal_bm25.py \
  benchmark/report/old-coder/SPEC-conditions.md \
  benchmark/report/old-coder/EVIDENCE-conditions.md \
  benchmark/report/old-coder/gauntlet_conditions.sh \
  benchmark/report/old-coder/mutation_conditions.py \
  benchmark/report/old-coder/property_conditions.py \
  benchmark/report/old-coder/check_changed_coverage_conditions.py \
  benchmark/report/old-coder/real_execution_conditions.py; do
  if [ -f "$f" ]; then
    echo "sha256($f)=$(sha256sum "$f" | cut -d' ' -f1)"
  else
    echo "sha256($f)=MISSING"
  fi
done
