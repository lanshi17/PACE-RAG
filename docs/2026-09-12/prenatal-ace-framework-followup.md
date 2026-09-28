# PACE-LightRAG 探索续记：语料核验、命名与先例

日期：2026-09-12。本文是 [prenatal-ace-framework.md](./prenatal-ace-framework.md) 的同日续记，全部工作为只读核验（manifest、抽取文本页首、数据集与代码定位）加联网检索；未修改运行代码、未重建索引、未启动训练。仓库断言核验由本会话直接完成；LightRAG vendored 代码与外部先例由两个只读探查任务完成，外部条目均对照原文摘要或页面，未能核验的条目单独标出。所有 `lightrag` 行号锚点位于 `benchmark/baseline/libs/light_rag/`。

## 1. 主文档 §3 断言逐条核验

| # | 主文档断言 | 结果 | 证据 |
|---|---|---|---|
| 1 | client 支持 embedding/LLM/reranker 注入与 `aquery_data` | 确认 | `benchmark/baseline/light_rag_client/client.py:94-100`（`llm_model_func`/`embedding_func`/`rag_options` 的 `rerank_model_func`→`enable_rerank`）、`client.py:467-470`（`aquery_data`/`aquery_llm`） |
| 2 | vendored LightRAG 为 1.5.7 | 确认 | `lightrag/_version.py:3-4`：`__version__="1.5.7"`，api `0330` |
| 3 | 已含 MinerU/Docling/VLM 多模态；当前 pypdf→`ainsert` 未接入 | 确认，并细化 | 多模态是**逐文档 opt-in**：`process_options` 的 `i/t/e` 开关（`constants.py:422-425`；`lightrag.py:6372-6377`）；全局 addon 开关已废弃、仅记日志（`addon_params.py:26,34-36`）；API 默认 `F` 即 VLM 关闭（`api/routers/document_routes.py:2407-2408`）；`ainsert` 无 `process_options` 参数（`lightrag.py:1765`），多模态只能走 `apipeline_enqueue_documents`（`pipeline.py:1050-1057`）。解析器选择顺序＝文件名 `[hint]`→`LIGHTRAG_PARSER` 规则→legacy 默认（`parser/routing.py:1416-1503`） |
| 4 | `ainsert_custom_kg` 缺操作 journal 与文档恢复锚点 | 逐字确认 | `lightrag.py:3455-3459` 签名；`:3465-3476` 恢复警告原文 |
| 5 | （补充事实）引用粒度 | 新事实 | `aquery_data` 的引用只到 file/chunk 级：`utils.py:6436-6562` 中 entities/relationships **无** `reference_id`，仅 chunks 有；`api/routers/query_routes.py:1046-1094` 的 OpenAPI 示例展示了实体级 `reference_id`，与实现不符。**PACE 的 span 级锚点只能由证据存储承担**——与主文档 §4.1 的设计判断一致，且否决了"直接复用 LightRAG 引用"的捷径 |
| 6 | corpus.py 哈希与 unified_corpus 清单可用 | 确认 | manifest 字段＝source_id/pdf_sha256/input_file/page_count/text_characters/status/warnings；**无** DOI、组织、版本、许可字段 |
| 7 | schema 有孕周窗口/版本关系但不足以做区间判断 | 确认 | `benchmark/qa/schema.py`：`GESTATIONAL_WINDOW`、`REQUIRED_IN`（:58-59）、`UPDATED_BY`（:91-92）存在；`GUIDELINE_REGISTRY` 11 条 `valid_until` 全为 None，仅 1 条 `superseded_by` 别名（:231-238）；`EvidenceLevel` L1/L2/L3 把组织层级与研究设计混为一谈（FDA 网页=L1 :239-246，2014 回顾性研究=L3 :247-255）——正是主文档 §3 要求拆开的混淆，现状即证据 |
| 8 | Judge 上下文截断问题 | 确认并定位 | `benchmark/qa/judge.py:44`：`max_context_chars=12000`（answer/gold 各 8000，:45-46）。这是 [增量报告](../../benchmark/report/preclinical-incremental-20260911.md) 中 faithfulness 0.78→0.99 翻转的直接开关 |
| 9 | 检索通道现状 | 新事实 | `benchmark/common/retrieval.py` 只做 context 扁平化；项目代码（common/client/qa）中无任何 BM25/Okapi 实现（检索 0 命中）→ 主文档 §5.1 的 BM25 召回通道是全新代码 |

