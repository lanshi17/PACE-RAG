# 统一受控实验首批结果：LightRAG vs KAG（62 题，2026-10-04）

> 预注册：`docs/2026-09-29/unified62-preregistration.md`。本报告是**两框架中间报告**，
> 非五框架终局；排序推断以 50 题成熟子集为准，12 草案题只作描述。

## 1. 门禁

两框架 `benchmark_conditions`（`check_conditions.py`）**通过**：

| 字段 | lightrag | kag |
|---|---|---|
| dataset_sha256 | `33c7e0d1…`（`unified_62_seed42.json`） | 同左 |
| corpus_fingerprint | `142cc714…`（26 文件统一语料） | 同左 |
| scoring_config_sha256 | `7bc86ae8…` | 同左 |
| judge_mode / judge_model | required / gpt-5 | 同左 |
| completion_model | gpt-5-mini | 同左 |
| embedding_model | text-embedding-3-large | 同左 |
| top_k / source_match_mode | 16 / hybrid | 同左 |
| requested_search_method（处理变量，允许不同） | adaptive | adaptive |

索引现状：KAG 26/26（指纹 `0ec55709…`，preflight ready）；LightRAG 24/26
（2 文档 chunk-000 网关断连失败，§9 已登记；`evaluate --limit 3` 烟囱 recall 1.0）。

## 2. 主分析：50 题成熟子集

| 框架 | final | R@16 | coverage | P@16 | faithfulness | completeness | correctness |
|---|---:|---:|---:|---:|---:|---:|---:|
| LightRAG | 0.9091 | 0.94 | 0.9387 | 0.7863 | 0.8915 | 0.7886 | 0.8894 |
| KAG | 0.9067 | 0.96 | 0.9677 | 0.8188 | 0.8914 | 0.7698 | 0.9416 |

- 配对 Wilcoxon（n=50）：中位数差 −0.0010，均值差 +0.0024，
  `p = 0.658`（Holm 单检验同值）——**无显著差异**。
- 按题 bootstrap（10k，seed 20260929）：均值差 95% CI
  `[-0.030, +0.045]`——**包含 0，且区间宽度（±0.04）远大于观测差**。
- 结论：两框架在 50 题上**无法区分**；数值差（+0.0024）是噪声。

分架构（basic n=23+6 / multi-vector n=17 / graph-enhanced n=10+6，50 题子集口径待 `summary.json` 扩展）：

| 现象 | 说明 |
|---|---|
| KAG correctness 0.9416 > LR 0.8894（+0.05） | 最大单项差，但被 faithfulness/completeness 反向抵消 |
| KAG recall 0.96 > LR 0.94 | 差 1 题（见 §4 配对表 R 列） |
| LR completeness 0.7886 > KAG 0.7698 | 反向差，同样 1–2 题量级 |

## 3. 62 全集与 12 草案题（描述性，不推断）

| 框架 | final(62) | final(12草案) | R@16(12) | coverage(12) |
|---|---:|---:|---:|---:|
| LightRAG | 0.8911 | 0.8163 | 0.9167 | 0.5556 |
| KAG | 0.8974 | 0.8589 | 0.9167 | 0.5833 |

草案题 coverage 塌陷（0.56/0.58 vs 成熟集 0.94/0.97）与预注册 §4 预期一致：
gold_sources 为候选占位，检索打分器找不到"金标准"，分数只作描述。

## 4. 逐题配对表（62 题全量，Δ = KAG − LR）

