# 语料身份修复与条件密度审计（P1+P3 批次报告）

日期：2026-09-12。批次范围：P3 版本链裁决 → 语料身份修复（落地）→ P1 条件密度审计。探针脚本位于 `benchmark/report/`（`corpus_diff_probe.py`、`condition_density_probe.py`），结果数据位于 `benchmark/results/corpus-audit-20260912/`。全部为调研/修复批次，未启动任何模型训练、未重建任何基线索引。

## 1. P3：六对重复的裁决（全部为同文重复，无隐藏更新）

方法：页首 DOI + 卷期页码行 + 全文 5-词 shingle Jaccard + 逐页相似度 + 最差页 diff 片段（[corpus_diff_results.json](../../benchmark/results/corpus-audit-20260912/corpus_diff_results.json)）。

| 对 | 页首 DOI（双方一致） | shingle Jaccard | 差异集中处 |
|---|---|---|---|
| 中孕 2022 | 10.1002/uog.24888 | 0.987 | 首末页下载水印 |
| 产时 2018 | 10.1002/uog.19072 | 0.975 | 西班牙文摘要（一份有、一份无）+ 水印 |
| 生物测量 2019 | 10.1002/uog.20272 | 0.989 | 西文摘要 + 版权脚注 |
| 侵入性操作 2016 | 10.1002/uog.15945 | 0.992 | 版权脚注 |
| CNS part1 2020 | 10.1002/uog.22145 | 0.986 | 逐页版权脚注（一份漏抽） |
| 心脏筛查 2023 | 10.1002/uog.26224 | 0.996 | 无（最低页相似度 0.990） |

**裁决：六对全部为同一文章的不同 PDF 副本（出版版式 / 扫描版 / 下载水印差异），正文内容无实质差异，全部归并，不建版本链。** 续记 §5 的第一个未决问题就此关闭。

真版本链表面核查（[同结果文件](../../benchmark/results/corpus-audit-20260912/corpus_diff_results.json)）：胎儿 MRI 2017（uog.17412）vs 2023（uog.26129）章节结构几乎重写（57 节 vs 97 节，仅 8 节标题重合，Jaccard 0.055），推荐措辞与 GA 提及量级相近（17/17、16/19、9/10）→ `SUPERSEDES` 抽取试点必须做**条款级对齐**，不能做文件级替换。心脏链（2005 basic〔年份来自文件名，页首未核对〕＋ 2013 uog.12403 → 2023 uog.26224）维持为版本链候选。

## 2. 语料身份修复（已落地并重跑）

`benchmark/common/corpus.py`：

- `CANONICAL_SOURCE_FILES` 补 4 个长名映射（midtrimester / intrapartum / biometry / invasive 的 `ISUOG-Practice-Guidelines-*` 文件此前漏配，是同文异源的直接原因）。
- `ISPD_2023_genome-wide-sequencing-position.pdf`（实为 NIPT 立场声明，Prenat Diagn 2023;43:814–828，DOI 10.1002/pd.6357，年份/卷期已从页首核实）更名 `ISPD-nipt-2023`，历史 ID 记录在新增的 `KNOWN_SOURCE_ISSUES` 并写入 manifest warnings。
- 新增 `extract_page1_doi()`：从 `## Page 1` 段抽 DOI 作为内容级身份信号。

`benchmark/common/unified_corpus.py`：

- 新增 `plan_family_duplicates()`：同 source_id 且页首 DOI 相同 → 保留抽取字符数最多的一份（并列按文件名），其余记 `duplicate`（`duplicate_reason="same-page1-doi"`）；DOI 缺失或分歧的同组 → 保留全部并写警告，不擅自合并。
- `prepare_corpus` 重跑后清理 `input/` 孤儿文本（manifest 未引用即删除）；manifest 每文档新增 `page1_doi`，顶层新增 `pruned_text_count`。

重跑结果：33 PDF → **26 篇索引文本、7 条去重记录（1 identical-bytes + 6 same-page1-doi）、0 错误**；23/26 有页首 DOI（缺失：SMFM×2 与 Minor markers，均单副本家族，无归并歧义）。

