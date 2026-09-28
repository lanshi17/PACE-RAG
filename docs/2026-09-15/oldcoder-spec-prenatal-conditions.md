# SPEC — chunk 级条件抽取与 B1 三值过滤器

日期：2026-09-15。适用代码：`prenatal_rag/conditions/`（新增）与
`prenatal_rag/evidence_store/store.py`（新增条件持久化）。本 SPEC 为**追溯性**
契约：代码在先、验收在后（用户要求以 old-coder 门禁通过后才能进入下一步）。
因此 `spec approval: not obtained pre-code`，EVIDENCE 置信度相应下调；本文件
是验收后供人工复核的行为契约。

层次（Calibration）：**Tier 2**（正常规模特性）＋ 因涉医学适用性语义，附加
property 不变量与手动变异。隔离机制：**无 worktree/branch** —— 门禁只在现有
工作树上运行（无新源码改动、无运行时依赖变更），blast radius 为新增/改动的
~8 个源文件；新增仅测试期工具 `coverage`(7.16.1)、`hypothesis`(6.168.0) 装入
现有 `.venv`（不写入 `pyproject.toml`）。

## 行为契约（可执行验收准则）

E = gestational_age 条件，P = population，T = technique。

### GA 抽取（extract.py）
- G1 `"26+0 to 28+6 weeks"` → 单条 GA `[182,202]`，pattern `ga_plus_window`
- G2 `"26 to 28+6 weeks"`、`"32-33+6 weeks"` → `[182,202]` / `[224,237]`，`ga_mixed_right_plus`
- G3 `"18 to 24 weeks"`、`"12-14 weeks"` → `[126,168]` / `[84,98]`，`ga_plain_window`
- G4 `"at 34 weeks or more"` → `at_least(238)`，`ga_suffix_at_least`
- G5 `"at least 34 weeks"` → `at_least(238)`，`ga_prefix_at_least`
- G6 `"up to 24 weeks"` → `at_most(168)`，`ga_prefix_at_most`
- G7 合理性守卫：`"follow-up in 1 to 2 weeks"` → **无** GA 条件（非孕周语义，`_MIN_GA_DAYS=42`）
- G8 `base_offset=100` 时 GA 的 `char_start == 100 + 本地偏移`（绝对锚点）
- G9 纯普通文本 → 无 GA 条件；overlap 时更具体/更长者胜出且不重复记账

### GaWindow（schema.py，孕周以天）
- W1 `serialize`/`parse` 往返保持 closed 与无界 `(238,)`、`( ,168)` 持等
- W2 非法边界（lower>upper）→ `ValueError`
- W3 `overlaps`/`covers` 兼容无界：`at_least(238)` 与 `[280,280]` overlaps、与 `[210,220]` 不相overlaps；`(238,287)` covers `(240,250)`

### 人群 / 技术抽取
- P1 `"monochorionic twins"` → P 值含 `{monochorionic, twin}`
- T1 `"1.5 T four-chamber view cfDNA"` → T 值含 `{field_1.5t, four_chamber, cfdna_screen}`

### 三值分类（filter.py，主文档 §4.2）
- C1 20+0 vs 证据 `[126,168]` → **Applicable**
- C2 20+0 vs `[77,97]` → **Inapplicable**
- C3 查询区间 `18+4..25+5` 跨 `[126,168]` 边界 → **Unknown**（不取中点）
- C4 查询限 GA 而 chunk 无 GA 条件 → **Unknown**
- C5 查询 population={singleton} vs chunk `monochorionic twins` → **Inapplicable**（正对）
- C6 查询 population={twin} vs 同 chunk → **Applicable**
- C7 无任何约束 → **Applicable**
- C8 混合（GA+人群均不适用）→ **Inapplicable**

### B1 过滤（filter_chunks）
- F1 只剔除**明确 Inapplicable**；Applicable 与 Unknown（含无条件 chunk）均保留

### 存储持久化（store.py 增）
- S1 `rewrite_chunk_conditions` 整份替换；`conditions_for`/`iter_conditions` 回读一致
- S2 `build_condition_index` 幂等（重复运行结果稳定）
- S3 存储的 span 为来源文档规范化文本内的绝对偏移；`source_id` 正确保留
- S4 整份替换语义：源文档文本变化被重入时旧条件随旧锚点级联删除（`ON DELETE CASCADE`）

## 不变量 / 负约束（contract clauses）
- N1 `GestationalAge`/`Bm25Index` 等既有模块的公开 API 不变（只增 `store.py`）
- N2 `prenatal_rag` 不依赖 `benchmark.*`
- N3 只剔除 Inapplicable；Unknown 永不因过滤被丢弃
- N4 孕周始终以天、不擅自外推边界（`GaWindow` 无界侧仅由明确措辞产生）
- N5 抽取确定：相同输入 + 偏移 → 逐字节相同的条件集（hypothesis property）
- N6 新增运行时依赖 = 0（仅测试期 coverage/hypothesis 装入 venv）

## 设置计划（门禁会添加/修改的路径）
- 新增：`prenatal_rag/conditions/{__init__,schema,extract,filter}.py`、`tests/test_prenatal_conditions.py`、
  `benchmark/report/condition_extract_probe.py`、`benchmark/report/oldcoder_gauntlet.sh`、
  `docs/2026-09-15/pace-foundation-batch-2.md`、`docs/2026-09-15/oldcoder-spec-prenatal-conditions.md`、
  `docs/2026-09-15/oldcoder-evidence-prenatal-conditions.md`
- 修改：`prenatal_rag/evidence_store/store.py`、`prenatal_rag/evidence_store/__init__.py`
- 工具：`uv pip install --python .venv/bin/python coverage hypothesis`（测试期，非 pyproject 依赖）
- git：不主动 commit（仓库 owner 未授权提交节奏）；以 `git status`/`git diff` 复核变异恢复

交付：绿色跑通后产出 `oldcoder-evidence-prenatal-conditions.md`，映射每个行为到验证测试，
并记录各 gauntlet 层命令与**最终一次**运行的实际数字。