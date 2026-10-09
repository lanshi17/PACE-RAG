# B1 过滤前置 + 去冗余：设计（2026-10-09，零 token，待配额恢复后验证）

> 动机（批次十二原话）：候选池对齐与上下文取舍，而非继续堆通道。
> 现状问题：`filter_contexts` 在检索**后**对冻结 B0 上下文过滤，50 题仅 2 题触发、
> 上下文实质没换过；`condition_seed_anchors` 只用于图通道种子，BM25/向量两路仍在全池排序。

## 1. 改动：三处，同 `prenatal_rag` 内完成

### ① 过滤前置：三路在同一适用候选池上竞争
- 新增 `prenatal_rag/retrieval/pipeline.py::prefiltered_pool(store, query) -> set[int]`：
  对真值层全部锚点跑 `classify`，返回非 `INAPPLICABLE` 锚点集（即现有
  `condition_seed_anchors` 的集合语义，改名为池）。
- 三通道 `rank()` 各加可选参数 `candidates: set[int] | None = None`：
  `None` 时行为不变（向后兼容）；非 `None` 时只对池内锚点排序/回映。
  - BM25：`Bm25Index.search` 后按 `candidates` 过滤（分数不动，只删行）。
  - 图通道：种子本就是池内锚点（`condition_seed_anchors`），扩展时丢弃池外落点。
  - 向量通道：`EmbeddingChannel.rank` 回映时跳过池外锚点（与现有"无映射跳过"同一位置）。
- `parallel_recall` 签名不变（输入已是池内排名，RRF 照常）。

### ② 去冗余：同一来源多片段不挤占 k=16 预算
- 新增 `prenatal_rag/retrieval/rrf.py::diverse_top_k(fused, k, *, source_of, max_per_source=2)`：
  按融合顺序遍历，同一 `source_id` 最多保留 2 条，补到 k=16。
- `source_of` 由 `EvidenceStore` 提供（chunk → source_id 映射已存在，
  `SourceResolver` 同源逻辑复用，不新增来源体系）。
- `max_per_source=2` 为超参数，开发集（50 题）上与 1/3 对照，选 recall 不掉的最小值。

### ③ 对照实验（单变量）
- 基线：现行 B1（检索后过滤）vs 新臂（前置过滤 + 去冗余），同 50 题、
  同 B0 冻结上下文来源、同生成器、同 Judge。
- 主指标：final；护栏：faithfulness/completeness 不得低于基线（batch12 回退是否修复是关键判断）。
- 输出：`benchmark/results/corpus-condition-*/b1_prefilter.json`（产物格式沿用
  `b1_end_to_end_ctrl.json`：`arms/{b0_ctrl,b1}` + `per_question`）。

## 2. 不做的事
- 不改 `classify` 三值语义（Unknown 不得剔除，主文档 §4.2）。
- 不改 RRF 公式、不碰 embedding/reranker 训练。
- 不动 benchmark 客户端接线（`prenatal_rag_client` 只换 `contexts_provider` 的供给函数）。

## 3. 验证（零 token 现在可做 / 需配额后做）
- [x] 设计文档（本文件）。
- [ ] 离线单测：池过滤确定性、前置 vs 后置在 Inapplicable=0 的题上输出一致（回归）、
  去冗余 `max_per_source` 边界（k=16、单源超限、空池）。
- [ ] 零 LLM 探针：50 题金标准打分（`compute_retrieval_metrics`），看 recall/coverage
  相对现行 B1 的 Δ（预期：触发题从 2 题上升，recall 不掉）。
- [ ] 端到端 Judge（需配额）：50 题双臂 + 配对 Wilcoxon；只看 final，不看检索层自嗨。
