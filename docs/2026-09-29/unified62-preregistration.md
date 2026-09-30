# 五框架 62 题统一受控实验：预注册方案（v1.0，2026-09-29）

> 状态：设计冻结，执行前登记。任何偏离必须记入 §9 偏离日志，不得事后改口径。

## 0. 背景：历史 62 题合并为什么不是受控实验

`benchmark/report/framework-comparison-62-20260912.md` 的 62 题表是**已保存结果的
描述性合并**，五个混杂源：

| # | 混杂源 | 证据 |
|---|---|---|
| C1 | 索引语料不一致 | GraphRAG/LightRAG/PathRAG/KAG/HippoRAG 现有索引均建在旧 32 文档语料上（含 3 份陈旧残留 + 已去重的重复版本）；当前统一语料是去重后 26 文件。KAG 索引态 32 文档 vs 当前 ok 26，8 个 id 在新语料无对应 |
| C2 | 索引期模型只部分可考 | 仅 KAG（`kag_index_state.json`：`gpt-5-mini` + `text-embedding-3-large`/3072）与 HippoRAG（`index_manifest.json`：同上 + OpenIE `temperature: 0`）有机器可读记录；LightRAG/PathRAG/GraphRAG 索引期模型无结构化记录 |
| C3 | 判分入口不一致 | 50 题部分是 `rescore` 产物（LightRAG/GraphRAG/KAG 为 `-rescored.json`），PathRAG 为 `judge_mode=required` 直出，HippoRAG 为手工合并（`-merged.json`，PRE008 Judge 解析失败只计 61 题） |
| C4 | 12 新增题未定稿 | `preclinical_challenge_draft.json` 12 题全部 `adjudicated=False`、双 `pending` 标注；gold_sources 为候选来源占位（"Candidate source only…"），实体关系标注不完备；50 题中 49 题同样 `adjudicated=False`（仅 1 题 True），但有 kappa=1.0 的双 MD 标注，成熟度不对等 |
| C5 | 检索方法各异 | adaptive（GraphRAG 按 arch 切 drift/local/basic；LightRAG 切 hybrid→local/basic；KAG 切 solver/naive）vs PathRAG 全 hybrid vs HippoRAG 单链路——这是**待比较的处理变量**，不是混杂；但必须在同题配对下比较（§3），不能用边际均值排名 |

结论：历史表只能做"量级参考"，任何"框架 A > 框架 B"的断言都必须等本实验。

## 1. 实验单元与区组设计

- **实验单元**：`(question, framework)`。62 题 × 5 框架 = 310 个单元。
- **区组**：以 `question_id` 为区组（repeated-measures / randomized block 设计）：
  同一题的 5 个框架答案在**同一语料、同一判分条件下**配对比较。框架效应估计只用
  区组内差值，不用跨题边际均值。
- **分层（报告用，非随机化用）**：难度 L1/L2/L3/L4 × 题类
  （safety / cross_guideline / 其余）× 检索 archetype（basic / multi-vector /
  graph-enhanced）。12 新增题全落在 L4-basic-safety（6）与 L3-graph-enhanced-cross_guideline（6）
  格子里——这两个格子的结论必须标注"草案题、未定稿"。
- **运行顺序随机化**：62 题在各框架 `evaluate` 内的执行顺序用固定种子打乱
  （`seed=42`），防 API 限流/超时重试与题目难度顺_X序混杂。同一打乱顺序用于全部 5 框架
  （区组内顺序一致，跨框架可比）。
- **重复**：生成单次（LLM 调用成本约束），Judge 单次；不确定性用**按题聚类的
  bootstrap CI**（§6）而非重复运行估计。

## 2. 冻结的统一条件（5 框架 × 62 题全部相同）

