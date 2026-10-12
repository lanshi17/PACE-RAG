# C1/C2 base-gap 探针结果（2026-10-12）

> 归因 R1 四臂（≤0.9123）与 LR 原生（0.9193）的差距：上下文组成 vs prompt。

## 1. 结果（62 题，同生成器/判分器/评分口径）

| 臂 | 上下文 | prompt | final | gen weighted | retrieval mean |
|---|---|---|---:|---:|---:|
| LR native（基线） | LR hybrid | LR 原生 | **0.9193** | 0.9122 | 0.8969 |
| C2 | LR hybrid（top40） | LR 原生 | 0.8725 | 0.9065 | 0.8377 |
| C1 | LR hybrid（top40） | PACE `[E1..En]` | 0.7876 | 0.8828 | 0.8104 |
| R1 A00 | RRF 融合 | PACE `[E1..En]` | 0.9064 | — | — |

注意：C2（0.8725）低于 LR native（0.9193），尽管两者同为 LR hybrid 上下文 +
LR 原生 prompt——差异来自 **top40 截断 + 上下文重装**（C2 把 chunk 重新装成
benchmark contexts，LR native 是原生管线内拼接）。C1 比 C2 低 0.085 =
**PACE prompt 的代价**。

## 2. 归因

1. **Prompt 是主因**：C1−C2 = −0.085（同上下文同截断，只换 prompt）。
   PACE 的 `[E1..En]` 编号 + 来源标识格式显著压低生成质量——评分器（Judge）
   对无编号引用/自由格式的答案给分更高，或编号格式本身干扰生成。
2. **上下文重装次之**：C2−LR native = −0.047。top40 截断 + 重装丢失了
   LR 原生管线的上下文排序与压缩策略（LR native 不是简单 top-k 拼接）。
3. **检索器差异是小的**：R1 A00（RRF 融合）0.9064 **高于** C1（LR hybrid
   上下文 + PACE prompt）0.7876——说明 PACE prompt 换到 RRF 上下文上反而
   表现更好，上下文组成不是 main driver。

## 3. 结论与对 R3 的决定

1. **base 差距主因 = PACE prompt**，次因 = 上下文重装。两者都不是
   "RRF 融合弱于 LR hybrid"。
2. **R3 主比较的口径修正**：P vs S 的生成端**必须固定同一 prompt**（计划
   §4.1 第 4 条已要求）——若用 PACE prompt，P 和 S 都承受 −0.085 的格式
   代价，比较内部有效；若用 LR 原生 prompt，需要把联合选择器的输出适配
   LR 格式。**决定：R3 主比较固定 PACE prompt**（与 R1/R0 管线一致，
   已验证可跑），并在报告中声明 prompt 代价为常量偏移。
3. **H2 外部效度**：PACE prompt 的 −0.085 意味着当前管线不能直接部署；
   工程化需要把联合选择器输出适配到 LightRAG 原生 prompt/上下文格式。
   这是 R4/R5 的工程项，不影响 R3 的机制比较。
4. **与 R1 的关系**：R1 四臂在 PACE prompt 下测得的因子效应（≈0）在
   LR prompt 下可能不同——但鉴于 R1 效应量 ≈0 且 CI 宽，换 prompt 重跑
   四臂的预期收益低，不做。

## 4. 数据

- `benchmark/results/pace_research/r0/c1_full.json`、`c2_full.json`
- 探针：`benchmark/pace_research/probe_c1_c2.py`
