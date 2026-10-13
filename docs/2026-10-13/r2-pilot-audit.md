# R2 开发试标包审计报告 v2（2026-10-12 初版，2026-10-12 修订）

> 任务：27 道开发草案整理为可交专家独立审核的材料包。审计覆盖预注册
> pace-research-plan.md §5.2 的审核材料要求。**本报告不代表专家审核完成，
> 不增加隐藏题计数。实际隐藏题仍为 0，gold 保持未冻结。**
>
> v2 修订（审计补正 §5）：统一状态计数（互斥统计）、重叠分数更名为
> "启发式候选分数"、按家族组织复核（整家族标记）、补 A/B 独立审核包、
> 补锚点可复现校验 v2 与暴露集覆盖校验。"9/9 通过"限定为**结构一致性**；
> 语义有效性仍待专家审核。不变对照以保持含义为目标，不要求制造临床差异。

## 1. 状态计数（互斥统计）

| 状态 | 家族 | 题 | 说明 |
|---|---:|---:|---|
| 草案总量 | 9 | 27 | 9 个三变体家族（base/condition_change/invariant_control） |
| 结构一致性通过 | 9 | 27 | 变体三元组、单变量性、不变对照条件一致性——**仅结构** |
| 待裁定（整家族） | 2 | 6 | CE-01、GA-01：启发式重叠分 ≥0.5，整家族标记待专家裁定派生关系 |
| 语义复核待做 | 9 | 27 | **全部家族**保留人工语义复核要求——低分不证明独立 |
| 缺源保留 | 1 | 0 | VC-02：corpus 阈值搜索未找到双侧冲突原文（审计记录在家族字段） |
| 隐藏题实际数量 | — | **0** | 60 个隐藏家族配额尚未出题 |

互斥口径：每题有且仅有一个主状态。结构一致性通过是送审前置条件，不是
送审充分条件；语义有效性（派生关系、变体区分度、gold 合理性）全部待专家。

## 2. 锚点可复现校验 v2（12/12 通过）

四步校验（`benchmark/pace_research/verify_anchors_v2.py`）：

| 步骤 | 检查 | 结果 |
|---|---|---|
| 来源文档 | 文件存在 + input_text_sha256 匹配 | 12/12 |
| 证据库快照 | 声明锚点的 chunk 存在 | 12/12 |
| 来源一致 | chunk.source_id == manifest source_id（错来源反例） | 12/12 |
| 完整摘录 | 摘录完整包含于锚点 chunk 文本（空白归一化） | 12/12 |

- 多锚点覆盖：2 行有其他 chunk 也含摘录前缀（允许，逐条记录于
  `anchor_verification.json`）；
- 反例检出：错来源、仅前缀相同但非完整包含的候选会记 failure——当前无；
- PDF 布局复核继续单列待专家确认。

## 3. 历史暴露集覆盖 v2（4/4 文件通过，98 条）

`legacy_exposure_inventory.json` 驱动（`verify_exposure_coverage.py`）：

| 文件 | 声明 | 实际 | sha256 | 结论 |
|---|---:|---:|---|---|
| sample_questions.json | 50 | 50 | 匹配 | pass |
| preclinical_challenge_draft.json | 12 | 12 | 匹配 | pass |
| sample_questions_l4_safety.json | 6 | 6 | 匹配 | pass |
| condition_pairs.json | 30 | 30 | 匹配 | pass |

缺失或不一致 → 脚本报错退出（审计标记未完成）。condition_pairs.json 30 个
变体已纳入覆盖。回退测试：`tests/test_r2_scaffold.py` 回归测试覆盖 98 条断言。

## 4. 重叠审计 v2：启发式候选分数（非"语义重叠"）

- 分数更名：**启发式候选分数**（术语概念 ID + 归一化数值的 jaccard）——
  没有依据称它为语义重叠的"保守下界"；
- 中英同义词映射到统一概念 ID（14 个概念），孕周"14周6天"统一为
  `ga_days:104` 后比对；
- 全部 27 题标记 `semantic_review_required=true`——**低分不证明独立**；
- 命中分 ≥0.3 的变体所在**整家族**标记 `family_flagged_for_adjudication=true`：
  当前 5 个家族（CE-01、CE-02、GA-01、PM-01、UN-02）15 行；
- 产物：`template_overlap_audit_v2.json`（v1 词面版保留于 git 历史）。

## 5. 三变体设计审查（结构一致性 9/9）

| 检查 | 结果 | 说明 |
|---|---|---|
| 变体类型三元组 | 9/9 | base / condition_change / invariant_control |
| known_conditions 单变量性 | 9/9 | 差异键 == 声明 change_axis |
| invariant_control 条件与 base 一致 | 9/9 | 问题措辞同义改写，known_conditions 逐位相同 |

- 不变对照以保持含义为目标，不要求制造临床差异——专家需确认同义改写
  不引入语义变化；
- 应变项/应保持项清单已在 A/B 审核包中作为待填字段（见 §6）。

## 6. A/B 独立审核包与合并仲裁

`review_package_A.json` / `review_package_B.json`：各覆盖 27 题，**临床判断
字段全部留空**（适用性三值判定、必需陈述、禁止断言、应变项/应保持项、
派生关系判断及理由、耗时、审核者标识、时间、材料版本）。

`merge_arbitration_template.json`：逐题合并行（agreements / disagreements /
arbitration），保留双方原始意见与仲裁依据，不覆盖。

`review_package_A.json` 与 `B.json` **结构完全一致**——独立填写由流程保证，
不由文件差异保证。

## 7. 真实冲突家族核查（VC-01 / VC-02）

- **VC-01（MRI 版本链）**：双侧原文均在语料且坐标验证通过；base(cutoff
  2020) 只含 E-MRI17，condition_change(cutoff 2024) 含两版——语义为版本
  更新而非冲突，与审核焦点一致。
- **VC-02**：corpus 阈值搜索（25/15/10 mm 宫颈长度）显示的是不同临床动作
  在不同阈值/语境——`blocked_missing_bilateral_sources` 状态确认保留，
  审计记录写入家族字段。

## 8. 修订日志

| 文件 | 修订（v2 相对 v1） |
|---|---|
| anchor_verification.json | 新增：四步校验 v2 + 反例检出 |
| verify_exposure_coverage.py | 新增：暴露集覆盖校验（4 文件 98 条） |
| template_overlap_audit_v2.py / .json | 新增：概念 ID + 归一化数值的启发式候选分数，整家族标记 |
| review_package_A/B.json | 新增：独立 A/B 审核包（替代共享 dual_review_template） |
| merge_arbitration_template.json | 新增：合并与仲裁记录模板 |
| tests/test_r2_scaffold.py | 补暴露集覆盖回归测试；锚点断言同步更新 |
| 本报告 | 状态计数互斥化、分数更名、按家族组织复核、A/B 包说明 |

## 9. 遗留（外部依赖或需配额）

- 专家审核（gold/必需陈述/禁止断言/派生关系裁定/4 题重叠裁定）——外部依赖；
- 语义去重、功效论证（待隐藏集规模冻结）；
- MMR 离线对比（需 vdb 向量逐对余弦，实现待做）与 S 冻结；
- PDF 布局复核（专家）；
- required Judge 失败语义强制化已实现（`66f1b08`），R1 v3 重跑待配额。