| 控制项 | 冻结值 | 说明 |
|---|---|---|
| 语料 | 当前 `benchmark/data/corpus/input/` 26 文件 + `corpus_manifest.json`（ok 26） | 全部 5 框架**重建索引**，新 namespace/目录，历史产物只读保留 |
| 数据集 | 新文件 `benchmark/qa/dataset/unified_62.json`（50 + 12 合并，id 无碰撞已验证）+ 其 sha256 | 不改动 `sample_questions.json`（fingerprint 保护历史 rescore） |
| 生成模型 | `gpt-5-mini` | 以 `benchmark_conditions.completion_model` 落盘值为准 |
| 向量模型 | `text-embedding-3-large`（3072 维） | 同上 `embedding_model` |
| Judge | `gpt-5`，`judge_mode=required` | required：Judge 失败即该单元判失败，不混入词面回退分（HippoRAG PRE008 事件不再重演）；Judge temperature 按 `benchmark/qa/judge.py` 现行逻辑（gpt-5 不设 temperature） |
| 行为判定 | `judge_safety`（gpt-5）逐题，`safety_verdict` 随行持久化 | 与现行口径一致 |
| top-k | 16 | `benchmark_conditions.top_k` |
| 来源校验 | `hybrid` + 同一 `scoring_config.yaml`（落盘 `scoring_config_sha256`） | 同一配置文件 sha |
| 安全惩罚 | 只在逐题层应用一次（2026-09-08 起口径） | dataset 层不二次折半 |
| 检索方法 | 各框架 `adaptive`（PathRAG 自适应义即 hybrid；HippoRAG 单链路） | 方法差异是处理变量，`requested_search_method` + `actual_search_methods` 落盘备查 |
| 种子 | 题序打乱 `seed=42`；Judge/生成不设 seed（API 侧 temperature 行为按各客户端现行默认） | seed 只管可复现的题序 |

`benchmark_conditions`（`benchmark/common/benchmark_protocol.py`）是**门禁**：
汇总前用 `assert_comparable_conditions` 对 5 份产物两两校验，
`dataset_sha256 / corpus_fingerprint / scoring_config_sha256 / judge_model /
completion_model / embedding_model / top_k / judge_mode` 任一不一致即拒收。

## 3. 待比较的处理变量（唯一允许不同的）

各框架的索引与检索链路本身：GraphRAG（drift/local/basic 按 arch）、
LightRAG（hybrid→local/basic）、PathRAG（hybrid）、KAG（solver/naive）、
HippoRAG（事实检索→PageRank + 临床引用 prompt）。生成 prompt 保持各框架现行
（HippoRAG 的临床引用 prompt 是其链路的一部分，不统一）。

## 4. 数据集说明：`unified_62.json`

- 构成：`sample_questions.json` 50 题（原样）+ `preclinical_challenge_draft.json`
  12 题（原样，`adjudicated=False` 保留）；合并文件 sha256 `cd025c64…2204f50`。
- 已知局限：12 题 gold_sources 为候选占位、实体关系不完备、
  标注 pending → 12 题的 retrieval/generation 分数**只作描述性报告**，不进入
  "框架排序"推断；排序推断只用 50 题成熟子集。62 题全集用于"量级总览"。
- 若执行前 12 题获得专家定稿，允许升级为 v1.1（定稿 sha 变更即新版本），
  本文件 §9 登记。

## 5. 执行计划

```
阶段 A（建库，每框架独立目录/namespace，历史产物不动）：
  GraphRAG  → benchmark/data/microsoft_graphrag_unified62/   (~2h, ~1400 请求)
  LightRAG  → benchmark/data/light_rag_unified62/            (~1h)
  PathRAG   → benchmark/data/path_rag_unified62/             (~1h)
  KAG       → benchmark/data/kag_unified62/                  (~1h)
  HippoRAG  → benchmark/data/hipporag_unified62/             (~1.5h)
阶段 B（评测，题序 seed=42 打乱，judge_mode=required）：
  benchmark/results/unified62/{graphrag,lightrag,pathrag,kag,hipporag}/
    evaluation-YYYYMMDD.json + .jsonl（逐题增量落盘，含答案全文 + contexts +
    retrieval/generation/safety 分数 + safety_verdict + usage）
阶段 C（汇总）：benchmark/results/unified62/summary.json（门禁校验记录 + §6 统计）
```

- 每框架产物必须含 `benchmark_conditions`（现有 5 客户端 `evaluate` 已写，
  由 `build_benchmark_conditions` 生成）。
- 中断续跑：各客户端现行增量落盘/缓存机制；`--no-cache` 重建只在索引污染时用，
  用了即登记。
