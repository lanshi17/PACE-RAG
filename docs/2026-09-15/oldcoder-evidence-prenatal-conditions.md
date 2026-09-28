# EVIDENCE — chunk 级条件抽取与 B1 三值过滤器（old-coder 门禁）

日期：2026-09-15。本报告对应 SPEC `oldcoder-spec-prenatal-conditions.md`。
**spec approval: not obtained (autonomous/retrospective)** —— 代码先于门禁存在，
本 SPEC 为行为契约，供人工验收后复核；置信度据此不主张"预先批准过的契约"。

源状态：`git HEAD ac6003b`；门禁相关文件合并哈希 `2f44645009c6cf4f`（8 个源/测试/报告文件，未 commit——仓库 owner 未授权提交节奏）。
工具版本：pytest（venv 3.12.3）、ruff 0.15.17、pyright 1.1.410、coverage 7.16.1、hypothesis 6.168.0。
复现入口：`bash benchmark/report/oldcoder_gauntlet.sh`（fail-closed，任一层失败即退出非零）。

## SPEC 行为 → 验证测试映射

| 行为 | 验证处 | 结果 |
|---|---|---|
| G1/G2/G3/G4/G5 | `TestExtractionGA.test_extracts_window`（参数化六窗口） | ✅ |
| G6 | `TestExtractionGA.test_at_most_plausible_window` | ✅ |
| G7（下界守卫） | `TestExtractionGA.test_lower_guard_rejects_early_start` | ✅ |
| G8（span 守卫/绝对偏移） | `TestExtractionGA.test_at_most_implausible_upper_guard`、`test_anchor_offsets_absolute`、`TestExtractorProperties.test_plausible_guard_and_span` | ✅ |
| G9（去重/长者胜） | `TestGaOverlapDedup.test_{narrow_contained_skipped,wide_containing_replace}`（子类注入重叠 pattern） | ✅ |
| W1/W2/W3 | `TestGaWindow.test_{serialize_roundtrip_closed,half_bounded_roundtrip,bad_bounds_rejected,negative_days_rejected}`、`test_overlaps_covers_half_bounded`、`TestGaWindowProperties.*` | ✅ |
| P1 / T1 | `TestExtractionToken.test_{population,technique}` | ✅ |
| C1–C8 | `TestClassify.*`（8 个场景 + 跨维合并） | ✅ |
| F1 | `TestFilterChunks.test_drops_only_inapplicable` | ✅ |
| S1–S4 | `TestStoreConditions.test_rewrite_and_read`、`TestIndexConditionsHelper.test_writes_via_decoupled_helper` | ✅ |
| N5 抽取确定性 | `TestExtractorProperties.test_deterministic` | ✅ |
| N4 孕周以天/无界仅措辞 | `TestGaWindowProperties.*`、`TestExtractorProperties.test_plausible_guard_and_span` | ✅ |
| N1/N2/N3/N6 负约束 | ruff/pyright/覆盖/供应链层（本文件 §Gauntlet） | ✅ |

## Gauntlet（最终一轮，`bash benchmark/report/oldcoder_gauntlet.sh`）

| 层 | 命令 | 实际结果 |
|---|---|---|
| 全量测试（非 baseline） | `python -m pytest -q --ignore=tests/baseline` | **192 passed, 0 failed** |
| 静态类型 | `pyright prenatal_rag/` | **0 errors, 0 warnings, 0 informationals** |
| Lint（ruff） | `ruff check prenatal_rag/ …` | **All checks passed** |
| 变更行覆盖（门） | `coverage report --fail-under=100 <4 条件源文件>` | **100% (229/229 stmts)**；`conditions/schema,extract,filter,__init__` 各 100% |
| 变异测试（无 mutmut→手动） | `python benchmark/report/manual_mutation_prenatal.py` | **5/5 mutants killed**（见下） |
| Property（hypothesis） | 内嵌于 conditions 套件 | 全部通过（往返/覆盖蕴含相交/确定性/守卫/无界语义） |
| 真实执行 | `python benchmark/report/condition_extract_probe.py` | 341 chunks → 2651 条件；三值样例正确 |
| 套件确定性 | 无条件 pytest-randomly → **连续 3 次同输出** 44 项全过 | ✅ |

### 变异（5/5 killed；每只 once，恢复后复核文件字节）
1. `GaWindow.covers` 忽略查询无界上界 → 被 `test_covers_implies_overlaps`
2. `_window_direction` 覆盖方向颠倒 → 被 `TestClassify`
3. `_weeks_to_days` 7→6 换算 → 被 `TestExtractionGA`
4. 下界守卫停用 → 被新增 `test_lower_guard_rejects_early_start`（**首轮曾存活**，见 §异常与修复）
5. 人群正对不再判 Inapplicable → 被 `TestClassify.test_population_opposite_inapplicable`

## 关键发现 / 修复记录（honest）

- **覆盖门/变异门负对照**：`coverage report --fail-under=100 prenatal_rag/evidence_store/store.py` → exit 2、
  `Coverage failure: total of 80 is less than fail-under=100`——证明覆盖门失败路径会红，非空转。
  变异运行器在 M4 首轮存活时以非零退出（`overall: FAIL`）——证明运行器 fail-closed。
- **Property 层第一个抓到真 bug**：`GaWindow.covers` 对"有限证据窗口覆盖无界上界查询"判 True（错误）。
  例驱动测试用有限窗口未暴露；`test_covers_implies_overlaps` 立即红。已修复并锁为回归断言。
- **M4 首轮存活 → 测试盲点**：下界守卫被上界守卫遮蔽（`1–2 周` 两界都 <42，上界也拦截）。
  缺少"下界<42 而上界≥42"的样例（如 `3 to 8 weeks`）。补 `test_lower_guard_rejects_early_start` 后 M4 被正确击杀。
- **方法签名红线**：`GaWindow.covers` docstring 已注明无界语义必须两侧匹配。

## 层跳过原因
- **pytest-randomly / mutmut / pytest-cov**：环境未装，未装的原因不是不可用而是主动最小化环境变动。
  替代：套件连续 3 次同输出验证确定性；手动变异（5 变异已持久化脚本）；`coverage report --fail-under` 直接作门。
- **供应链审计（pip-audit 等）**：未运行鉴权；本批未加**运行时**依赖——coverage/hypothesis/sortedcontainers
  仅测试期装入 `.venv`（未写入 `pyproject.toml`），且已有 N6 断言 ＋ SPEC 设置计划授权。

## 已知限制（不回写为缺陷）
- 确定性抽取只覆盖硬规则形态；条款级**语义**消歧（绒毛膜性子类型、随访间隔 vs 孕周窗口）按主文档 §5.1
  留给经校准的小模型分类（`conditions/filter` 已按 Unknown 保留处理，不误删）。

## 基线说明
`tests/baseline/` 存在 **3 个历史收集期报错**（KAG/PathRAG client 在 import 时即因环境畸形 base-url，
`httpx.InvalidURL: Invalid port: ':1]'`，与本次改动无关，不 import `prenatal_rag`）。门禁以
`--ignore=tests/baseline` 运行并**只守零新增失败**；修复该环境问题属范围外，另行处理（见先前汇报）。