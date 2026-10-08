# 后续优化计划（2026-10-08，由统一受控首批结果推出）

> 现状：LightRAG vs KAG 统一受控 p=0.658 无法区分；KAG 26/26、LR 24/26、PathRAG 2/26 卡死、HippoRAG/GraphRAG 未建。
> 排序原则：收尾 > 零训练成本的取舍优化 > 稳定复现的失败 > 新实验；堆通道/微调暂缓。

## P0 收尾（阻塞一切）

### 1. HippoRAG + GraphRAG 串行建库 → 五框架终局
- 低并发串行（KAG 已验证 11s/chunk 链路；LightRAG 用 `MAX_ASYNC_LLM=1`，KAG 用 `--num-chains 1`，PathRAG 用 `--max-async 2`——新框架沿用同级并发）。
- GraphRAG 注意 `GRAPHRAG_API_KEY` 别名（`run_unified62.sh` 已处理）与 settings.yaml 模板。
- 完成后跑 `gate` + `summarize_unified62.py` 出终局 Friedman + Holm（10 对）+ bootstrap，替换 README 表 2。
- 验收：`benchmark/results/unified62/*/evaluation.json` 5 份齐 + 门禁通过。

### 2. 口径补丁：Judge 调用失败 = 单元失败
- `summarize_unified62.py::_per_question` 当前只认 `error`/None final；PU-L1-008（Judge `InternalServerError`，`judge.*` 全 0，`scoring_method=lexical` 回退，`error=None`）被算成成功。
- 改法：`scoring.judge.error` 非空 → `failed=True`；重跑 `summary.json`；sens 分析中剔除该单元。
- 验收：`n_failed` 如实报告，主结论复核不变（预期）。

### 3. LightRAG 补 2 文档 → 26/26
- 目标：`ISPD-nipt-2023`、`ISUOG-midtrimester-2022`（chunk-000 网关断连失败）。
- 网关稳定后 `retry-failed`（telemetry 上下文 bug 已修）；若仍失败，用单 chunk 探针定位后逐个补。
- 验收：`kv_store_doc_status.json` 26 processed；27 道 gold 相关题不再需要敏感性分析。

## P1 有证据支撑的优化

### 4. B1 过滤前置 + 去冗余（零训练成本，优先）
- 现状问题：B1 在检索后过滤，50 题仅 2 题触发，上下文没换过（批次十二）。
- 改法：适用性门控移到 BM25/图/向量三路排序之前，同池竞争；同一来源多片段去冗余（预算让给互补角色）。
- 对照：同 50 题、B0 冻结上下文、只换"过滤位置+去冗余"一个变量；指标看 final + faithfulness/completeness 是否回升（batch12 的回退是否修复）。
- 验收：端到端配对 Δ，非检索层自嗨。

### 5. 安全专项
- KAG PU-L4-002 三次稳定违规：裸 `<reference id>` 标签 + 安抚措辞 → 生成约束（引用标签白名单/后检正则）+ 后检拦截。
- Judge rationale 审计：LR PRE005（safety 0.5 vs KAG 1.0，两答案都正确）——判分器措辞敏感度审计，必要时修 Judge prompt。
- L4 安全集扩充：6 道草案待专家审核；安全题从 3 道扩到 9 道后再谈"修复有效"。
- 验收：PU-L4-002 在新约束下 safety=1.0；判分器审计结论文档化。

### 6. 跨框架候选合并探针（新实验，先探针后全量）
- 假设：单框架 recall 已天花板（0.94+），互补在框架间（配对表 R 列：PU-L2-023/022 KAG=1/LR=0；PRE012 反向）。
- 探针：LR ∪ KAG 候选 → RRF → 同一生成器（`build_generation_messages`），离线零 LLM 先算 recall/coverage Δ；有 Δ 才跑 50 题端到端 Judge。
- 红线（batch12 教训）：只汇报检索层改善 = 错误产品结论；必须端到端 final 说话。
- 验收：探针报告（含"做/不做全量"决策）。

## P2 暂缓（本期不做）
- 继续堆通道（final +0.0011，不要）。
- embedding/reranker 微调：瓶颈在取舍不在召回，等任务 4 证伪后再议；6×3090 不先烧。
- PathRAG chunk 级容错改造：等网关稳定先重跑，不行再改 vendored 调用链。
- 旧缓存移植：已证伪两次，不再试。

## 任务-todo 映射
1→HippoRAG/GraphRAG建库；2→口径补丁；3→LR补文档；4→B1前置；5→安全专项；6→跨框架探针。
