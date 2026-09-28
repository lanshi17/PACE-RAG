# PACE 基础批次（十一）：embedding 第三通道（并行召回补齐三路）

日期：2026-09-15。范围：续批次十。主文档 §5.1 第 2 步的"并行召回"此前只落了
**两路**（BM25 + 图通道）；本批补齐第三路 **embedding**，并把"读冻结向量 + 本地
余弦排序 + 回映锚点 + RRF 三路合并"固化为可测 API。

## 1. 新增 `prenatal_rag/retrieval/vectors.py`（纯 stdlib）

背景：LightRAG 投影里**已经存有**冻结的 chunk 向量，不必重新编码语料。

```python
VectorIndex.from_vdb_json(path)        # 读 nano-vectordb（以 matrix 为准）
index.rank(query, *, k=None, keys=None)  # 余弦降序，平分按键升序
```

- **不引入第三方依赖**：解码用 `base64` + `array`，点积用 `math.sumprod`
  （CPython 3.12 的 C 实现）。实测：解码 468×3072 矩阵 0.035 s，全量排序
  **0.016 s/查询**——stdlib 足够，无需 numpy；
- **确定性**：按 `(-相似度, 键)` 排序；零向量/零查询的余弦定义为 `0.0`（不产 NaN，
  不抛除零）；`k<=0` 返回空列表（与 `top_k` 语义一致）；`keys` 子集去重保序；
- **存储格式的一个坑（值得记下）**：nano-vectordb v2 把精确的 float32 矩阵放在
  `matrix`，而每条记录里的 `vector` 字段是同一向量的 **float16 有损副本**。若把
  后者的字节按 float32 解读，会得到 ~1e-10 量级的**伪向量**且不报错。本模块一律
  以 `matrix` 为准，并把这条写进模块 docstring；
- 字节序：nano-vectordb 以小端写出。本机是小端，故换序分支在真实数据上**不会**
  执行——为不让它成为永不执行的代码，解码抽成 `_decode_matrix(raw, *, swap)`
  并由测试显式传 `swap=True` 覆盖（"换序逻辑确实被执行且结果确实不同"）。

## 2. `pipeline.py` 扩展

- `EmbeddingChannel(index, bridge)`：向量在**投影 chunk 空间**排序，再经与图通道
  **同一个** `OverlapBridge` 回映到真值层锚点；无映射的 chunk 跳过、同一锚点只保留
  向量排名最高的一次；
- `parallel_recall(..., embedding_ranking=None)`：新增可选第三路。缺省 `None` 时
  行为与批次六**完全一致**（向后兼容，有专门测试）；
- 顺带修掉一处潜藏不一致：`GraphChannel.rank(k=0)` 原会返回首个扩展锚点，现与
  `top_k`/新通道统一为**空列表**。

## 3. 实测（`embedding_channel_probe.py`，真实 3072 维向量）

用 `text-embedding-3-large`（`RAG_EMBEDDING_DIMENSION=3072`）编码 50 条问题，
在冻结 B0 投影上跑三路召回：

| 指标 | 值 |
|---|---|
| 索引 | 468 chunks × 3072 dims，**468/468 成功回映锚点**（桥在向量空间无损失） |
| 向量通道独有锚点（BM25∪图都没有） | 均值 **6.9/题**，**50/50 题**均 > 0 |
| 三路合并相对两路的新增锚点 | 均值 **3.96/题** |
| 源级覆盖（对冻结 B0 上下文的来源集合） | 两路 **0.6607** → 三路 **0.7208**（+6.0 pt） |
| 向量 top-1 落在 B0 上下文内 | **0.98**（49/50） |

**诚实边界**：上面覆盖的是**冻结 B0 检索集**，不是端到端正确率。另外当前向量通道在
**条件过滤之前**排序，applicability 门控仍在下游生效。

## 3b. 金标准打分的三通道消融（真正的 Δ 证据，仍为零 LLM）

想回答"向量通道到底有没有用"，先要澄清一个**架构事实**：`prenatal_rag_client` 的
B1 明确**复用冻结的 B0 上下文、不重跑检索**（其模块 docstring 第一句）。因此"把
向量通道接进 B1"**不会改变任何一条上下文**——它测不出第三通道的作用。而检索层的
Δ 可以在**离线、零 LLM、零重索引**下直接测：数据集带 `gold_sources` 标注，基准自带
的 `compute_retrieval_metrics`（hybrid 口径 + 来源等价）就是打分器。

`three_channel_ablation.py` 对同样这 50 题给三臂打分：

| 臂 | 候选空间 | precision@16 | recall@16 | coverage@16 | miss@16 |
|---|---|---|---|---|---|
| `b0_frozen`（参照） | LightRAG 投影 chunk（468） | 0.7887 | 0.96 | 0.9413 | 0.0 |
| `bm25_graph` | 真值层锚点（341） | 0.7812 | 0.94 | 0.957 | 0.0 |
| `bm25_graph_embedding` | 真值层锚点（341） | **0.8263** | **0.98** | **0.9627** | 0.0 |

