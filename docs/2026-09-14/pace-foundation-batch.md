# PACE 基础批次（一）：Judge 修复、注册表增量、证据存储与 BM25 召回

日期：2026-09-14。范围：[续记 §4](../2026-09-12/prenatal-ace-framework-followup.md) 第 1–2 周清单中的 #2（Judge 截断）、#3（B0/B1 检索底座）、#4（schema 增量）与 #5 的版本链登记部分。未启动任何基线索引重建、未运行 LLM、未训练模型。

## 1. Judge 截断修复（续记 #2）

`benchmark/qa/judge.py` 的 `JudgeConfig`：`max_context_chars` / `max_answer_chars` / `max_gold_chars` 默认从 `12000/8000/8000` 改为 `None`（不截断），显式传参仍可截断。判分现在默认使用实际生成时的完整证据包；历史 62 题结果系在截断下产出，不可与新结果直接混比。问题定位依据：增量报告中 faithfulness 0.78→0.99 的翻转开关即 `judge.py:44`。
Judge 截断效应已量化（2026-09-11 增量批 LightRAG 12 题，`light_rag_untruncated.json`）：不截断后 faithfulness 0.888→0.968（+8.1 分）、weighted_mean 0.928→0.971（+4.3 分）；逐题 12/12 不降、11/12 上升（PU-L4-PRE006：0.78→1.00），无任何题因不截断而降分——旧 Judge 确实在为未见上下文系统性惩罚。Judge 成本约 $0.28 / 589k tokens（gpt-5）。


## 2. GUIDELINE_REGISTRY 增量与版本链（续记 #4、#5 部分）

新增 8 条条目（11→19），DOI/年份逐一核实：

| 条目 | 核实来源 | 备注 |
|---|---|---|
| ISPD-nipt-2023 | 语料页首（10.1002/pd.6357） | 即更名后的 NIPT 立场声明 |
| ISPD-genome-wide-sequencing-2022 | 语料页首 DOI + PubMed 35583085 | Prenat Diagn 2022;42(6):796–803 |
| SMFM-consult-57-soft-markers-2021 | ajog.org / ScienceDirect | 10.1016/j.ajog.2021.06.016；页首 Replaces #10/#16/#17/#25/#27 已录入 note，是 SUPERSEDES 题源 |
| SMFM-cfdna-ultrasound-2017 | PubMed 28108156 原始记录 | 10.1016/j.ajog.2017.01.005；搜索 AI 摘要曾给出错误 DOI（.04.001），已按 PubMed 弃用 |
| ISUOG-fetal-mri-2017 / 2023 | 语料页首 | 已核验版本链，`superseded_by` 已接线 |
| ISUOG-basic-cardiac-screening-2006 | 语料页首（UOG 2006;27:107–113，10.1002/uog.2677） | **新发现：审计报告遗留的"2005 年份未核对"就此解决——页首印刷为 2006** |
| ISUOG-sonographic-screening-fetal-heart-2013 | 语料页首 | `superseded_by` → fetal-cardiac-screening-2023 |

`EvidenceLevel` 按续记 #4 以类文档注释标记"组织范围 × 研究设计/推荐强度"拆轴方向，枚举值未动；L1 文档串补 SMFM。

## 3. `prenatal_rag/` 包（主文档 §9 建议目录的第一批）

刻意不依赖 `benchmark.*`（manifest 格式视为稳定契约、本地解析），可独立发布。

- **`evidence_store/`**（SQLite 原型，主文档 §4 真值层）：
  - `store.py`：`SourceDocument` / `SpanAnchor`（page/chunk/span 三种锚点）/ `Chunk`；规范化文本 = 统一语料文本剥离 Wiley 下载水印行（审计 §3 遗留改进项，剥离计数入库）；页区域无缝平铺（文件头行并入页 1）；chunk 页内贪心装箱（默认 1200 字符），文本恰为规范化文本的精确切片；`locate()` 做原文精确 span 定位；文本变化时整份替换，支持撤回后重投影。
  - `ingest.py`：按 manifest 摄取 ok 文档；family_id = 页首 DOI（两键身份，续记 §2.1），缺 DOI 退化为 source_id。
  - 锚点偏移全部相对存储内规范化文本，不依赖 LightRAG chunk（续记 §1#5 的结论：span 级锚点只能由本层承担）。
- **`applicability/gestational_age.py`**（主文档 §4.2）：孕周以天存储（22+3=157，拒绝 22.3 周与 24+7）；区间开闭边界按整数天集合化简；`apply_ga_interval` 三值判断——任一侧缺失→Unknown，无交集→Inapplicable，覆盖→Applicable，**跨越边界→Unknown（不取中点）**；单日查询界外明确 Inapplicable。`parse_weeks` 把 "18 to 24 weeks" 映射为 [18+0, 24+0]，是否外推到 24+6 留给条款级抽取，不擅自决定。
- **`retrieval/bm25.py`**（主文档 §5.1 第 2 步）：无依赖、确定性的 Okapi BM25（k1=1.5、b=0.75 起步）；英文小写词 + CJK 逐字分词，查询与语料共用；只输出排名与分数，供上层 RRF 合并，不与其他通道直接相加。

