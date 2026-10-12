# C1/C2 base-gap 探针结果与归因边界（2026-10-12）

> 核验修订：保留 `f1cfb9d` 的观测数字，撤回“PACE prompt 是主因、上下文重装
> 是次因、−0.085 是常量偏移”的归因。当前探针存在上下文、检索模式和评分口径
> 混杂，**base 差距归因尚未完成**。本次仅核对代码和已有产物，未新增模型调用。

## 1. 观测结果（62 题，描述性）

| 臂 | 实际路径 | final | gen weighted | retrieval mean |
|---|---|---:|---:|---:|
| LR native（历史基线） | adaptive 路由，k=16，LR 原生生成 | **0.9193** | 0.9122 | 0.8969 |
| C2 | 独立运行 mix/top40，直接取 LR 原生答案 | 0.8725 | 0.9065 | 0.8377 |
| C1 | 独立运行 mix/top40，取返回 chunks 用 PACE prompt 重新生成 | 0.7876 | 0.8828 | 0.8104 |
| R1 A00（v2，3 重复均值） | RRF 融合，PACE prompt | 0.9064 | 0.8989 | 0.8905 |

C1−C2 = **−0.0849**；C2−LR native = **−0.0468**。这两个数是跨路径的
final 观测差值，不能分别命名为“纯 prompt 代价”和“上下文重装损失”。
C1/C2 每题各 1 次，未保存完整运行条件与失败明细；62 题含 12 道未完成专家审核
的草案，不能将这些探索性均值升级为确认性结果。

## 2. 归因未成立的具体证据

1. **未共用冻结上下文。** 探针对两臂分别调用 `client.search`，已有产物中
   **11/62 题的 `n_context` 不同**；其余题条数相同也不能证明内容、顺序一致。
   C1/C2 的 retrieval mean 分别为 0.8104/0.8377，不能视为“只换 prompt”。
2. **生成与评分所见证据未对齐。** C1 将返回 chunks 重装为 PACE 证据包并重新
   生成；C2 直接使用 `qr.response`，重装后的 chunks 只用于评分，未证明它们与
   LR 内部实际用于生成的完整上下文一致。保存的上下文条数范围为 C1 12–17、
   C2 12–19，均小于 40，不能据此声称脚本的 `raw_contexts[:40]` 切片删掉了证据。
3. **历史基线检索条件不同，且 C1/C2 是两次独立检索。** 逐题 n_context 在 11/62 题上不一致（如 PU-L2-025 14 vs 12、PU-L3-PRE012 17 vs 19）——两次运行各自重跑 mix/top40 检索，检索结果不可跨运行复现；两臂并非共享同一冻结证据包。
3. **历史基线检索条件不同。** 原生基线记录为 `adaptive`（实际路由为
   basic/local/drift），探针为 `mix`、`top_k=chunk_top_k=40`，评分参数仍为
   k=16。历史门禁中的 `source_match_mode=hybrid` 是来源匹配口径，不是
   LightRAG 检索模式。因此 C2 不是原生基线的同条件复跑。
4. **安全及失败口径未统一。** 探针未调用 `judge_safety`、未传入
   `safety_verdict`，L4 回退短语评分；R1 和历史原生结果接入了安全 verdict。
   此外，`score_arm(judge_mode="required")` 本身不阻止 Judge 错误后回退 lexical，
   探针也未校验或保存逐题错误，无法确认所有评分均成功使用 Judge。
5. **未隔离编号或 Judge 格式偏好。** PACE prompt 同时改变循证角色、仅依据
   给定材料作答、证据不足时的处理和引用要求，不能把差异归于 `[E1..En]` 编号。
   产物仅保存答案前 500 字，未保存完整 prompt、证据包及哈希，无法事后补足
   格式效应或 Judge 偏差的识别证据。

R1 A00 高于 C1 也不能排除检索与证据组成的影响：两者并非同条件的检索器消融，
且 prompt 与证据选择可能存在交互。现有数据不能给主因、次因排序。

## 3. 对 R3 的决定与声明

1. **P vs S 继续固定 PACE prompt。** 同时固定宽候选、可用元数据、预算与
   装包规则、生成/Judge 模型、输出契约、安全及失败口径，只改变预定的选择机制。
   由此估计的是“在该 prompt 和运行条件下的 P−S 效果”；固定 prompt 不保证它
   对不同选择器的影响相等，**不得假定 −0.0849 会抵消或用它校正分数**。
2. **S 配置与分数纠正。** 按本轮安排保留指定的 A11 作为 S 比较起点，其
   v2 final 是 **0.9061**。**0.9122 属于 A01**；A10 的 0.9123 仅是点估计最高，
   四臂结果未确立唯一最优配置。MMR/metadata filter 的开发比较仍待执行，
   最终强简单对照须在隐藏测试前按真实配置和比较产物冻结，不以误标的“最优”代替。
3. **外部效度仍待验证。** R3 的 P−S 收益不能直接解释为优于 LightRAG 原生
   系统。按[研究计划 §6.2](../2026-10-10/pace-research-plan.md)，同生成条件的
   LightRAG 控制 L 与原生端到端对照分别报告。R4/R5 保留原生 prompt/上下文格式
   适配与验证任务，适配后的效果另测；当前探针不能单独决定能否部署。
4. **本轮不换 prompt 重跑 R1。** 这是资源优先级决定。R1 当前主效应点估计
   接近零、尚未证实收益，不代表已证明无效、等效或没有 prompt 交互。

## 4. 后续纯 prompt 探针的最小条件（待配额，未执行）

- 每题只取一次证据并冻结；两臂共用完全相同的内容、顺序、来源信息和预算规则，
  均从该证据包重新生成，不能让一臂直接复用另一路径的原生答案。
- 区分“整个 prompt 包”的效应与“仅编号格式”的效应；后者只改变编号呈现。
  若检验 Judge 格式敏感性，另对语义不变的同一答案作格式对照并核验内容一致。
- 按题配对、交错运行两臂并记录生成重复；以题或题家族为推断单位，预先确定
  比较指标与重复数。安全 verdict、实际证据的评分方式和失败处理必须相同。
- 保存完整证据包、prompt、答案、哈希、模型参数、质量/安全 Judge 结果和错误。
  报告失败数，required Judge 失败计入失败，不静默混用 lexical 分数。

## 5. 数据与方法来源

- 观测产物：[C1](../../benchmark/results/pace_research/r0/c1_full.json)、
  [C2](../../benchmark/results/pace_research/r0/c2_full.json)、
  [R1 v2](../../benchmark/results/pace_research/r1/r1_ablation.json)、
  [LR native](../../benchmark/results/unified62/lightrag/evaluation.json)。
- 实现：[探针](../../benchmark/pace_research/probe_c1_c2.py)、
  [PACE prompt](../../benchmark/baseline/prenatal_rag_client/prompting.py)、
  [评分入口](../../benchmark/baseline/prenatal_rag_client/evaluate.py)。
- 汇总声明：[四框架终局报告 §8](../../benchmark/report/unified62-final-4fw-20261009.md)、
  [R1 报告 §4](../../benchmark/report/pace-research-r1-ablation-20261011.md)。

本次方法核验使用 `scientific-critical-thinking` 与 `experimental-design` 技能。
方法来源：Kassis, T., Agarwal, V., He, Y., Patel, D., & Brueckner, A. M. (2026).
*Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents*.
[arXiv:2609.00065](https://arxiv.org/abs/2609.00065)，
[DOI](https://doi.org/10.48550/arXiv.2609.00065)。作者与题名于 2026-10-12 核验；
该引用说明核验工作流，不作为 PACE 有效性的证据。
