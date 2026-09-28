# PACE 基础批次（八）：指南版本时态（SUPERSEDES）——被替代版本不得承担直接支持

日期：2026-09-15。范围：续批次七。落地主文档 **§7 版本时态** 的确定性核心：
同一指南的多版本共存时（如 ISUOG 心脏筛查 **2006 → 2013 → 2023**、胎儿 MRI
**2017 → 2023**），**被替代版本不得承担直接支持**，只作版本比较材料。本批以
"注册表 superseded_by + 真值层 DOI"为桥构建 source_id 替代图，并把版本门控
接进证据集合选择（`comparative` 桶）。

## 1. 新增 `prenatal_rag/evidence/supersession.py`

`SupersessionGraph(edges: Mapping[str, str])`——确定性、无副作用、stdlib-first：

- 边语义 ``older -> newer``（immediately superseding）；
- `successor` / `is_superseded` / `superseded_sources`；
- `chain(s)` 返回 ``[s, 后继, …, 当前版本]``；`current_version(s)` 取链尾；
  `depth_to_current(s)` 为距当前版本跳数（当前版本 0，越旧越大）；
- **构造期 fail-closed**：自环与替代环抛 `ValueError`（环检测沿链走，重访即环）。

本模块只承载关系语义；边从何处来由调用方注入，`prenatal_rag` 不依赖
`benchmark.*`。

## 2. 证据选择接入版本门控（`selection.py`）

- `EvidenceCandidate` 新增可选字段 `source_id: str = ""`（向后兼容）；
- `select_evidence(..., supersession: SupersessionGraph | None = None)`；
- 桶判定规则（顺序即优先级）：
  1. Inapplicable → `comparative`；
  2. Unknown → `applicability_unknown`（**"Unknown 永不丢"优先于版本降级**）；
  3. **被替代来源 → `comparative`**（版本比较材料，即使 Applicable∧角色匹配
     也不得承担直接支持）；
  4. Applicable∧角色匹配∧锚点 → `primary_support`；否则 `background`。
- `supersession=None` 时行为与批次五完全一致（旧测试全绿）。

## 3. 版本图加载器 `benchmark/common/versions.py`

注册表键名与语料 `source_id` 不一致，但两侧都携带 **DOI**（语料侧在
`source_documents.family_id`）。加载器以 DOI 为桥解析
``source_id(旧) -> source_id(新)``；缺 DOI / DOI 不在语料 / 旧式别名的条目
跳过——**图只含可验证边**。无 schema 迁移。

## 4. 真实探针（`benchmark/report/supersedes_probe.py`，零 LLM）

结果 `benchmark/results/corpus-condition-20260915/supersedes_probe.json`：

- **图**：3 条边 / 3 个被替代来源。链：
  - `ISUOG_2005_basic-cardiac-screening → …-2013 → ISUOG-fetal-cardiac-screening-2023`（深度 2）
  - `ISUOG-Practice-Guidelines-sonographic-screening-fetal-heart → …-2023`（深度 1）
  - `ISUOG-Practice-Guidelines-fetal-MRI → Updated-…-fetal-magnetic-resonance-1`（深度 1）
- **触发面**：**29/50 题**的检索集命中被替代来源；开版本门控后 **共 108 个候选
  从 `primary_support` 降级到 `comparative`**（如心脏筛查 PU-L1-011：16→8；
  PU-L3-027/030/031：各降 8–9 个）。说明旧版证据在真实检索集中相当普遍。
- **诚实边界**：MRI 版本链在本 50 题集**无对应问题**（`mri_chain_exercised=false`）
  ——图已建、门控已就绪，但未被该题集触发；如实记录，不夸大为"全链验证"。

## 5. 门禁（最后一次代码编辑后的新鲜运行）

`bash benchmark/report/oldcoder_gauntlet.sh` → **6/6 ALL LAYERS PASS（EXIT=0）**：
- 全量非 baseline 套件 **428 例**通过（其中 `tests/test_prenatal_*.py` 子集 327 例；
  新增 19 例 supersession 测试。注：本行原写 "356 例" 系误用 prenatal 子集口径，已按实测更正）；
- ruff 0 警（新增 supersession/versions/probe/测试入列）；pyright 0 错 0 警；
- 覆盖 **6 段 100%**：条件 298、rrf 21、**证据 105**（selection 62 +
  **supersession 39** + `__init__` 4）、graph 99、bridge 46、pipeline 45；
- **变异 28/28 击杀**（新增 7：环检测失效 / 自环失效 / current_version 取链首 /
  depth 差一 / chain 非传递 / 版本降级失效 / 版本门控越权覆盖 Unknown）；
- 真实执行 6 段（新增 `supersedes_probe.py`）。

## 6. 对应的 §5.1 / §7 位置与下一步

§5.1 确定性子集现为：条件解析 → 并行召回(BM25+图) → RRF → 三值适用性 →
**证据集合选择（角色+适用性+版本时态联合门控）**。版本门控补齐了"时间感知"
在证据层的落点（此前只有 §3 的 `valid_until` 标注与 `updated_by` 关系类型）。

下一步候选：B1 满量真实运行 `--judge-mode required`（需 token，闭环生成端收益）；
embedding 第三通道；`valid_until` 时间窗（当前全 None）与生效期过滤；
SUPERSEDES 生成端核验（答案须引当前版本）；人群/技术轴配对题（待标注补覆盖）。

## 7. EVIDENCE 要素（old-coder）

- **SPEC**：批次 8 计划（指南版本时态门控），沿续跑模式批准执行。
- **层**：pytest(356) / ruff(0 警) / pyright(0 错) / coverage(fail-under=100 ×6)
  / mutation(28/28) / real execution(6 探针) —— 单入口
  `benchmark/report/oldcoder_gauntlet.sh` 复跑。
- **工具**：Python 3.12.3、pytest 9.1.1、coverage 7.16.1、hypothesis 6.168.0、
  ruff 0.15.17、pyright 1.1.410。
- **源状态**：git HEAD `ac6003b`；改动未提交（沿用历批次约定），关键文件：
  `prenatal_rag/evidence/supersession.py`、`prenatal_rag/evidence/selection.py`、
  `prenatal_rag/evidence/__init__.py`、`tests/test_prenatal_supersession.py`、
  `benchmark/common/versions.py`、`benchmark/report/supersedes_probe.py`、
  `benchmark/report/manual_mutation_prenatal.py`、`benchmark/report/oldcoder_gauntlet.sh`、
  `benchmark/results/corpus-condition-20260915/supersedes_probe.json`、本文档。
- **已知局限**：版本图只含可验证 DOI 边（3 条）；MRI 链未被 50 题集触发；
  版本门控依赖"旧版被检索到"（图知道当前版本存在即降级）；`valid_until` 全 None，
  生效期过滤未实现；生成端"答案须引当前版本"未核验。