## 2. 语料新发现（主文档未覆盖）

### 2.1 重复与身份歧义（最重要的新事实）

33 份 PDF 只有 1 对字节级重复被折叠（manifest `duplicate_count=1`）。按每份抽取文本**页首 DOI** 逐一核对，32 份"索引文本"实际只对应 **26 篇不同文章**：

| 类型 | 文章（页首 DOI，均已打开核对） | 卷入文件与结果 |
|---|---|---|
| 字节级重复（已折叠） | 11–14 周 2023（uog.26106） | 2 文件同 sha256，1 份入索引 |
| 同文异源：两个 source_id **都已索引** | 中孕 2022（uog.24888，UOG 2022;59:840–856）；产时 2018（uog.19072，UOG 2018;52:128–139）；生物测量与生长 2019（uog.20272，UOG 2019;53:715–723）；侵入性操作 2016（uog.15945，UOG 2016;48:256–268） | 各 2 份 PDF，hash 不同，抽取字符差 0.3%–7%（如产时 65,515 vs 61,229 字符；PDF 文件大小 15.9MB vs 430KB，扫描版与排版版） |
| 同 ID 双版本：一个 source_id 下两份文本**都已索引** | CNS part1 2020（40,426 vs 43,282 字符）；心脏筛查 2023（84,850 vs 85,282 字符） | `ISUOG-cns-2020`、`ISUOG-fetal-cardiac-screening-2023` 各挂 2 份不同 hash 的 txt |

影响：

- 支持计数虚增与上下文预算浪费有了**语料内 live 实例**：同一篇文章的两份 chunk 可同时命中并各自计票——§4.1"证据独立性按来源家族追踪"的现实版。
- 历史 Recall@16=0.968 在重复文章下略微虚高；不影响"召回饱和、区分度在条件处理"的结论方向，但基线数字应注明该缺陷。
- 训练/测试划分若不按**文章族**隔离（而非 chunk 或文件名）会直接跨集合泄漏：重复文章的两份文本极相似（§8.1 的近重复隔离要求由此具体化）。

修复建议（新 P0，约半天工作量）：`benchmark/common/corpus.py:21-35` 的 `CANONICAL_SOURCE_FILES` 漏配了 midtrimester/intrapartum/biometry/invasive 四个长名文件；更彻底的方案是身份改为"页首 DOI ＋ hash family"两键（每篇 UOG 文章页首都印刷 DOI，可正则抽取），`SourceDocument` 增 `family_id`。ISPD 错位（§2.2）一并记入 manifest warnings，重跑 `unified_corpus`。**同日已落地**：修复全部实现并重跑——26 篇单份索引、7 条去重记录、`page1_doi` 入 manifest；另发现并清除 3 份更早构建的陈旧文本，历史基线实际索引 35 份文本而非 manifest 声称的 32 份。细节见[审计报告](./prenatal-corpus-audit-20260912.md)。

### 2.2 文件名与内容不符（潜在地雷）

`ISPD_2023_genome-wide-sequencing-position.pdf` 全文是 **NIPT** 立场声明（页首：DOI 10.1002/pd.6357，Hui 等，"…non-invasive prenatal testing…singleton pregnancies"），对 `genome-wide|exome` 全文检索 **0 命中**；真正的全基因组测序声明在另一份 Van den Veyver 文件（`International Society for Prenatal Diagnosis (ISPD) Updated Position Statement…`）中。当前题库没有任何题目引用 ISPD 来源（`benchmark/qa/dataset` 检索 0 命中），故未造成已发生的评分错误；扩到 300–500 题前必须修复或改名。结论：source 身份不可依赖文件名，与 §2.1 的两键身份方案同因。

### 2.3 真版本链（§8 版本实验的现成题源）

已核对的真实新旧链条（均为不同文章，双份都在库中）：

- 胎儿 MRI：2017（uog.17412）→ 2023 updated（uog.26129）。
- 胎儿心脏：2005 basic（年份来自文件名，页首未核对）＋ 2013 筛查（uog.12403）→ 2023（uog.26224）。

