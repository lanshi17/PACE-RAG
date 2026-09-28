#!/usr/bin/env bash
# Record the audited source state (old-coder EVIDENCE requirement).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../.."
echo "HEAD=$(git rev-parse HEAD)"
echo "dirty_entries=$(git status --porcelain | wc -l)"
git status --porcelain -- \
  benchmark/common/corpus.py \
  benchmark/common/unified_corpus.py \
  tests/test_common_corpus.py \
  tests/test_common_unified_corpus.py \
  benchmark/report/corpus_diff_probe.py \
  benchmark/report/condition_density_probe.py \
  benchmark/report/old-coder
for f in \
  benchmark/common/corpus.py \
  benchmark/common/unified_corpus.py \
  benchmark/report/corpus_diff_probe.py \
  benchmark/report/condition_density_probe.py \
  tests/test_common_corpus.py \
  tests/test_common_unified_corpus.py; do
  echo "sha256($f)=$(sha256sum "$f" | cut -d' ' -f1)"
done