配对差（三通道 − 两通道）：recall **+0.04**（2 题改善 / 0 题变差），coverage
**+0.0057**（2 改善 / 1 变差），precision **+0.045**。三项同向改善，且只用
**16 个锚点**就拿到高于冻结 B0（0.96）的 recall 0.98。

**口径声明**：后两臂同在锚点空间、可严格对比；`b0_frozen` 分块粒度不同
（LightRAG chunk vs 真值层锚点），只作参照，不据此下"打赢/打输"的结论。

### 自查修掉的一个指标口径错误

消融首跑时 `precision@16` 出现 **2.11 / 2.35** 这种大于 1 的值。查打分器源码
（`scoring.py:335-370`）：`n_retrieved = len(retrieved_sources)` 按**来源**计，而
`relevant` 按**片段**计，故契约要求 `retrieved_supports` 与 `retrieved_sources`
**等长**。我的探针把"按来源去重后的列表"配上了"逐锚点的 supports"（16 条 supports
对 ~7 个来源），违反契约，precision 被系统性放大。改为不去重、两列表严格 1:1
（与 `evaluate.py::_score_arm` 的用法一致）后回到合理区间（0.78 / 0.83）。

不修这一步，本批会带着一个**看起来更漂亮**（precision 2.35）却无效的数字进文档——
这也是探针必须打印原始指标、而不是只打印结论的原因。

## 4. 查询向量缓存 → 门禁可离线复现

缓存与编码逻辑抽到共享层 `benchmark/common/embeddings.py`（两个探针复用，避免
跨脚本 import 私有名）：

`benchmark/results/corpus-condition-20260915/query_embeddings.json`
（50 × 3072，base64 float32，820 KB）。探针**默认读缓存**、只在 `--refresh-embeddings`
时触网，因此门禁第 6 段的真实执行**不依赖网络**且结果逐位可复现。

这一点不靠"看着像"来保证：`tests/test_common_embeddings.py` 把"缓存命中时若触网
就抛异常"写成了断言（`test_cache_hit_never_touches_the_api`），并覆盖部分命中、
缓存缺失写盘、强制刷新、批大小（25 条 → 10+10+5 切批）、维度不符报错、缺 key 报错。

## 5. 变异门禁发现的一个等价变异体

首次跑变异层时 48/49，幸存者是"`VectorIndex.rank` 的 `k<=0` 保护放宽为 `k<0`"。
分析后确认它**不可能被击杀**：对 `k=0`，早退返回 `[]` 与落到末尾的 `ordered[:0]`
结果相同——即这是一个**等价变异体**（行为完全一致），不是测试不足。

处理：把该变异改成"**删除**保护"，于是负 `k` 会退化成 `ordered[:-3]`（返回除最后
3 个以外的全部），与测试断言的 `[]` 不同 → 立即被击杀。教训写进本文件：**变异措辞
必须落在真正存在行为差异的路径上，否则它衡量的是测试的运气而不是强度。**

## 6. 门禁 / EVIDENCE

- **测试**：非 baseline 全量 **518**（含 baseline 共 547；prenatal 子集 406）。
  本批新增 58 例：`tests/test_prenatal_vectors.py` 33 例（含 5 条 hypothesis 属性：
  排名是键的排列、正缩放不变、`k` 是前缀、top-1 余弦最大、余弦对称）+
  `tests/test_prenatal_pipeline.py` 14 例（EmbeddingChannel 8 + 三路 RRF 5 +
  图通道 `k=0` 1）+ `tests/test_common_embeddings.py` 11 例（编解码往返、
  批切分、维度/缺 key 报错、**缓存命中不触网**、部分命中、写盘、强制刷新）；
- **ruff** 0 警、**pyright** 0 错 0 警；
- **覆盖率 8 段全部 100%**：conditions 298 / rrf 21 / evidence 155 /
  version_citations 71 / graph 99 / bridge 46 / pipeline **69** / vectors **96**；
- **变异 49/49 全击杀**（本批新增 11 个：排序方向、零范数保护 ×2、重复键校验、
  子集去重、忽略 k、`k<=0` 保护 ×3、两通道去重 ×2、RRF 丢弃第三路）；
- **缓存哨兵 OK**（批次十的字节码污染防线仍在）；
- **真实执行 9 段**：条件抽取、B1 检索消融、图通道、条件对构建/统计、版本替代、
  生成端核验、**向量通道**、**三通道金标准消融**（后两者走缓存，离线）；
- 命令：`bash benchmark/report/oldcoder_gauntlet.sh`（EXIT=0，`ALL LAYERS PASS`）。

## 7. 下一步候选

1. **运行时检索臂**：新增一个"真的按三通道重检索再生成"的评估臂（B1 当前是冻结
   上下文设计，要测生成层 Δ 必须先有这条臂），再跑 judge；这是**唯一**能把本批的
   检索层 Δ 传递到答案层的路径；
2. 条件过滤前置：先在 applicability 通过集内做向量排序，让三路在同一候选池上竞争
   （当前向量通道在过滤前排序，与 B1 的"同检索 + 显式过滤"口径不完全对齐）；
3. 注册表 `valid_until` 实际填值（批次九已留好生效期接口，当前全为 None）。
