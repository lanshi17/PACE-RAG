# 统一受控实验终局：四框架（62 题，2026-10-09）

> 预注册：`docs/2026-09-29/unified62-preregistration.md`。**PathRAG 未入榜**：
> 其索引在当前网关下不可建库（单 chunk `APIConnectionError` 即整文档回滚，2/26，
> §9），按预注册"缺框架不阻塞其余"处理。五框架口径见 §5。

## 1. 门禁

graphrag / lightrag / kag / hipporag 四框架 `benchmark_conditions` 两两一致（通过）：
同语料（26 文件统一语料指纹 `142cc714…`）、同数据集（`unified_62_seed42.json` sha `33c7e0d1…`）、
同生成（gpt-5-mini）/ 判分（gpt-5，required）/ 向量（text-embedding-3-large）、
同 k=16、来源匹配口径 `source_match_mode=hybrid`、同题序（seed=42）。
此处 hybrid 不指各框架的实际检索模式。索引全部**新建**（26/26；LightRAG 曾 24/26，
`retry-failed` 补齐后 62 题已按 verdict 口径重跑，本报告 §2/§3 为重跑后数字）。

## 2. 主分析：50 题成熟子集（LightRAG 已用 26/26 全索引重跑 + verdict 口径；下表为重跑后口径）

| 框架 | final | R@16 | coverage | P@16 | faithfulness | completeness | correctness | n |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LightRAG | **0.9279** | 0.98 | 0.9587 | 0.8013 | 0.942 | 0.8066 | 0.9096 | 50 |
| HippoRAG | 0.9090 | 0.96 | 0.9563 | 0.79 | 0.9726 | 0.714 | 0.8668 | 50 |
| KAG | 0.9067 | 0.96 | 0.9677 | 0.8187 | 0.8914 | 0.7698 | 0.9416 | 50 |
| GraphRAG | 0.8733 | 0.84 | 0.869 | 0.704 | 0.8312 | 0.7842 | 0.9018 | 50 |

- **Friedman（n=50，零剔除）**：stat=6.489，`p=0.090`（未过 0.05，但 Kendall's
  W=0.043 显示框架排序开始解释方差）。
- **Holm 配对 Wilcoxon（6 对）**：**1 对显著**——GraphRAG−LightRAG 中位数差
  −0.0141，`p_holm=0.017`；bootstrap CI `[-0.084, -0.027]` **不含 0**，仅支持
  "GraphRAG 显著低于 LightRAG"这一条；次接近：LightRAG−HippoRAG `p_holm=0.073`、
  CI `[0.007, 0.032]` 不含 0（LightRAG 高）。其余 4 对 p_holm ≥ 0.37。
- **结论（更新）**：LightRAG ≥ HippoRAG、KAG > GraphRAG 的分层开始显形；
  GraphRAG 在与其余三框架的配对中均处下风但仅对 LightRAG 过显著性门槛。
  注意 faithfulness/completeness 的框架间排序与 final 不完全同向
  （GraphRAG completeness 0.7842 高于 KAG 0.7698），单指标不作排序依据。

## 3. 62 全集（描述性）

| 框架 | final | n / n_failed |
|---|---:|---:|
| LightRAG | 0.9193 | 62 / 0 |
| HippoRAG | 0.9010 | 62 / 0 |
| KAG | 0.8974 | 62 / 0 |
| GraphRAG | 0.8438 | 62 / 0 |

## 4. 与历史结果对比（同框架配对）

| 框架 | 历史合并表 final | 统一受控 final（50 题口径） | Δ |
|---|---:|---:|---:|
| LightRAG | 0.894 | 0.9279 | +0.03 |
| KAG | 0.861 | 0.9067 | +0.05 |
| GraphRAG | 0.817 | 0.8733 | +0.06 |

三框架分数**整体上移**，且历史 +0.033 的 LR−KAG 差被抹平（配对 Wilcoxon
p=0.559）——C1–C4 混杂（旧 32 文档索引、判分入口不一、安全口径）是历史排序的来源。
GraphRAG 提升最大（+0.06）：统一索引去掉了旧索引的陈旧残留与社区摘要污染路径。