- 成本上限：单框架 evaluate 约 62 生成 + 62 Judge + 行为复核；GraphRAG index
  约 1400 请求。若某框架失败率 > 10%，停线排查，不拿失败偏集做结论。
- 阶段 A 串行：共享网关限流下多框架并行建库互相挤占（实测三并行即大面积
  `Retrying request` + `APIConnectionError` 失败），同一时刻只跑一个框架的
  `index`；顺序：LightRAG → KAG → PathRAG → HippoRAG → GraphRAG。

## 6. 分析计划（先登记）

- **主分析**：50 题成熟子集，`final_score` 区组内配对比较。Friedman 检验
  （5 相关组）→ 若显著，Holm 校正的配对 Wilcoxon（10 对比较）+ 配对中位数差
  与按题 bootstrap 95% CI。效应量：Kendall's W + 配对 rank-biserial。
- **次分析**：retrieval（recall/coverage）与 generation（faithfulness/
  completeness/correctness）分层报告：按 L1–L4、按 arch 类型、按 safety/
  cross_guideline 格子；12 题只报告描述性均值 + 独立行为复核表，不做推断。
- **敏感性**：62 全集重跑主分析（看 12 草案题是否翻转排序）；lexical vs Judge
  口径对照；缺源题（PU-L4-001~003、PU-L3-024/027）剔除后重算（语料锁定的 recall
  上限是已知天花板）。
- **失败处理**：Judge 失败单元记失败（required 语义），失败率按框架报告；
  不做插补；若某题某框架失败，该题配对比较中剔除该题（listwise within-pair），
  剔除数报告。
- **解释禁区**：不声称临床可用（50 题仅 3 安全 + 1 跨指南；12 题未定稿）；
  不跨口径比较历史产物（历史表在 README 中保留"描述性"标签）。

## 7. 已知局限（执行前承认）

1. 12/62 题未定稿（§4）：排序推断只用 50 题。
2. 生成单次运行：框架差的 CI 来自按题 bootstrap，不是运行重复；若主分析 CI
   宽到无法区分，结论就是"无法区分"，不加跑 cherry-pick。
3. 语料缺 3 源（FDA-ultrasound-imaging、PMC-3410507、PubMed-24258515）：
   相关 5 题 recall 上限被锁，敏感性分析覆盖。
4. 索引期 LLM 参与建库（实体抽取等）：重建统一了模型但"索引内容"仍是各框架
   链路的一部分——这正是处理变量，不视为污染；但报告必须写明各框架索引用模型。
5. Judge 即 LLM-as-Judge：与专家复核不等价；L3/L4 仍需专家复核（沿用现行声明）。

## 8. 验收标准

- [ ] 5 份产物 `benchmark_conditions` 门禁两两通过（§2 表格字段）。
- [ ] 5 × 62 = 310 单元，答案全文 + contexts + verdict 落盘可审计。
- [ ] `summary.json` 含 Friedman + Holm 配对结果 + bootstrap CI + 失败率。
- [ ] 报告含 §6 全部次分析与敏感性；README 表 2 替换为受控结果（历史表移入附录并标注）。
- [ ] §9 偏离日志无未登记项。

## 9. 偏离日志

