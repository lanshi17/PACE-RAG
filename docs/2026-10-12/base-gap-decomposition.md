# R3 前置：base 差距分解（2026-10-12，零 token 分析）

> 问题：R1 四臂 final ≤0.9123 vs LightRAG 原生 0.9193（62 题，同判分同生成）。
> 在 P vs S 主比较前必须解释该差距，否则无法归因。

## 1. 分解：差距不在检索质量，在上下文组成 + prompt

| 证据 | 数值 | 解读 |
|---|---|---|
| LR 原生检索质量 | recall 0.9677 / precision 0.7339 / mean 0.8969 | 与 R1 各臂检索面相当 |
| R1 A00 生成 weighted_mean | 0.8989 | 低于 LR 原生 0.9122 |
| 源集合 Jaccard（LR 原生 vs A00 kept） | **均值 0.503**（分布 0.1–1.0 全谱） | 两管线选出的**来源集合只有一半重叠**——这不是同一检索的两个变体，是两个不同的检索器 |
| R1 生成 prompt | PACE `[E1..En]`（`build_generation_messages`） | LR 原生用 LightRAG 自带 prompt |

关键事实：R1 的 A00（无前置过滤、无去冗余、纯 RRF 融合）与 LR 原生**不是同一
检索路径**。快照管线是 BM25(语料库) + LightRAG 图 + 向量（vdb）三路 RRF；LR 原生
是 LightRAG hybrid（own key-word/entity/graph 机制）。source-set Jaccard 0.503
意味着约一半上下文不同——final 差距 0.007 是这两个不同上下文集合在**同一生成器
不同 prompt** 下的净值。

## 2. 差距归因的两个候选（需一个对照实验区分）

| 候选 | 预测 | 检验 |
|---|---|---|
| ① 上下文组成差异（RRF 融合 vs LR hybrid 选出的 chunk 不同） | 换用 LR 原生上下文 + PACE prompt → final ≈ 0.9193 | 对照实验 C1 |
| ② 生成 prompt 差异（`[E1..En]` 编号格式 vs LR 原生格式） | LR 原生上下文 + LR 原生 prompt vs LR 原生上下文 + PACE prompt → final 有差 | 对照实验 C2 |

若 C1 显示换上下文后 final 回到 0.919 → 差距 = 上下文组成，RRF 融合管线**弱于**
LR 原生检索 → R3 的 P/S 比较必须以**同一宽候选来源**为前提（已满足），且 base
差距是"融合排序损耗"，可单独优化。
若 C2 显示 prompt 是主因 → P/S 比较的生成端需固定同一 prompt（计划 §4.1 第 4 条
已要求），差距归入 prompt 变量，不影响检索层结论。

## 3. 对 R3 的操作结论

1. **P vs S 主比较不受 base 差距阻塞**：两者共用同一宽候选、同一 prompt、同一
   生成器（计划 §6.2 已冻结），差距是 A00-vs-LR-native 的**跨管线**比较问题，
   不是 P-vs-S 的**同管线内**比较问题。
2. 但 **H2 的外部效度**受影响：若 RRF 融合本身弱于 LR hybrid，联合选择器的
   收益可能被融合损耗吃掉。R3 探针应先跑 C1/C2 两个对照（各 50 题 × 1 重复，
   ~200 调用），把 base 差距归因清楚，再决定 P 的实现基座（LR hybrid 检索 +
   联合选择 vs 独立 RRF 管线 + 联合选择）。
3. C1/C2 属于 R3 范围内的前置探针，优先级高于联合选择器实现。

## 4. 行动项

- [ ] C1：LR 原生上下文 + PACE prompt → 50 题 × 1 重复 → final 对照
- [ ] C2：LR 原生上下文 + LR 原生 prompt（即 unified62 的 LightRAG 臂复跑）→ final
- [ ] 归因结论 → 决定 P 的检索基座
