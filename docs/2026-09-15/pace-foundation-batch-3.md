# PACE 基础批次（三）：查询条件解析 + B1 检索层消融

日期：2026-09-15。范围：续批次二。在 `prenatal_rag` 补齐"任务/查询适用条件解析"
（§5.1 第 1 步的确定性首版），给出可复用的 B1 三值过滤（`classify_text`），并对
**冻结的 B0 50 题结果**做**检索层消融**（零 LLM、零重索引）。未重跑检索、未调生成。

## 1. 新增/改动

- **`prenatal_rag/conditions/query.py`**：`parse_query_conditions(text)` 从题目文本推导
  `QueryConditions`。孕周**窗口 > 单点**优先级（"11+0–13+6"→窗口，否则 "at 13 weeks"→单日点）；
  人群沿用词表；技术**仅保留强约束标记**（cfDNA/NT-only/harmonic/经阴道等），
  避免把 "four-chamber view" 这类"答案主题"误判为查询条件。`describe()` 供报告。
- **`prenatal_rag/conditions/filter.py`** 新增 `classify_text(text, query)`：
  对任意长度上下文文本直接抽条件→三值分类（B1 过滤单元，无需预先建 chunk 索引）。
- 条件包导出 query/classify_text/describe。

## 2. 冻结 B0 的检索层消融（`benchmark/report/b1_retrieval_ablation.py`）

读 `pace-b0-evaluation-20260914.json` + `sample_questions.json`：每题从题干推导查询条件，
对 B0 每条检索 context 抽条件判三值，丢弃明确 Inapplicable 后，用与评测相同
`compute_retrieval_metrics` 复算 B0/B1 检索指标。结果落
`benchmark/results/corpus-condition-20260915/b1_retrieval_ablation_b0frozen.json`。

| 口径 | precision@16 | recall@16 | coverage@16 | miss@16 |
|---|---|---|---|---|
| B0（全部 50 题） | 0.7887 | 0.96 | 0.9413 | 0.0 |
| B1（过滤后，全部 50 题） | 0.7901 | 0.96 | 0.9413 | 0.0 |

- **机制生效**：B1 在具备 GA 条件的 5 题上共丢弃 **3 条不适用上下文**（PU-L2-028 丢 2、
  PU-L2-032 丢 1），但召回/覆盖不变——金标准来源已被适用 chunk 覆盖，丢弃的是
  多余的错误孕周上下文。
- **诚实的主要发现：当前 50 题不具备条件区分度**——仅 **5/50** 题干含可解析 GA，
  **0** 题含人群/技术条件。因此冻结 B0 消融在指标层几乎不产生 Δ。
  这正是文档早前论断（"召回饱和、区分度在条件处理"）的数据面证据，也说明
  类别较多在第 8 章条件配对题集（15 组变体）。

## 3. 条件对机制演示（15 组变体 Group 1：delivery 时机）

用真实指南措辞构三条"语义相似但孕周不同"的分娩时机证据，逐查询验证 B1 只保留适用窗口：

| 查询 GA | 26+0–28+6 / 29+0–31+6 / ≥34 / 18–24 周 | 判定 |
|---|---|---|
| 20 周 | 前三条 DROP、18–24 KEEP | 全对 |
| 30 周 | 29+0–31+6 KEEP、其余 DROP | 全对 |
| 36 周 | ≥34 KEEP、其余 DROP | 全对 |

即：B0 会把这些关于 W 分娩时程的语义相近 chunk 一并视为相关，B1 丢弃孕周不符者——
正是 §8.3"减少不适用证据导致的错误"的机制本身。

## 4. old-coder 门禁（新查询代码并入既有 gauntlet）

`bash benchmark/report/oldcoder_gauntlet.sh` 全绿（含本批新增 query.py）：
- 非 baseline 套件通过；ruff 通过；pyright 0 错 0 警；
- 条件包（schema/extract/filter/query/__init__）**覆盖 100%（270/270）**，`--fail-under=100` 门通过；
- **手动变异 7/7 击杀**（新增 2 个：查询窗口/单点优先级颠倒、技术约束筛选失效，均被单测击杀）；
- 实跑：条件索引 + B1 消融均通过。

## 6. prenatal_rag_client：B1 端到端受控生成评估（可选零 token 验证）

在 `benchmark/baseline/prenatal_rag_client/` 落成一个协议化受控生成评估入口，把 B1
的"检索 → 条件过滤 → 重生成 → 评分"端到端跑通：

- **复用冻结的 B0 检索上下文**（同检索、显式过滤），不重跑索引/嵌入；
- 每题生成两个臂：**b0_ctrl**（不过滤）与 **b1**（丢弃 Inapplicable 后），
  仅"是否过滤"不同，隔离条件处理对生成的效应；
- **生成器可注入**：测试/stub（`--dry-run`，零 token）用确定性 stub，真实运行
  复用 LightRAG 默认补全（读 benchmark/.env）；
- 每个臂用 `score_question` 独立评分，Judge 可选（`--judge-mode`）。

组件：`prompting.py`（确定性提示词）、`generator.py`（异步受控生成，llm_func 可注入）、
`b1_filter.py`（三值过滤上下文）、`evaluate.py`（双臂评分核心）、`benchmark.py`（CLI）。

**dry-run 验证（50 题真实 B0 冻结上下文，stub 生成器）**：
```
questions: 50 | split-gen: 2 | dropped: 3
  b0_ctrl final=0.5034 R=0.96 P=0.7887 C=0.9413 F=0.0
  b1      final=0.5035 R=0.96 P=0.7901 C=0.9413 F=0.0
  drop: PU-L2-028 (GA 77:98) drop=2 answers_differ=True
  drop: PU-L2-032 (GA 77:98) drop=1 answers_differ=True
```
50/50 题目上下文均成功匹配；仅 2 题发生过滤丢弃（与批次三消融一致），分臂生成生效
（answers_differ=True）；检索层 R/P/C 与冻结 B0 消融完全一致。F=0 因 stub 答案是
确定性噪声（非真实生成），属预期。

**真实满量运行**（需 API token）：
```bash
PYTHONPATH=. .venv/bin/python -m benchmark.baseline.prenatal_rag_client.benchmark \
  --judge-mode required    # 可加 --limit N / --question-ids 限缩
```
stub 之外的 `generate_with_context`/`a_generate` 默认走真实补全。

## 7. 下一步

- 查询条件解析是确定性首版；临床语义消歧（绒毛膜性子类型、随访间隔 vs 孕周窗口、
  更复杂的技术意图）按主文档留给经校准的小模型。
- §6 `prenatal_rag_client` 离线管道已建成并被 dry-run 验证（零 token）；剩余的是
  **真实满量运行**（`--judge-mode required`，50 题，需 API token），才能拿到
  有内容的生成层 Δ。
- 待落地：① B1 端到端满量运行（真实生成+Judge），② 用 15 组变体建条件配对题集
  （补条件区分度，才能让 B1 检索/生成 Δ 对多数题目可见），③ SUPERSEDES 条款级试点
  （MRI 2017→2023）。