| 2026-09-29 | LightRAG 统一索引首轮 60 min 超时中断（26 文档 0 完成），不断点续跑（`index` 默认 `cache=True` 复用 LLM 缓存） | 实体抽取 LLM 往返慢（chunk 级逐 extract） | 产物内容不变（同语料同模型幂等续建）；§5 "~1h" 按实际更新 |
| 2026-09-29 | 共享网关 `linxi.chat` 疑似限流/抖动：三框架并行建库时大面积 `Retrying request` + `APIConnectionError`，单跑仍持续失败；裸探针（`gpt-5-mini` ping，经 `benchmark/.env`）成功，网关本身可达 | 网关侧限流或长连接不稳，非 credentials 问题 | 阶段 A 改串行（§5 已补规则）；KAG/PathRAG 已暂停，LightRAG 续跑观察；若持续失败则改夜间窗口重跑 |
| 2026-09-29 | 确认网关侧限流：无 key 裸探 `/v1/models` 连续 5 次 401 后第 6 次返回 **429 Too Many Requests**（即使无 key 请求也被计数限流）；3 分钟窗口内 LightRAG 状态零前进（failed 62→63 仅为失败计数）、并发已降至 1 仍 `Connection error` | 网关全局限流，我方重试风暴可能加重 | 全部 index 进程已停，进入冷却；夜间窗口用 `MAX_ASYNC_LLM=1` 串行重跑阶段 A；`run_unified62.sh` 已加 `GRAPHRAG_API_KEY` 别名 + `mkdir -p` 启动 |
| 2026-09-29 | LightRAG 统一索引存储污染：中断→续跑累积 78 条 doc_status 行，其中 52 条为 `dup-*` 重复文件名失败行（`File name already exists`，同 track 重复入队伪影），真实 26 文档 0 完成（11 failed 皆 `APIConnectionError`）→ 已 `rm -rf rag_storage` 全新重建（`--no-cache`），`MAX_ASYNC_LLM=1` 单并发；新存储 26 行干净（14 parsing / 9 analyzing / 3 processing） | 失败行不是"已索引"，续跑只会堆积 dup 行；网关恢复后干净重建最省 | 旧存储已删（仅 2.2MB 污染产物，无可用向量）；`index` 重试语义待验证——若 `retry-failed` 不能复用失败 chunk 缓存，需补进运行手册 |
| 2026-09-29 | 运行器修正：各客户端 `evaluate` 按数据集文件顺序执行、不保留 `--question-id` 传入顺序 → 题序控制改用预打乱数据集文件 `unified_62_seed42.json`（sha `33c7e0d1…`，与 `run_order_seed42.txt` 一致性已验证）；Judge 环境（`JUDGE_COMPLETION_MODEL`/`JUDGE_API_KEY`/`JUDGE_API_BASE`）均已配置 | 口径不变（同文件同顺序），`benchmark_conditions.dataset_sha256` 将记录打乱文件 sha | `run_unified62.sh` evaluate 段已重写；预注册 §1/§2 的"seed=42 打乱"实现方式以此为准 |
| 2026-09-29 | LightRAG 首轮 `index` 终态：26 文档中 24 processed / 2 failed（`ISPD-nipt-2023`、`ISUOG-midtrimester-2022`，均为 chunk-000 `APIConnectionError`）；附带修好 `retry-failed` 的 telemetry 上下文 bug（此前重试中 135 次真实 LLM 调用直接抛 `RuntimeError`，现修好并加回归测试）；旧 extract 缓存移植验证**不可复用**（gleaning prompt 含上一轮输出，新旧 key 不交叠） | 剩余 2 文档的新旧 chunk 命名都对不上旧缓存（去重前后 PDF 版本不同），只能正面重提 | 图谱已有 8723 节点 / 10583 边可用；下一步给 extract 链路加 `timeout`（`llm_model_kwargs={"timeout": …}` 经 `_rag_options` 透传，待验证），再对 2 文档单跑重试 |
| 2026-09-30 | 移植二轮验证失败，转为审计：① v1 移植（换头三行）键 miss——旧 input-text 与新 chunk 文本有 ~1% 版本差异；② 按新 chunk 文本在旧缓存中找最接近条目：ISPD 前 14 chunk ratio≥0.95 但 midtrimester 后半 chunk 低至 0.14——旧版 `8bdd` 与新版 `182ace` 不是同一切分偏移，而是有实质内容差异的版本（旧 21 chunk vs 新 22 chunk，句级 94% 正向一致但 chunk 级错位）；③ 关键审计：`vdb_chunks` 中有 1 行新 chunk-id（`ISPD-nipt-2023--…-chunk-000`）却是在 purge 后失败终态下写入的**孤儿向量行**（`__created_at__` 10:24:38 在 purge 之后），属失败终结 flush 的副产物 | 移植旧 extract 结果在证据层面不可辩护（chunk 文本不同=不同的抽取输入），放弃移植 | ** gate 决策**：LightRAG 以 24/26 processed 现状进入评测（§5 备注）；27 道 gold 引用缺失文档的题走敏感性分析（剔除重算），主结论不受单文档缺失影响；孤儿向量行 1 行（有正常 3072 维向量、file 归属正确）属失败 flush 副产物，`evaluate --limit 3` 烟囱已过（recall 1.0），不阻塞 |