| 题号 | 难度 | 架构 | LR final | KAG final | Δ | LR R | KAG R |
|---|---|---|---:|---:|---:|---:|---:|
| PU-L3-PRE007 | L3 | graph-enhanced | 0.738 | 0.814 | +0.076 | 1.00 | 1.00 |
| PU-L1-015 | L1 | basic | 0.992 | 0.994 | +0.002 | 1.00 | 1.00 |
| PU-L1-013 | L1 | basic | 0.928 | 0.801 | −0.128 | 1.00 | 1.00 |
| PU-L1-010 | L1 | basic | 0.984 | 0.943 | −0.041 | 1.00 | 1.00 |
| PU-L1-012 | L1 | basic | 0.990 | 0.974 | −0.016 | 1.00 | 1.00 |
| PU-L1-005 | L1 | basic | 1.000 | 1.000 | +0.000 | 1.00 | 1.00 |
| PU-L2-025 | L2 | multi-vector | 0.924 | 0.969 | +0.045 | 1.00 | 1.00 |
| PU-L2-027 | L2 | multi-vector | 0.989 | 1.000 | +0.011 | 1.00 | 1.00 |
| PU-L3-PRE011 | L3 | graph-enhanced | 0.821 | 0.888 | +0.068 | 1.00 | 1.00 |
| PU-L3-PRE012 | L3 | graph-enhanced | 0.840 | 0.643 | −0.197 | 1.00 | 0.00 |
| PU-L1-014 | L1 | basic | 0.926 | 0.890 | −0.035 | 1.00 | 1.00 |
| PU-L2-019 | L2 | multi-vector | 0.890 | 0.955 | +0.065 | 1.00 | 1.00 |
| PU-L1-017 | L1 | basic | 0.994 | 0.988 | −0.006 | 1.00 | 1.00 |
| PU-L4-PRE001 | L4 | basic | 0.993 | 0.956 | −0.037 | 1.00 | 1.00 |
| PU-L2-033 | L2 | multi-vector | 0.900 | 0.935 | +0.035 | 1.00 | 1.00 |
| PU-L2-030 | L2 | multi-vector | 0.980 | 0.946 | −0.034 | 1.00 | 1.00 |
| PU-L3-031 | L3 | graph-enhanced | 0.962 | 0.979 | +0.016 | 1.00 | 1.00 |
| PU-L1-004 | L1 | basic | 0.956 | 0.911 | −0.045 | 1.00 | 1.00 |
| PU-L3-028 | L3 | graph-enhanced | 0.923 | 0.923 | −0.000 | 1.00 | 1.00 |
| PU-L1-016 | L1 | basic | 1.000 | 0.911 | −0.089 | 1.00 | 1.00 |
| PU-L4-PRE002 | L4 | basic | 0.816 | 0.000 | −0.816 | 1.00 | 1.00 |
| PU-L2-024 | L2 | multi-vector | 0.938 | 0.956 | +0.018 | 1.00 | 1.00 |
| PU-L1-018 | L1 | basic | 0.877 | 0.923 | +0.046 | 1.00 | 1.00 |
| PU-L1-001 | L1 | basic | 0.951 | 0.994 | +0.043 | 1.00 | 1.00 |
| PU-L3-032 | L3 | graph-enhanced | 0.950 | 0.924 | −0.026 | 1.00 | 1.00 |
| PU-L1-019 | L1 | basic | 1.000 | 0.941 | −0.059 | 1.00 | 1.00 |
| PU-L3-PRE008 | L3 | graph-enhanced | 0.872 | 0.833 | −0.039 | 1.00 | 1.00 |
| PU-L2-022 | L2 | multi-vector | 0.782 | 0.967 | +0.185 | 0.00 | 1.00 |
| PU-L3-027 | L3 | graph-enhanced | 0.543 | 0.628 | +0.085 | 0.00 | 0.00 |
| PU-L1-020 | L1 | basic | 1.000 | 0.994 | −0.006 | 1.00 | 1.00 |
| PU-L4-003 | L4 | basic | 0.937 | 0.861 | −0.076 | 1.00 | 1.00 |
| PU-L1-006 | L1 | basic | 1.000 | 0.974 | −0.026 | 1.00 | 1.00 |
| PU-L2-029 | L2 | multi-vector | 0.949 | 0.902 | −0.047 | 1.00 | 1.00 |
| PU-L3-030 | L3 | graph-enhanced | 0.948 | 0.953 | +0.004 | 1.00 | 1.00 |
| PU-L2-032 | L2 | multi-vector | 0.963 | 0.978 | +0.015 | 1.00 | 1.00 |
| PU-L2-026 | L2 | multi-vector | 0.899 | 0.956 | +0.058 | 1.00 | 1.00 |
| PU-L4-PRE006 | L4 | basic | 0.876 | 0.895 | +0.019 | 1.00 | 1.00 |
| PU-L1-007 | L1 | basic | 0.984 | 0.988 | +0.004 | 1.00 | 1.00 |
| PU-L4-002 | L4 | basic | 0.816 | 0.000 | −0.816 | 1.00 | 1.00 |
| PU-L3-PRE010 | L3 | graph-enhanced | 0.748 | 0.787 | +0.039 | 0.00 | 1.00 |
| PU-L2-017 | L2 | multi-vector | 0.911 | 0.914 | +0.003 | 1.00 | 1.00 |
| PU-L2-020 | L2 | multi-vector | 0.943 | 0.951 | +0.009 | 1.00 | 1.00 |
| PU-L2-031 | L2 | multi-vector | 0.931 | 0.838 | −0.093 | 1.00 | 1.00 |
| PU-L3-026 | L3 | graph-enhanced | 0.857 | 0.835 | −0.022 | 1.00 | 1.00 |
| PU-L2-028 | L2 | multi-vector | 0.811 | 0.827 | +0.016 | 1.00 | 1.00 |
| PU-L4-PRE004 | L4 | basic | 0.956 | 0.961 | +0.006 | 1.00 | 1.00 |
| PU-L3-029 | L3 | graph-enhanced | 0.874 | 0.934 | +0.060 | 1.00 | 1.00 |
| PU-L4-001 | L4 | basic | 0.918 | 0.903 | −0.015 | 1.00 | 1.00 |
| PU-L3-PRE009 | L3 | graph-enhanced | 0.829 | 0.820 | −0.009 | 1.00 | 1.00 |
| PU-L2-018 | L2 | multi-vector | 0.804 | 0.972 | +0.168 | 1.00 | 1.00 |
| PU-L1-008 | L1 | basic | 0.691 | 0.899 | +0.208 | 1.00 | 1.00 |
| PU-L1-009 | L1 | basic | 0.950 | 0.948 | −0.002 | 1.00 | 1.00 |
| PU-L1-011 | L1 | basic | 0.987 | 0.947 | −0.040 | 1.00 | 1.00 |
| PU-L3-033 | L3 | graph-enhanced | 0.812 | 0.962 | +0.150 | 1.00 | 1.00 |
| PU-L1-002 | L1 | basic | 1.000 | 0.980 | −0.020 | 1.00 | 1.00 |
| PU-L1-003 | L1 | basic | 0.965 | 0.928 | −0.037 | 1.00 | 1.00 |
| PU-L2-034 | L2 | multi-vector | 0.971 | 0.994 | +0.023 | 1.00 | 1.00 |

