# R2 送审包审计报告 v4（2026-10-13 初版；v4 修订 2026-10-13）

> v5 修订（失败路径回归）：锚点反例补齐——同源摘录前缀相同/后文不同 →
> `full_excerpt_not_contained`（CLI exit 1）、来源文件缺失 →
> `source_file_missing`（CLI exit 1）；暴露集失败路径——历史文件缺失 →
> `file_missing`、内容改变记录数不变 → `sha256_mismatch`（均使重叠入口
> exit 2，且不覆盖已有重叠产物）。固化为仓库测试（`00e1ff6`）。
>
> v4 修订（一致性补丁）：材料哈希同步为最终产物（A/B 包 + 仲裁模板三份
> 清单逐文件校验）、匹配理由改用实际历史题文本（16 条非零分数全部复算）、
> GA 解析 `num:6` 泄漏修复（`14+6` 特征层仅 `ga_days:104`）、反例验证固化为
> 可复现测试（覆盖错来源/缺失锚点/CLI 非零退出码）、报告数字从产物生成
> （锚点 341 chunks、输入 98 条）。

> 任务：27 道开发草案整理为可交专家独立审核的材料包。**本报告不代表专家
> 审核完成，不增加隐藏题计数。实际隐藏题仍为 0，gold 保持未冻结。**
>
> v3 修订（审计补正 §1–§5 落地）：
> ① 锚点校验 v3（`verify_anchors_v3.py`）：统一入口/JSON/失败非零退出码、
>    快照与内容身份指纹、前缀命中改记候选、反例检出测试通过；
> ② 暴露集覆盖 v2（`verify_exposure_coverage.py`）：4/4 文件、98 条、
>    哈希+计数验证，缺失/不符报错退出；重叠审计 v3 强制以其为前置门禁；
> ③ GA 解析修正：`14周6天`==`14+6周`==`14+6`==`ga_days:104`；
>    `6周`=42（单段式不被天数模式误捕获），针对性测试 3 项通过；
> ④ 状态计数互斥口径修正（§1 互斥统计表替换 v2 混合口径）；
> ⑤ A/B 审核包 v2（材料哈希绑定、完成时间字段、提示语移入说明区）。

## 1. 状态计数（互斥口径，从同一 JSON 生成）

来源：`template_overlap_audit_v3.json` → `status_counts_mutually_exclusive`。
单位 = 开发草案变体（27 题逐题唯一归类，不重叠）。

| 互斥状态 | 变体数 |
|---|---:|
| flagged_family_adjudication（整家族标记，启发式分 ≥0.3） | 15 |
| unflagged_semantic_review_pending（无标记，语义复核待做） | 12 |
| **合计** | **27** |

- "结构一致性通过"是送审前置条件，不是互斥状态——不计入本表；
- 阈值 0.3 与用途：仅作人工语义复核的候选排序依据，不判定派生、不证明独立；
- 缺源（VC-02）：1 家族、0 题，另计。

## 2. 锚点可复现校验 v3（12/12 pass，exit=0）

`verify_anchors_v3.py`：统一入口 + 统一 JSON（`anchor_verification_v3.json`） +
失败非零退出码 + 快照身份指纹（341 chunks 的 content_fingerprint，与 EvidenceStore 一致）。
四步校验：来源文档 sha → 证据库快照锚点 → 来源一致（manifest 对照）→ 完整摘录
包含。前缀命中改记 `candidate_anchors`（候选，非"多锚点覆盖"）。
反例检出测试：错来源、缺失锚点均产生明确失败记录与非零退出码。

## 3. 历史暴露集覆盖 v2（4/4 文件 pass，98 条）

`verify_exposure_coverage.py`：以 `legacy_exposure_inventory.json` 驱动，
覆盖 4 文件 98 条（sample_questions 50 + preclinical_draft 12 + l4_safety 6 +
condition_pairs 30），sha256 与计数逐条匹配。缺失/不符 → 报错退出 +
审计标记未完成。回归测试断言 98 条记录的覆盖校验。

## 4. 重叠审计 v3

- 强制暴露集前置门禁：覆盖校验失败 → SystemExit(2)，重叠审计不运行；
- GA 同义表达解析修正：`14周6天`==`14+6周`==`14+6`==`ga_days:104`；
  `6周`=`ga_days:42`（单段式不被两段式天数模式误捕获）——针对性测试 3 项；
- 输出实际输入数量（4 文件哈希 + 98 条历史暴露记录 + 27 题草案，`n_input_questions=98`）、逐题匹配理由
  （shared concepts/numbers 列表）、概念 ID 表（14 个超声临床概念）。