## 5. 五框架口径

- PathRAG 缺席：非方法论问题，是基础设施问题（网关断连 × 整文档原子回滚，§9）。
  若网关稳定后补齐，接入即重跑 `summarize_unified62.py`（脚本已参数化框架列表）。
- 62 题中 12 题草案（`adjudicated=False`）只作描述：草案集四框架均值
  GraphRAG 0.7211 / LightRAG 0.8832 / KAG 0.8589 / HippoRAG 0.8676——
  全部低于成熟集，与预注册 §4 预期一致（gold 占位拉低 coverage）。

## 6. 产物

- 逐题：`benchmark/results/unified62/{graphrag,lightrag,kag,hipporag}/evaluation.json{,l}`
- 汇总：`benchmark/results/unified62/summary.json`（门禁 + 描述 + Friedman + Holm + bootstrap 10k + 敏感性）
- 偏离日志：预注册 §9（12 条，含 verdict 口径修复 `c95cd87` 与三客户端接线
  `c95cd87`、LR/KAG 索引重建门禁修复、安全结论修正 `ce75f9f`）

## 7. 剩余项

- ~~LightRAG 补 2 文档~~：已完成（retry-failed 26/26），LightRAG 62 题已用全索引
  + verdict 口径重跑（62 题 final 0.9193；50 题成熟子集 0.9279；Judge 62/62）
  ——终局数字以本版为准。
- PathRAG 建库（网关稳定后重试；`--max-async 2` 已备）。
- 安全专项（已结，结论修正）：KAG PU-L4-002 非三次稳定违规——单题 A/B 探针
  （`benchmark/report/unified62-kag-safety-pu-l4-002.md`）显示两臂均未违规，
  是 gpt-5-mini 措辞随机带内的**概率性风险**（四次观测三次违规）；根因在判定层，
  建议确定性后检正则 + Judge 并联（未实现）。L4 安全集 6 道草案待专家审核。

## 8. PACE prompt 代价声明与归因边界（2026-10-12 补充）

后续 C1/C2 探针在 62 题上的 final 为 C1 0.7876、C2 0.8725，
**C1−C2 = −0.0849**；C2 相对本报告 LR native 0.9193 的差值为 **−0.0468**。
这些是跨路径的描述性差值，**尚不能识别 PACE prompt 的独立代价**，不改变
§2/§3 的四框架结果。原“prompt 主因、上下文重装次因、常量偏移”的结论撤回。

核验发现：C1/C2 分别检索，11/62 题的上下文条数不同；C1 用返回 chunks 重新
生成，C2 直接取 LR 原生答案，未证明两者生成所见证据一致。探针使用 mix/top40，
历史 LR 基线使用 adaptive/k=16；探针也未接入安全 verdict，且未保存逐题 Judge
失败明细。因此差值混有证据选择、生成路径、评分及随机性差异，不能归为编号格式
或 Judge 格式偏好，也不能据此排除检索器差异。

R3 的 **P vs S 固定 PACE prompt**，并统一候选、可用信息、预算规则、生成与
判分条件，结论限定为该条件下的联合选择效果。相同 prompt 不证明它对两种选择器
有相同影响，不能将 −0.0849 作为抵消项或分数修正量。相对原生 LightRAG 的收益
需另行验证；R4/R5 的原生格式适配仍是待实现、待验证事项。

S 比较按本轮指定以 A11 为起点，但 R1 v2 中 **A11=0.9061、A01=0.9122、
A10=0.9123**，不能将 A11 标为“同管线最优 0.9122”。MMR/metadata filter
的开发比较及最终 S 冻结仍待完成。本轮不因 prompt 问题重跑 R1，是资源安排，
不代表已证明因子无效或没有交互。

实现证据、原始产物和后续隔离条件见
[C1/C2 核验记录](../../docs/2026-10-12/c1-c2-results.md)；
[R1 报告](pace-research-r1-ablation-20261011.md)同步上述边界。
