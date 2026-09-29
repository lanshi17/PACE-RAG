#!/usr/bin/env bash
# 五框架 62 题统一受控实验运行入口（见 docs/2026-09-29/unified62-preregistration.md）。
# 冻结条件：数据集 unified_62.json / 生成 gpt-5-mini / 向量 text-embedding-3-large /
# Judge gpt-5 required / top-k 16 / hybrid / 题序 seed=42。
# 用法：
#   bash benchmark/unified62/run_unified62.sh index     # 阶段 A：五框架重建索引（耗时数小时）
#   bash benchmark/unified62/run_unified62.sh evaluate  # 阶段 B：五框架评测
#   bash benchmark/unified62/run_unified62.sh gate      # 门禁：benchmark_conditions 两两可比性校验
set -euo pipefail
cd "$(dirname "$0")/../.."

MODE="${1:-}"
DATASET="benchmark/qa/dataset/unified_62.json"
ORDER="benchmark/unified62/run_order_seed42.txt"
OUTDIR="benchmark/results/unified62"

# seed=42 打乱后的 question_id 顺序（预注册 §1；各框架 --question-id 逐题传入保证同序）。
# 生成：python3 -c "import random,json; rng=random.Random(42); qs=json.load(open('benchmark/qa/dataset/unified_62.json')); o=list(range(62)); rng.shuffle(o); print('\n'.join(qs[i]['question_id'] for i in o))"

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
    mkdir -p "$OUTDIR"
    run_fw() { # $1=key, 余下为evaluate命令前缀
      local key="$1"; shift
      echo "==> $key evaluate (62题)"
      local args=()
      for q in "${QIDS[@]}"; do args+=(--question-id "$q"); done
      # shellcheck disable=SC2068
      uv run python $@ --output "$OUTDIR/$key/evaluation.json" "${args[@]}"
    }
    run_fw graphrag -m benchmark.baseline.microsoft_graphrag_client.benchmark evaluate \
      --project-dir benchmark/data/microsoft_graphrag_unified62 $COMMON_EVAL --method adaptive
    run_fw lightrag -m benchmark.baseline.light_rag_client.benchmark evaluate \
      --project-dir benchmark/data/light_rag_unified62 $COMMON_EVAL --method adaptive
    run_fw pathrag -m benchmark.baseline.pathrag_client.benchmark evaluate \
      --project-dir benchmark/data/path_rag_unified62 $COMMON_EVAL --method adaptive
    run_fw kag -m benchmark.baseline.kag_client.benchmark evaluate \
      --project-dir benchmark/data/kag_unified62 $COMMON_EVAL --method adaptive
    run_fw hipporag -m benchmark.baseline.hippo_rag_client.benchmark evaluate \
      --save-dir benchmark/data/hipporag_unified62 $COMMON_EVAL
esac
