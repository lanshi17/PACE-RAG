# R2 开发试标包审计报告（2026-10-12）

> 任务：27 道开发草案整理为可交专家独立审核的材料包。审计覆盖预注册
> pace-research-plan.md §5.2 的审核材料要求。**本报告不代表专家审核完成，
> 不增加隐藏题计数。**

## 1. 证据核对（12/12 通过）

| 检查 | 结果 |
|---|---|
| input_text_sha256 与语料文件一致 | 12/12 |
| excerpt 在声明坐标 char_start:char_end 处精确匹配（空白归一化后） | 12/12 |
| 真值层锚点映射（归一化 excerpt 前缀匹配 EvidenceStore chunk） | 12/12 |

- 坐标系 `raw_corpus_text_unicode_codepoints_half_open` 逐条验证；
- 原 `evidence_store_anchor_id=None` 已更新为验证后的锚点（E-AMNIO→440、
  E-MRI17→140、E-MRI23→675、E-NIPT→63、E-NEURO→88、E-TWIN→224、
  E-CALIPER→490、E-CERVIX-PREP/LANDMARK/REPEAT→327、E-GROWTH→489、
  E-REPORT→494）；`locator_status` 更新为 `text_verified_anchor_mapped_…`；
- `validate_r2_scaffold.py` 断言同步更新（anchor 需为已映射的数字 ID），
  9 项测试通过。
- 残留：PDF 页面布局复核（`pdf_layout_review_pending`）仍待专家确认——
  文本坐标与 PDF 视觉布局的对应需人工查验。

## 2. 三变体设计审查（9/9 通过）

| 检查 | 结果 |
|---|---|
| 变体类型三元组 = base/condition_change/invariant_control | 9/9 |
| known_conditions 差异键 == 声明 change_axis（单变量性） | 9/9 |
| invariant_control 的 known_conditions 与 base 完全一致 | 9/9 |

- 单变量性审计写入 `variant_audit.json` 与逐家族 `audit_20261012` 字段。
- "可能应变/应保持"清单：各家族 invariant_control 的问题措辞已做同义改写
  （如 GA-01 BASE "14周6天" vs INVARIANT "14+6周"），known_conditions 逐位
  相同——专家需确认该改写不引入语义变化，并补充逐家族的必需陈述与禁止
  断言（当前 gold 字段为空，属待填项）。
- 结构性风险（待专家确认）：UN-02 的不变对照与 base 的措辞差异极小，
  需专家判断该变体是否具有区分度。

## 3. 模板重叠审查（vs 历史 68 题）

- 词面 5-shingle（中英跨语言）：全部 0.0——语言不同，词面法不可用。
- 跨语言特征近似（术语+数字 jaccard，保守下界）：均值 0.231；
  ≥0.5 的 4 题：R2-DEV-GA-01-01（vs PU-L1-008）、R2-DEV-UN-02-01/02/03
  （vs PU-L2-025）。**文字不同不视为独立——这 4 题标记派生关系待专家裁定**。
- 审计产物：`template_overlap_audit.json`（逐题最近历史题与重叠度）。

## 4. 真实冲突家族核查（VC-01 / VC-02）

- **VC-01（MRI 版本链）**：双侧原文均在语料且坐标验证通过（E-MRI17 2017 /
  E-MRI23 2023）。措辞相似不构成真实冲突——家族设计正确地做**版本更新**
  （cutoff 2020 vs 2024），而非冲突判定。base/condition_change 的差异仅在
  cutoff 年（2020→2024），invariant_control 用同 cutoff 2020。语义检查通过。
- **VC-02（同适用范围真实冲突）**：corpus 全文阈值搜索（宫颈长度 25/15/10 mm）
  显示这些是**不同临床动作在不同阈值/语境**（筛查切点、环扎考虑、回顾性
  亚组、胎盘随访），不构成"同人群+同孕周+同目的的不相容建议"。
  `blocked_missing_bilateral_sources` 状态**确认保留**，审计记录写入家族字段。

## 5. 送审数量汇总

| 状态 | 数量 | 说明 |
|---|---:|---|
| **可送审**（证据映射完成 + 变体审计通过） | **27 题 / 9 家族** | 需专家补 gold、必需陈述、禁止断言 |
| 待修订（重叠待裁定） | 4 题（GA-01-01、UN-02-01/02/03） | 派生关系由专家裁定后可送审 |
| 缺源保留 | 1 家族（VC-02，0 题） | 找到双侧原文后才出题 |

## 6. 双人审核模板

`benchmark/qa/dataset/pace_conditions_v1/dual_review_template.json`：27 行，
每行含题干、known_conditions、证据摘录与锚点、空白 reviewer_A/reviewer_B
字段（适用性三值判定/必需陈述/禁止断言/应保持项/耗时）+ dispute 列。
审核流程：两人独立填写、分歧第三名仲裁（预注册 §5.2）。

## 7. 修订日志

| 文件 | 修订 |
|---|---|
| evidence_candidates.json | 12 条记录补 `evidence_store_anchor_id`、`locator_status` 更新、`audit_20261012` 字段 |
| dev_families.json | 9 家族补 `audit_20261012` 字段；VC-02 补审计记录 |
| variant_audit.json | 新增：9 家族单变量性与不变对照审计 |
| template_overlap_audit.json | 新增：跨语言特征重叠审计 |
| dual_review_template.json | 新增：双人审核模板（27 行） |
| validate_r2_scaffold.py / tests | anchor 断言从 None 改为已映射数字 ID |

## 8. 遗留（不在本任务范围）

- PDF 布局复核（专家）；gold/必需陈述/禁止断言填充（专家）；
- 4 题派生关系裁定（专家）；语义去重、功效论证（待隐藏集规模冻结）；
- MMR 离线对比与 S 冻结（需配额或实现）。
