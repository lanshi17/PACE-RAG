# PACE 基础批次（六）：LightRAG 投影图通道接入 RRF（§5.1 并行召回双通道）

日期：2026-09-15。范围：续批次五。落地主文档 **§5.1 第 2 步"并行召回
(BM25/embedding/图) → RRF 合并"**的图通道：把 LightRAG B0 索引当作**真值层的
可重建投影**，离线解析成确定性 chunk 邻接图，经"文本重叠桥"映射回真值层锚点
空间，与 BM25 锚点排名用现有 RRF 合并。embedding 通道（需查询嵌入模型、
非确定性）明确出范围，记为后续工作。

## 1. 新增 `prenatal_rag/retrieval/` 三模块

- **`graph.py` — `LightRagChunkGraph`**（投影图通道）：
  - `from_index_dir` 离线解析 `kv_store_text_chunks.json` /
    `kv_store_entity_chunks.json` / `kv_store_relation_chunks.json`；缺文件 /
    非对象 / 非法记录均抛带路径 `ValueError`；
  - 无向加权邻接：每张 incidence 表（entity / relation）内对 chunk 列表去重后
    两两成对 +1，边权 = 共同出现表数；**构造期对称化**，保证从任一端都能扩展；
  - `expand(seed_keys, *, hops=2, k=20, include_seeds=False)`：加权 BFS，
    排名键 = 距离升序 → 同距边权降序 → chunk 键升序；种子默认排除
    （种子由词法通道给出，避免 RRF 重复计分）；`k<=0` 返回空；
  - `source_for` / `texts` / `chunk_count`。
- **`bridge.py` — `OverlapBridge`**（投影 → 真值层锚点桥）：
  - `build(chunk_texts, store, *, min_jaccard=0.0, tokenizer=tokenize)`：剥离
    `SOURCE_ID:/ORIGINAL_FILE:` 投影头后，与全部真值层 chunk 算 token 集合
    Jaccard，取最大重叠锚点（平分取更小 anchor_id，确定性）；低于阈值不建映射；
  - 双向映射 `chunk_to_anchor` / `anchor_to_chunks` + 保真度元数据
    `jaccard_for`（每个映射的最佳重叠 Jaccard，供探针如实上报保真度）。
- **`pipeline.py` — 编排**：
  - `GraphChannel(graph, bridge, hops=2, k_expand=20).rank(seed_anchors, *, k)`：
    种子锚点 → 投影键 → 图扩展 → 回映锚点（去重保首个、跳过 None、k 截断）；
  - `condition_seed_anchors(store, query)`：复用三值分类，取"非明确不适用"的
    锚点作图种子（Unknown 保留语义在此同样成立）；
  - `parallel_recall(bm25, graph, *, k)`：RRF 合并两路排名并截断。
- `retrieval/__init__.py` 追加导出；`pre/report` 探针见 §4。

## 2. 测试与门禁（最后一次代码编辑后的新鲜运行）

`tests/test_prenatal_graph.py` / `test_prenatal_bridge.py` / `test_prenatal_pipeline.py`
共 **46 例** + hypothesis 属性（图扩展确定性/子集/无重复；桥双向映射自洽）。
覆盖错误分支：索引缺文件/非对象/非法记录、`k<=0`/`hops=0`、空图/孤立种子、
无重叠→None、阈值边界（恰等于 0.5 的 `>=` vs `>`）、去重、None 跳过。

`bash benchmark/report/oldcoder_gauntlet.sh` → **6/6 ALL LAYERS PASS（EXIT=0）**：
- 全量非 baseline 套件 **409 例通过**（其中 `tests/test_prenatal_*.py` 子集 308 例）；ruff 0 警；pyright 0 错 0 警；
- 覆盖 **6 段均 100%**（`--fail-under=100`）：条件 298/298、rrf 21/21、
  证据 61/61、**graph 99/99、bridge 46/46、pipeline 45/45**；
- **手动变异 21/21 击杀**（条件 7 + RRF 3 + 证据 3 + 图/桥/管道 **8**）；
- 真实探针：condition_extract / b1_retrieval_ablation / **graph_channel_probe** 全部可跑。