## 5. 三变体设计审查（结构一致性 9/9）

| 检查 | 结果 | 说明 |
|---|---|---|
| 变体类型三元组 | 9/9 | base / condition_change / invariant_control |
| known_conditions 单变量性 | 9/9 | 差异键 == 声明 change_axis |
| invariant_control 条件与 base 一致 | 9/9 | 问题措辞同义改写，条件逐位相同 |

- 不变对照以保持含义为目标，不要求制造临床差异——专家需确认同义改写
  不引入语义变化；
- 应变项/应保持项清单已在 A/B 审核包中作为待填字段。

## 6. 真实冲突家族核查（VC-01 / VC-02）

- **VC-01（MRI 版本链）**：双侧原文均在语料且坐标验证通过；语义为版本更新
  而非冲突，与审核焦点一致。
- **VC-02**：corpus 阈值搜索显示不同临床动作在不同阈值/语境；
  `blocked_missing_bilateral_sources` 状态确认保留。

## 7. A/B 独立审核包 v2

`review_package_A.json` / `review_package_B.json`：**每份包对应一名审核者，
各含 27 题**；逐题包含临床判断、条件变化、派生关系、耗时和完成时间字段，
临床判断字段全部留空。材料绑定：4 文件 sha256 + 字节数 + git_baseline。
提示语在 `instructions`，填答字段为空列表。

`merge_arbitration_template.json`：逐题合并行 + `arbitration_requirements`
（仲裁时间/依据/人标识）+ `reviewer_A_ref`/`reviewer_B_ref` 双向引用；
材料清单与 A/B 包一致。

## 8. 送审数量汇总（互斥口径，同 §1）

| 状态 | 家族 | 题 |
|---|---:|---:|
| flagged（整家族待裁定） | 5 | 15 |
| unflagged（语义复核待做） | 4 | 12 |
| **草案合计** | **9** | **27** |
| 缺源保留 | 1 | 0 |
| 隐藏题 | — | **0** |

## 9. 修订日志（v3 相对 v2）

| 文件 | 修订 |
|---|---|
| verify_anchors_v3.py | 统一入口/JSON/失败退出码/快照指纹/前缀候选；反例检出测试 |
| verify_exposure_coverage.py | 暴露集覆盖校验（4 文件 98 条，报错退出） |
| template_overlap_audit_v3.py | 暴露集门禁前置 + GA 解析修正 + 逐题匹配理由 |
| template_overlap_audit_v3.json | 新产物（状态计数互斥口径） |
| anchor_verification_v3.json | 新产物（快照身份指纹 + 逐记录 pass/fail） |
| tests/test_r2_scaffold.py | GA 解析测试 3 项 + 暴露集覆盖回归 1 项 |
| run_arms.py | `text_lookup` 接入真值层全文（F 效应在 R1 v2 可见） |
| r1_ablation.py | `safety_verdict` 传入 `score_arm`；`include_s_variants` 参数 |

## 10. 遗留

- 专家审核（gold/必需陈述/禁止断言/派生关系裁定/重叠裁定）——外部依赖；
- 语义去重、功效论证（待隐藏集规模冻结）；
- MMR 离线对比与 S 冻结（需配额）；
- PDF 布局复核（专家）；
- required Judge 失败语义已强制化（`66f1b08`），R1 v3 重跑待配额。

## 11. 专家开发试标登记（2026-10-14）

范围：27 题 / 9 家族，双审 54 份题级记录。状态：**外部依赖，专家尚未落实**。

| 事项 | 状态 | 依赖 |
|---|---|---|
| 双人独立审核（适用性/必需陈述/禁止断言/应变-应保持/依据/时间/材料版本） | 待专家 | 临床专家 2 名 |
| 12 段证据 PDF 布局与医学支持复核 | 待专家（`pdf_layout_review_pending`） | 临床专家 |
| 单变量变化与不变对照复核；5 个标记家族优先 | 待专家 | 临床专家 |
| 分歧仲裁（第三名专家，保留双方原始意见） | 待专家 | 仲裁人 1 名 |
| VC-02 缺源项 | 单列，不进入可用性统计 | — |
| 汇总工具 | 已交付 `aggregate_expert_review.py` | — |

汇总入口（专家填毕后运行，材料哈希不符即拒绝）：

```bash
uv run python benchmark/pace_research/aggregate_expert_review.py \
  --reviewed-a review_package_A_填毕.json \
  --reviewed-b review_package_B_填毕.json
```

输出：validation_report / disagreement_log / family_status_table /
worktime_summary / gold_draft（gold 未冻结，隐藏题仍为 0）。