注意：中孕/产时/生物测量/侵入性操作四组"新旧文件名对"经页首核对是**同文重复，不是版本链**（§2.1），不得当作版本对使用。上述链条目前无任何 `superseded_by` 边（`GUIDELINE_REGISTRY` 仅 1 条 legacy 别名）——它们应成为 §8.1 "指南更新/部分替代"题类的直接题源，也是 `SUPERSEDES` 关系抽取的最小试点材料。

### 2.4 规模与推论

manifest 汇总：436 页、2,373,609 字符（约 60 万英文 token）、26 篇不同文章。

- 召回上限高（62 题 Recall@16=0.968）：区分度必然来自条件处理而非召回——支持把条件化作为主线。
- 批内负例供给有限（全库仅数千 chunk）：§7.2 困难负例主要靠跨文档条件变体构造，而非批内随机负例——该设计判断在语料规模上成立。
- 300–500 题目标 ≈ 每篇文章 12–19 题：题目划分与"文章族"隔离强耦合，§8.1 划分规则必须先于出题冻结。

## 3. 命名与先例核验

### 3.1 名称

- RAG/医学检索方向未发现真实碰撞：多组检索式为空是肯定性结果。搜索引擎 AI 摘要曾两次凭空给出 "PACE RAG" 论文（"Prompt-augmented Contextual RAG"、"PACE: Efficient RAG via Progressive Retrieval"），其列出的来源均不支持，判定为不存在，不得引用。
- 医学界 PACE 缩写拥挤（均已核对原始页面）：[PACE 期刊](https://onlinelibrary.wiley.com/journal/15408159)（Wiley，1978–，MEDLINE 收录）、[PACE 试验](https://www.thelancet.com/journals/lancet/article/PIIS0140-6736(11)60096-2/fulltext)（Lancet 2011，CFS RCT）、[PACE 妊娠与儿童表观遗传学计划](https://www.niehs.nih.gov/research/atniehs/labs/iidl/gen-epi/pace)（NIEHS，主题最相邻）、[AI-PACE](https://arxiv.org/abs/2602.10527)（医学教育框架，npj Digital Medicine 2026）、[PaCE](https://arxiv.org/abs/2406.04331)（NeurIPS 2024，概念工程）、PLOS PACE 图件工具（[引用页](https://pmc.ncbi.nlm.nih.gov/articles/PMC12500090)）。
- 决定：论文标题使用全称，PACE 只作短标签与代码/仓库名。主文档第 3 行的"名称唯一性尚未检索确认"已同步更新。

### 3.2 先例压力与贡献声明修正

最近邻（相关工作必须显式差异化的对象）：

- **集合选择**：[AdaGReS](https://arxiv.org/abs/2512.25052)（贪心边际收益＋冗余感知＋token 预算，ε-近似次模，含生物医学高冗余语料实验）与 [ScalDPP](https://arxiv.org/abs/2604.03240)（DPP 选择＋集合级 Diverse Margin Loss 训练目标）分别逼近主文档 §5.2 的贪心算法与 §7.2 可能的集合级训练。它们的目标＝相关性＋多样性（部分含成本），**不含**三值适用性、孕周/人群/切面/版本条件约束、不兼容合用约束与冲突保留。
- **条件化匹配**：[TrialGPT](https://www.nature.com/articles/s41467-024-53081-z)（Nat Commun 2024，逐条 eligibility 判断）、[TREC Clinical Trials 2023](https://www.trec-cds.org/2023.html)（eligible/excluded/not relevant 三级判定——三值适用性最接近的已发表先例）、[ClinicBot](https://arxiv.org/abs/2605.00846)（指南结构化单元＋可核验引用的 RAG）、[PICOs-RAG](https://arxiv.org/abs/2510.23998) 与 [AlpaPICO](https://arxiv.org/abs/2409.09704)（PICO 条件化已占据）、[EC-RAFT](https://aclanthology.org/2025.findings-acl.491.pdf)（eligibility 生成）、[资格匹配综述](https://arxiv.org/abs/2503.00863)（划定 2015–2024 已覆盖范围）。
- **训练负例**：[BiCA](https://arxiv.org/abs/2511.08029)（AAAI 2026，引用结构负例）、[商品属性不匹配负例](https://arxiv.org/abs/2605.00353)（结构化元数据负例的最直接可迁移先例）。**"医学适用性条件不匹配困难负例"检索为空**——贡献 2 的可主张空间。
- **弃答/充分性/自适应**：[Sufficient Context](https://arxiv.org/abs/2411.06037)（ICLR 2025，上下文充分性与选择性弃答）、[Adaptive-RAG](https://arxiv.org/abs/2403.14403)（NAACL 2024，三分类决策）、[Self-RAG](https://arxiv.org/abs/2310.11511)（反思 token）。
- **引用与冲突**：[ALCE](https://arxiv.org/abs/2305.14627)（引用支持评测基准）、[知识冲突综述](https://arxiv.org/abs/2403.08319)。集合选择其他先例：[PACMS](https://arxiv.org/abs/2606.20047)、[RECOMP](https://arxiv.org/abs/2310.04408)、[Provence](https://arxiv.org/abs/2501.16214)、[LongLLMLingua](https://arxiv.org/abs/2310.06839)、[成本感知选择](https://arxiv.org/abs/2606.02245)。

探查中以下条目未能对照原文核验（仅搜索摘要/列表），暂不得作为依据引用：cpgQA-DE（BMJ HCI 2026，snippet）、TruthfulRAG（AAAI 2025，listing）、RAG with Conflicting Evidence（OpenReview listing）。

结论：贡献声明应精确落在**"三值适用性×临床条件约束"与"证据集合选择"的耦合**（含不兼容合用约束、冲突保留、条件不匹配负例），而不是集合选择本身（AdaGReS/ScalDPP 已占），也不是条件化匹配本身（TrialGPT/TREC CT 已占）。主文档 §5.2 末段"若集合方法不优于简单过滤则降级主张"的防线依然必要，且现在有了明确的比较对象名单。

## 4. 修订后的第 1–2 周清单（增量）

1. **语料身份修复（新 P0）**：§2.1 四个长名映射补全或改"DOI＋hash family"两键身份并增 `family_id`；§2.2 ISPD 文件名错位记入 manifest warnings；重跑 `unified_corpus`，基线结果报告注明重复缺陷。
2. **Judge 截断修复（原计划内，已定位）**：`judge.py:44` `max_context_chars` 默认不限或可配置，判分一律使用实际生成时的完整证据包。
3. **B0/B1 检索底座**：BM25 通道为全新代码（§1#9）；LightRAG 引用只有 file/chunk 级（§1#5）——span 锚点从第一天就落在证据存储，不指望 LightRAG 引用字段。
4. **schema 增量**：`GUIDELINE_REGISTRY` 补 ISPD×2、SMFM×2 条目与 DOI/年份；`EvidenceLevel` 拆轴（组织范围 × 研究设计/推荐强度）先以注释标记，不改运行代码。
5. **版本题源**：§2.3 链条进入 §8.1 "指南更新/部分替代"题类；`SUPERSEDES` 抽取以 MRI 2017→2023 为最小试点。

→ **2026-09-14/15 落地状态**：#1 已由审计报告完成；#2/#4 已完成，#3 的证据存储与 BM25 通道已落地，#5 的版本链已入注册表（心脏 basic 实为 2006 年，页首核实）；**B0 已在新 namespace `light_rag_pace_b0_20260914` 完成（26/26 索引、50 题评估、不截断 Judge，final 0.9299）**。剩余：B1（前置=chunk 级条件抽取）、`prenatal_rag_client` 适配、MRI 链条款级试点。见 [PACE 基础批次（一）](../2026-09-14/pace-foundation-batch.md)。

## 5. 未决问题

- ~~CNS part1 与心脏筛查 2023 的双版本是排版重印还是内容更新~~ 已解决（同日 P3 diff）：六对重复页首 DOI 全部一致、差异仅版权脚注/西文摘要/下载水印，已全部归并为 26 篇单份索引；MRI 2017→2023 确认为真版本链（章节 Jaccard 0.055）。见[审计报告](./prenatal-corpus-audit-20260912.md)。
- 跨指南实验材料缺失：仓库无中文指南原文（`China-screening-2022` 仅 schema 条目，标 `primary_text_not_independently_verified`）→ 获得原文前，跨指南题只能测"来源缺失时拒绝断言"行为（增量报告的 KAG 案例已示范其必要性）。
- 教材与图像资产为零：§6 表第一行"有许可的教材材料"当前在仓库中不存在，图文支路暂无任何图像资产（pypdf 路径不提取 PDF 内嵌图）——图文部分的第一步实际是版面解析器选型与接入，而非检索。