新增变异（8，各绑定 kill 测试，fail-closed 片段须恰好出现一次）：
GRAPH1 incidence 不去重（建不出边）/ GRAPH2 距离主序反转 / GRAPH3 种子默认泄漏；
BRIDGE1 取首个而非最大重叠 / BRIDGE2 阈值含等号改严格大于；
PIPE1 RRF 丢图通道 / PIPE2 锚点不去重 / PIPE3 条件种子计入 Inapplicable。
（登记时发现 GRAPH1、BRIDGE2 的变异片段缩进与源码不符，已修正为 4/12 空格，
否则 fail-closed 会误判"出现次数 != 1"。）

## 3. 真实 B0 探针（`benchmark/report/graph_channel_probe.py`，零 LLM）

在冻结 B0 投影索引 + 真值层 SQLite 上运行，结果见
`benchmark/results/corpus-condition-20260915/graph_channel_probe.json`：

- **桥接保真度**：468/468 投影 chunk 全部映射到锚点（1.0）；最佳重叠 Jaccard
  均值 **0.6077**、中位 **0.585**、min/max 见 JSON。即：LightRAG 切分与真值层
  切分不同，桥是**最大重叠近似**而非精确对应——保真度如实上报。
- **逐题（50 题）**：BM25 top-16 与图通道（种子 top-8、hop=2）RRF 合并 k=16：
  - 图通道平均产出 18.9 个锚点排名；合并后平均 **6.42 个新锚点**挤进 top-16
    （50/50 题 marginal>0）；
  - **source 覆盖：merged(0.6607) < BM25-only(0.7019)**——k=16 预算下并入图
    候选挤掉了部分 B0 冻结结果覆盖的来源。这是诚实发现：**图通道机制有效，
    但在此预算下并不自动提升对 B0 来源的覆盖**，也**不改变 B0/B1 对比结论**。
  - 条件承载子集（5 题）同向（marginal 6.8、覆盖 0.538 vs 0.597）。

## 4. 对应的 §5.1 流程位置

确定性可复现子集再进一档：**查询条件解析 → 并行召回(BM25 + LightRAG 投影图)
→ RRF 合并 → 三值适用性 → 证据集合选择（角色+适用性分桶、预算封顶）**。
仍缺：embedding 通道、领域 reranker、原子陈述生成/核验、补充检索、SUPERSEDES。

## 5. EVIDENCE 要素（old-coder）

- **SPEC**：批次计划经两次 exit_plan_mode 批准（2026-09-15），含验收命令与
  honest-limits；本批次按计划执行。
- **层**：pytest(337) / ruff(0 警) / pyright(0 错) / coverage(fail-under=100 ×6)
  / mutation(21/21) / real execution(3 探针) —— 命令均持久化在
  `benchmark/report/oldcoder_gauntlet.sh`，可单入口复跑。
- **工具版本**：Python 3.12.3、pytest 9.1.1、coverage 7.16.1、hypothesis 6.168.0、
  ruff 0.15.17、pyright 1.1.410。
- **源状态**：git HEAD `ac6003b`；批次改动未提交（沿用历批次约定），关键文件：
  `prenatal_rag/retrieval/{graph,bridge,pipeline}.py`、`__init__.py`、
  `tests/test_prenatal_{graph,bridge,pipeline}.py`、
  `benchmark/report/{manual_mutation_prenatal.py,oldcoder_gauntlet.sh,graph_channel_probe.py}`、
  `.gitignore`、本文档。
- **已知局限**：图通道种子来自 BM25（LightRAG local-mode 等价物），非独立第三
  通道；embedding 通道未接；桥为近似，保真度已如实上报；本批不断言 B1 Δ 收益。

## 6. 下一步候选
- embedding 通道接入 RRF（真正的第三独立通道，需查询嵌入模型）；
- 条件配对题集（15 组变体）让 B1 检索/生成 Δ 可见；B1 满量真实运行（需 token）；
- SUPERSEDES 条款级试点（MRI 2017→2023）；§5.1 reranker/原子陈述生成/核验/补充检索。
