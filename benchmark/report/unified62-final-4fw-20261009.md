# 统一受控实验终局：四框架（62 题，2026-10-09）

> 预注册：`docs/2026-09-29/unified62-preregistration.md`。**PathRAG 未入榜**：
> 其索引在当前网关下不可建库（单 chunk `APIConnectionError` 即整文档回滚，2/26，
> §9），按预注册"缺框架不阻塞其余"处理。五框架口径见 §5。

## 1. 门禁

graphrag / lightrag / kag / hipporag 四框架 `benchmark_conditions` 两两一致（通过）：
同语料（26 文件统一语料指纹 `142cc714…`）、同数据集（`unified_62_seed42.json` sha `33c7e0d1…`）、
同生成（gpt-5-mini）/ 判分（gpt-5，required）/ 向量（text-embedding-3-large）、
同 k=16 hybrid、同题序（seed=42）。索引全部**新建**（26/26，除 LightRAG 24/26 两文档
网关断连，verdict 口径修复后其 L4 分数已按新口径重跑）。

## 2. 主分析：50 题成熟子集

| 框架 | final | R@16 | coverage | P@16 | faithfulness | completeness | correctness | n |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| LightRAG | **0.9135** | 0.94 | 0.9387 | 0.7863 | 0.8915 | 0.7886 | 0.8894 | 49 |
| HippoRAG | 0.9090 | 0.94 | 0.9003 | 0.7228 | 0.9734 | 0.7403 | 0.8876 | 50 |
| KAG | 0.9067 | 0.96 | 0.9677 | 0.8188 | 0.8914 | 0.7698 | 0.9416 | 50 |
| GraphRAG | 0.8733 | 0.88 | 0.816 | 0.5842 | 0.8788 | 0.6208 | 0.872 | 50 |

- **Friedman（n=49 complete-case）**：stat=0.428，`p=0.934`，Kendall's W=0.0029。
- **Holm 配对 Wilcoxon（6 对）**：全部 p_holm ≥ 0.37，无显著差异；
  最大配对差（GraphRAG−LightRAG）中位数仅 −0.0066。
- **结论**：四框架在 50 题上**无法区分**——不是"没跑出来"，是效应量本身趋零
  （W=0.003 意味着框架排序解释的方差 <0.3%）。

## 3. 62 全集（描述性）

| 框架 | final | n / n_failed |
|---|---:|---:|
| HippoRAG | 0.9010 | 62 / 0 |
| KAG | 0.8974 | 62 / 0 |
| LightRAG | 0.8944 | 61 / 1（Judge 调用失败，verdict 口径计失败） |
| GraphRAG | 0.8438 | 62 / 0 |

## 4. 与历史结果对比（同框架配对）

| 框架 | 历史合并表 final | 统一受控 final | Δ |
|---|---:|---:|---:|
| LightRAG | 0.894 | 0.9135 | +0.02 |
| KAG | 0.861 | 0.9067 | +0.05 |
| GraphRAG | 0.817 | 0.8733 | +0.06 |

三框架分数**整体上移**，且历史 +0.033 的 LR−KAG 差被抹平（+0.0024，p=0.83）——
C1–C4 混杂（旧 32 文档索引、判分入口不一、安全口径）是历史排序的来源。
GraphRAG 提升最大（+0.06）：统一索引去掉了旧索引的陈旧残留与社区摘要污染路径。

## 5. 五框架口径

- PathRAG 缺席：非方法论问题，是基础设施问题（网关断连 × 整文档原子回滚，§9）。
  若网关稳定后补齐，接入即重跑 `summarize_unified62.py`（脚本已参数化框架列表）。
- 62 题中 12 题草案（`adjudicated=False`）只作描述：草案集四框架均值
  GraphRAG 0.7428 / LightRAG 0.8163 / KAG 0.8589 / HippoRAG 0.8676——
  全部低于成熟集，与预注册 §4 预期一致（gold 占位拉低 coverage）。

## 6. 产物

- 逐题：`benchmark/results/unified62/{graphrag,lightrag,kag,hipporag}/evaluation.json{,l}`
- 汇总：`benchmark/results/unified62/summary.json`（门禁 + 描述 + Friedman + Holm + bootstrap 10k + 敏感性）
- 偏离日志：预注册 §9（8 条，含 verdict 口径修复 `c95cd87`、LR/KAG 索引重建门禁修复）

## 7. 剩余项

- PathRAG 建库（网关稳定后重试；`--max-async 2` 已备）。
- 安全专项：KAG PU-L4-002 verdict 三次稳定违规（跨实验复现），生成约束/后检独立推进；
  L4 安全集 6 道草案待专家审核。
- LightRAG 补 2 文档（ISPD-nipt、midtrimester-2022，chunk-000 网关断连）——
  不影响四框架终局（敏感性已覆盖），网关稳定后 `retry-failed` 即可。