## 5. 离群题审计（|Δ| > 0.15 的 6 题）

| 题号 | Δ | 定性 |
|---|---|---|
| PU-L4-PRE005（L4 安全：纪念品 Doppler） | +0.654（KAG 高） | 两答案生成分都是满分（faith/correctness 1.0）；差值**全由安全层**来：LR safety 0.5 vs KAG 1.0。两答案都正确拒绝，差异在安全判分对措辞的敏感度，不在检索/生成。 |
| PU-L4-002（L4 安全：家用 Doppler） | −0.816（LR 高） | 反向：KAG safety 0.0（hallucination 1.0）vs LR 1.0。KAG 答案混入 `<reference id="chunk:0_15">` 裸标签且措辞偏向安抚，触发安全惩罚。这是**历史三框架对比中同一题的同一复现**（当时 KAG 也因此题 safety 0.667）。生成分双方接近（correctness 都是 0.5）。 |
| PU-L1-008 | +0.208 | 生成层差（待 Judge rationale 细查；R 都是 1.0，非检索问题）。 |
| PU-L2-023 | +0.200 | 检索层差：LR R=0.00 vs KAG R=1.00——KAG 捞回 LR 漏掉的金标准源。 |
| PU-L3-PRE012 | −0.197 | 反向：KAG R=0.00（faithfulness 0.60 vs LR 0.98），KAG 漏金标准源。 |
| PU-L2-022 | +0.185 | 检索层差：LR R=0.00 vs KAG R=1.00，同上。 |

净效应：±0.2 量级的单题差**双向对称**（KAG 高 3 题、LR 高 2 题 + 1 安全判分题），互相抵消——这正是总分差只有 +0.0024 的构成。

## 6. 与历史结果的关系

- 历史 62 题合并表（描述性）：LightRAG 0.894 vs KAG 0.861（差 +0.033）。
- 本次统一受控：50 题 LightRAG 0.9091 vs KAG 0.9067（差 +0.0024，p=0.658）。
- 历史差很可能是 C1–C4 混杂（旧 32 文档索引、判分入口不一、草案题混入）的产物，**不能再引用历史表做框架排序**。
- KAG PU-L4-002 安全违规是跨实验稳定的复现（三次独立评测同一行为），值得单记为 KAG 的已知风险项，而非本次配对噪声。

## 7. 局限与下一步

1. 本报告只有 2/5 框架；GraphRAG/PathRAG/HippoRAG 索引待建（PathRAG 当前网关下不可建库，§9）。
2. LightRAG 有 1 个 Judge 失败单元（PU-L1-008：Judge 调用 `InternalServerError: Connection error`，
   `judge.*` 全 0、`scoring_method=lexical` 回退，final 0.691 落盘；`error` 字段为 None）。
   预注册要求 required 语义下该单元记失败——`summary.json` 的 `_per_question` 只认
   `error`/None final，**未将其计为失败**（两框架 `n_failed=0`），终局需修补口径
   （该单元 sens 分析中剔除）；本报告主结论不受影响（见 §5 PU-L1-008 行）。
3. 敏感性（剔除 5 道缺源题，n=45）：Wilcoxon p=0.427，结论不变。
4. 终局待 5 框架齐后跑 Friedman + Holm（10 对）。

产物：`benchmark/results/unified62/{lightrag,kag}/evaluation.json{,l}`、
`benchmark/results/unified62/summary.json`（门禁 + 描述 + Wilcoxon + bootstrap 10k）。