**修复过程中的新发现**：`input/` 中还残留 3 份更早构建的陈旧文本（`ISUOG_2016/2018/2019` 的长名 PDF 曾以短 slug 落盘）。`read_corpus_documents` 按 glob 读取目录而非 manifest，因此**历史基线实际索引的是 35 份文本**，重复虚高比例高于续记 §2.1 的估计；本次 `pruned_text_count=11`（7 份同文副本 + 1 份 ISPD 改名 + 3 份陈旧）已全部清除。历史评测产物不回填；B0/B1 起的实验必须以新 namespace 从 26 份文本重建。

测试与验证：`test_common_corpus.py` / `test_common_unified_corpus.py` 新增 9 例（新映射、DOI helper、dedup planner 的合并/警告/候选排除/并列决胜），全量 pytest 通过，ruff 通过。

## 3. P1：条件密度审计

方法链：prescan（26 篇，剥离 Wiley 每页下载水印后 1.80M 字符 / 341 页）→ sample（每篇 GA 最密 2 页共 48 页为挖掘集，加每篇 1 个种子随机页共 23 页为无偏集，seed=20260912）→ LLM 逐页抽取（71 页，554 条陈述，0 失败；字段：quote / topic / ga_weeks{min,max} / conditions / conditional_type / uncertain）→ analyze（外推与变体组聚类）。

prescan（[condition_density_prescan.json](../../benchmark/results/corpus-audit-20260912/condition_density_prescan.json)）：

- GA 提及共 1,788 处，中位密度 7.05/10k 字符。最密文章：荷兰早孕筛查 24.5、11–14w 2023 19.8、**双胎 18.2（population 词条 760，绒毛膜性条件最富集）**、子痫前期 17.6、SGA/FGR 17.0、早产 13.5。
- 8 篇含 supersession 语言（ISPD 两份各 2、SMFM/中孕/心脏/CNS-part2/胎儿心脏筛查 2013 各 1）；产时指南 GA 密度最低（0.49）——其条件轴是产程阶段而非孕周，提示条件 schema 不能只有 GA 轴。
- Wiley 下载水印约占保留文本 3.7%（~70k 字符）——证据存储 ingest 层应剥离（新改进项；本次探针在内存剥离，落盘文本保持原样以稳定哈希）。

抽取质量抽查：GA 结构化正确（11+0–13+6 → 11/13；FGR 26–32 周条目正确拆出 singleton、AC<10th、UA PI>95th、DV 阳性等条件），存在少量图注/叙述句噪声——**本审计数字可用于可行性判断，正式训练/评测前必须人工审核**。

无偏外推：15/23 个随机页含正文，94 条条件性陈述 → 全语料条件性陈述约 **1,594 条**（点估计；11 篇随机页无正文记 0，属保守下偏）。GA 条件占抽取陈述的 29%（75 纯 GA + 95 混合）。

条件变体组（挖掘集 394 个 topic 聚类，token Jaccard≥0.6）：**15 组**满足"≥2 条陈述且适用性签名 ≥2 种"，其中 10 组为同指南内变体（配对条件交换题的最佳素材），5 组跨文章（困难负例素材）。典型组：DV 异常分娩时机（4 条、2 个 GA 窗）、心脏筛查最佳时机（3 条、**3 篇文章**、2 窗）、晚孕期超声时机（2 窗 + 1 人群变体）、软指标咨询（2 种技术条件）、"既往宫颈环扎史"（GA + 人群 + 技术三维变体）。

**对杀线的裁决**：按页数占比（48/341≈14%）外推全语料变体组约 100 组（受聚类阈值与 LLM 抽取质量影响，误差约 ±2 倍），高于续记设定的 50 组杀线 → **贡献 1/2 的数据基础成立**。产能主要来自"同指南条件表"（双胎绒毛膜性表、FGR 分层标准、GA 分层筛查时点），P2 试点应优先从这些表格化条款抽样。

## 4. 对既有文档的修订

- 续记 §5 未决 1（CNS/心脏双版本）已解决并标注。
- 续记 §2.1 补记历史 35 份文本的事实。
- 主文档 §3 的"26 篇"表述升级为已落地状态，并指向本报告。

## 5. 局限

LLM 抽取为单遍、未人工审核，仅用于密度与结构可行性判断；变体组计数对聚类阈值（0.6）敏感；外推点估计偏保守（零正文文章记 0）；P3 心脏链中 2005 年份仍未从页首核实；落盘文本未剥离水印（保持哈希稳定，剥离留给证据存储 ingest 层）。
