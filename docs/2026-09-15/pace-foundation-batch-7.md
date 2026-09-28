# PACE 基础批次（七）：条件配对题集 —— 让 B1 显式过滤"可见"

日期：2026-09-15。范围：续批次六。落地主文档 **§8.1 条件配对题集（15 组变体）**：
补齐此前诚实缺口——冻结 B0 评测只有 6 个上下文被 B1 剔除（弱信号），原因正是
题集不具条件判别性。本批构造 15 组 GA 条件变体，在确定性检索管道
（BM25 + LightRAG 投影图 → RRF top-16 → 三值适用性 → B1 剔 Inapplicable）上
演示过滤的可见 Δ。

## 1. 数据资产：`benchmark/qa/dataset/condition_pairs.json`

- 从 `sample_questions.json` 选 15 个基底问题（gold 全部落在证据真值层语料内），
  各派生 **2 个变体**（30 变体总）：
  - `matched`：孕周子句与基底自然检查时点一致（11–14 周或 18–24 周）→ B1 几乎不剔；
  - `mismatched`：孕周子句远移第三孕周（32–36 周）→ B1 应剔大量明确不适用片段；
- 变体只改**查询条件子句**，核心题面与基底共享；gold_answer / gold_sources /
  must_have_statements / gold_entities / gold_relations 从基底**逐字复制**，
  不新造临床内容；
- 每个变体带 `variant_group` / `variant_role` / `window_label` / `condition_note`
  元数据（`Question.from_dict` 忽略多余键）。
- 生成器 `benchmark/qa/build_condition_pairs.py`（确定性）+ 构建期自检：
  15 组×2、每个变体 `parse_query_conditions` 抽出孕周 == 声明的 window_label、
  gold_sources 全在语料 source_ids 内。

**轴选择（设计实证）**：原型扫了 GA / 人群 / 技术三轴。关键发现——
- **GA 轴可靠触发**：远窗错配（首↔三）无交集 → Inapplicable；近窗错配（首↔中）
  部分重叠 → Unknown。故 all 15 组统一"matched 原位窗 vs mismatched 第三孕周窗"；
- **人群/技术轴近乎不触发**：four-chamber 单/双胎、3VV 一/三孕周等检索集多为
  未标注条件 → Unknown（永不丢弃）。这是框架"Unknown 永不丢"的诚实体现：
  B1 过滤的可见强度由**条件标注覆盖率**驱动，而非过滤本身失效。
  全 GA 轴是让 Δ 可靠可见的务实选择；人群/技术轴留待语料标注补齐。

## 2. 探针：`benchmark/report/b1_condition_pairs.py`（零 LLM）

复用 b1_retrieval_ablation 口径（`classify_text`、`supported_statements`、
`load_scoring_options` hybrid/equivalence、`compute_retrieval_metrics`、K=16），
B0 = RRF 合并全集，B1 = 剔 Inapplicable 后的保留集。运行时再断言数据集自检。
结果 `benchmark/results/corpus-condition-20260915/b1_condition_pairs.json`：

- **matched**：平均剔 2.4 个（15 组共 36）；**mismatched**：平均剔 **5.53** 个
  （15 组共 **83**，≈2.3×）。**13/15 组** mismatched 剔除多于 matched（对比触发）。
- 与冻结 B0（50 题只剔 6 个）对照：条件判别题集让 B1 过滤强度提升一个量级，
  机制从"几乎看不见"到"清晰可见"。
- **检索指标代价（如实）**：mismatched 上 B1 使 precision 0.775→0.741、recall
  1.0→0.933、coverage 0.953→0.907——因为 gold 跨配对共享，被剔的 Inapplicable
  片段中有一部分携带了 gold 陈述（极端例 CP-09b：drop=10，R1=0.0，C1=0.25）。
  这是已知权衡：**B1 的收益在生成端**（不引用不适用证据），须 judge 评测（需
  token，出范围）才能闭环；检索层只演示候选集如何被条件过滤改变。

## 3. 门禁（最后一次代码编辑后的新鲜运行）

`bash benchmark/report/oldcoder_gauntlet.sh` → **6/6 ALL LAYERS PASS（EXIT=0）**：
- 全量非 baseline 套件通过（**409 例**，其中 `tests/test_prenatal_*.py` 子集 308 例；无新增测试文件——数据集校验内置在
  build/probe 的真实执行层）；ruff 0 警（新增 2 脚本入列）；pyright 0 错 0 警；
- 覆盖 6 段 100%（条件 298 / rrf 21 / 证据 61 / graph 99 / bridge 46 / pipeline 45）；
- 变异 21/21 击杀；真实执行新增 `build_condition_pairs.py` + `b1_condition_pairs.py`
  两段（step 6/6），数据集可端到端重建复跑。

## 4. 对应的 §5.1 / §8 位置与下一步

- §8.1 条件配对题集落地（15 组 GA 变体，可复现重建）。
- §5.1 确定性可复现子集：条件解析 → 并行召回(BM25+图) → RRF → 三值适用性 →
  证据集合选择，现已在条件判别题集上有可量化的 B1 检索层行为。
- 下一步候选：B1 满量真实运行 `--judge-mode required`（需 token，闭环生成端
  收益）；embedding 第三通道；人群/技术轴配对题（待语料条件标注补覆盖）；
  SUPERSEDES 条款级试点；§5.1 reranker/原子陈述生成/核验。

## 5. EVIDENCE 要素（old-coder）

- **SPEC**：批次 7 计划（条件配对题集让 B1 Δ 可见），沿续跑模式批准执行。
- **层**：pytest(337) / ruff(0 警) / pyright(0 错) / coverage(fail-under=100 ×6) /
  mutation(21/21) / real execution(5 探针含 build+probe) —— 单入口
  `benchmark/report/oldcoder_gauntlet.sh` 复跑。
- **工具**：Python 3.12.3、pytest 9.1.1、coverage 7.16.1、hypothesis 6.168.0、
  ruff 0.15.17、pyright 1.1.410。
- **源状态**：git HEAD `ac6003b`；改动未提交（沿用历批次约定），关键文件：
  `benchmark/qa/build_condition_pairs.py`、`benchmark/qa/dataset/condition_pairs.json`、
  `benchmark/report/b1_condition_pairs.py`、
  `benchmark/results/corpus-condition-20260915/b1_condition_pairs.json`、
  `benchmark/report/oldcoder_gauntlet.sh`、本文档。
- **已知局限**：配对题集 gold 跨变体共享，检索层 B1 指标含"过滤剔掉 gold 片段"
  的代价（如实报告）；生成端收益未评测；全 GA 轴，人群/技术轴标注覆盖不足时
  Unknown 吸收过滤；B0 冻结结果与 B1 对比结论不受本批影响。
