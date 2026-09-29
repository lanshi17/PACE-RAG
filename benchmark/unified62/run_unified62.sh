#!/usr/bin/env bash
# 五框架 62 题统一受控实验运行入口（见 docs/2026-09-29/unified62-preregistration.md）。
# 冻结条件：数据集 unified_62.json / 生成 gpt-5-mini / 向量 text-embedding-3-large /
# Judge gpt-5 required / top-k 16 / hybrid / 题序 seed=42。
# 用法：
#   bash benchmark/unified62/run_unified62.sh index     # 阶段 A：五框架重建索引（耗时数小时）
#   bash benchmark/unified62/run_unified62.sh evaluate  # 阶段 B：五框架评测
#   bash benchmark/unified62/run_unified62.sh gate      # 门禁：benchmark_conditions 两两可比性校验
set -euo pipefail
DATASET="benchmark/qa/dataset/unified_62.json"
# 题序 seed=42 预打乱文件（各客户端按数据集文件顺序执行，不保留 --question-id
# 传入顺序，故用预打乱文件保证五框架同序；生成见下）
SHUFFLED="benchmark/qa/dataset/unified_62_seed42.json"
ORDER="benchmark/unified62/run_order_seed42.txt"
OUTDIR="benchmark/results/unified62"
MODE="${1:-}"
# GraphRAG 的 settings.yaml 模板默认引用 ${GRAPHRAG_API_KEY}（上游 graphrag-llm
# 约定），而本仓统一用 benchmark/.env 的 RAG_API_KEY；此处做别名导出，不改模板。
if [ -f benchmark/.env ]; then set -a; source benchmark/.env; set +a; fi
export GRAPHRAG_API_KEY="${GRAPHRAG_API_KEY:-${RAG_API_KEY:-}}"
case "$MODE" in
  index)
    # 各客户端 preflight 要求 project_dir 已存在；先建目录（prepare 只管统一语料）。
    mkdir -p benchmark/data/microsoft_graphrag_unified62 benchmark/data/light_rag_unified62 \
      benchmark/data/path_rag_unified62 benchmark/data/kag_unified62 benchmark/data/hipporag_unified62
    uv run python -m benchmark.baseline.microsoft_graphrag_client.benchmark index \
      --project-dir benchmark/data/microsoft_graphrag_unified62 --no-cache
    echo "==> [2/5] LightRAG index"
    uv run python -m benchmark.baseline.light_rag_client.benchmark index \
      --project-dir benchmark/data/light_rag_unified62 --no-cache
    echo "==> [3/5] PathRAG index"
    uv run python -m benchmark.baseline.pathrag_client.benchmark index \
      --project-dir benchmark/data/path_rag_unified62 --no-cache
    echo "==> [4/5] KAG index"
    uv run python -m benchmark.baseline.kag_client.benchmark index \
      --project-dir benchmark/data/kag_unified62 --no-cache
    echo "==> [5/5] HippoRAG index"
    uv run python -m benchmark.baseline.hippo_rag_client.benchmark index \
      --save-dir benchmark/data/hipporag_unified62 --force
    ;;
  evaluate)
    mkdir -p "$OUTDIR"/{graphrag,lightrag,pathrag,kag,hipporag}
    # 各客户端按数据集文件顺序执行：用预打乱文件保证五框架同序（§1）。
    COMMON_EVAL="--dataset $SHUFFLED --judge-mode required --judge-model gpt-5"
    echo "==> [1/5] graphrag evaluate (62题)"
    uv run python -m benchmark.baseline.microsoft_graphrag_client.benchmark evaluate \
      --project-dir benchmark/data/microsoft_graphrag_unified62 $COMMON_EVAL --method adaptive \
      --output "$OUTDIR/graphrag/evaluation.json"
    echo "==> [2/5] lightrag evaluate (62题)"
    uv run python -m benchmark.baseline.light_rag_client.benchmark evaluate \
      --project-dir benchmark/data/light_rag_unified62 $COMMON_EVAL --method adaptive \
      --output "$OUTDIR/lightrag/evaluation.json"
    echo "==> [3/5] pathrag evaluate (62题)"
    uv run python -m benchmark.baseline.pathrag_client.benchmark evaluate \
      --project-dir benchmark/data/path_rag_unified62 $COMMON_EVAL --method adaptive \
      --output "$OUTDIR/pathrag/evaluation.json"
    echo "==> [4/5] kag evaluate (62题)"
    uv run python -m benchmark.baseline.kag_client.benchmark evaluate \
      --project-dir benchmark/data/kag_unified62 $COMMON_EVAL --method adaptive \
      --output "$OUTDIR/kag/evaluation.json"
    echo "==> [5/5] hipporag evaluate (62题)"
    uv run python -m benchmark.baseline.hippo_rag_client.benchmark evaluate \
      --save-dir benchmark/data/hipporag_unified62 $COMMON_EVAL \
      --output "$OUTDIR/hipporag/evaluation.json"
    ;;
  gate)
    uv run python benchmark/unified62/check_conditions.py
    ;;
  *)
    echo "用法: $0 {index|evaluate|gate}" >&2
    exit 1
    ;;
esac