## 4. 验证

- 新增 4 个测试文件 + judge 测试扩充，全量 `pytest` 通过（0 失败），`ruff check` 通过。
- 真实语料端到端冒烟（存储默认位于 `benchmark/data/evidence_store/`，已 gitignore）：26 篇入库 / 7 条 duplicate 跳过 / 341 chunks / 195 行水印剥离，3 秒完成；重复摄取幂等（unchanged 26）。
- BM25 实查抽检方向正确：`nuchal translucency 11 to 13 weeks` → 心脏筛查 2013 + 11–14w 2023；`chorionicity surveillance twin` → 双胎指南；中英混排 `DV PI 剖宫产时机` → SGA/FGR 指南（DV 异常分娩时机所在篇）。
- span 定位实查：ISPD-nipt-2023 中 "singleton pregnancies" 命中页 1/2/12，页号与偏移正确。

## 5. B0/B1 推进状态（2026-09-14 晚间更新）

LLM 环境确认可用（`RAG_*` / `JUDGE_*` 均已配置）。

1. **Judge 截断效应已量化**：见 §1（12 题重跑，faithfulness +8.1 分、12/12 不降，成本约 $0.28）。
2. **B0 索引已完成**（2026-09-15）：新 namespace `light_rag_pace_b0_20260914`，26/26 processed、0 失败；产物 468 chunks / 12,592 实体 / 16,574 关系（LightRAG 1.5.7）。索引走统一语料**原始文本**（含水印行）——证据存储的剥离文本仅用于锚定；是否剥离索引文本属解析器消融，按主文档 §8.2 另做实验。索引+排队实测约 5 小时（26 篇、max_async=4）。
3. **B0 评估已完成**：`evaluate --judge-mode required`（50 题，adaptive→basic 23/local 17/drift 10，k=16，不截断 Judge），输出 `benchmark/results/light_rag/pace-b0-evaluation-20260914.json`，详见 §6。
4. **B1 的前置是 chunk 级条件元数据**：显式 metadata/区间过滤需要每 chunk 的 GA/人群/检查条件——这正是条件 schema → 条款级抽取的桥。在 chunk 条件抽取落地前不实现退化版 B1（source 级过滤是稻草人比较）。下一步顺序：`prenatal_rag` 条件抽取（条件密度审计的 15 组变体材料直接作验收样例）→ B1 过滤器。
5. `prenatal_rag_client` 协议适配与 SUPERSEDES 条款级试点（MRI 2017→2023；SMFM #57 Replaces 列表为第二题源）随后。

运行注意：`benchmark ... index` 的 preflight 要求项目目录已存在（`build_index` 先 preflight 后建目录），新 namespace 需先 `mkdir -p`。

## 6. B0 基线结果（新 namespace，不截断 Judge 协议）

`benchmark/results/light_rag/pace-b0-evaluation-20260914.json`（raw JSONL 同名）。数据集 `sample_questions.json`（50 题，指纹 dc1b2500…）；generator gpt-5-mini，Judge gpt-5（required，50/50 成功，0 失败查询）。

| 层 | 指标 | 值 |
|---|---|---|
| 检索 | precision@16 / recall@16 | 0.789 / **0.96** |
| 检索 | coverage@16 / miss@16 | 0.941 / 0.0 |
| 生成 | faithfulness（不截断） | 0.962 |
| 生成 | relevance / completeness / correctness | 0.943 / 0.861 / 0.895 |
| 生成 | weighted_mean | 0.913 |
| 安全 | safety / hallucination | 1.0 / 0.0 |
| 来源 | exact hit / evidence-supported | 0.94 / 0.84 |
| 最终 | final_score | 0.9299 |

读数：

- **召回饱和再次确认**（recall 0.96、miss 0），区分度空间在条件处理与 completeness（0.861 为最低生成指标）——与主文档"贡献 1/2 主线在条件化"的判断一致。
- faithfulness 0.962 在不截断协议下取得；截断协议的历史读数（12 题子集 0.888）不可与之直接混比（§1）。
- exact source hit 0.94 但 evidence-supported 仅 0.84——引用来源对不等于逐陈述有原文支持，正是 SourceCheckup 式缺口，也是 PACE §4.1 span 锚点 + 逐陈述核验要压缩的差距。
- 成本：查询 1.54M tokens（gpt-5-mini）+ Judge 0.97M tokens（$1.32）；评估耗时 41 分钟（50 题）。
