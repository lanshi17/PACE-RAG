# PACE 基础批次（四）：检索合并层 RRF + 变异门禁重同步

日期：2026-09-15。范围：续批次三。补主文档 §5.1 第 2 步的上层合并层
**RRF（Reciprocal Rank Fusion）+ top_k**，并把继承自旧版 conditions 源码的、
已漂移陈旧的手动变异片段**重同步到当前重构后的源码**，使变异门禁重新真实生效。

## 1. 新增/改动

- **`prenatal_rag/retrieval/rrf.py`**（新增）：
  - `reciprocal_rank_fusion(rankings, *, k=60)` —— 各通道输出**排名**，用
    `score=Σ 1/(k+rank)` 合并；只吃顺序、**禁把不同模型未校准相似度直接相加**。
    去重（通道内重复条目只计一次）、`k<=0` 抛错、平分按 `str(item)` 升序保证确定性。
  - `top_k(merged, n)` —— 截断。
  - 与 `Bm25Index` 一起导出到 `prenatal_rag/retrieval/__init__`，供 embedding/图通道后续接入。
- **`tests/test_prenatal_rrf.py`**（新增）：残缺语义测试 + hypothesis 属性
  （合并结果是并集的一个排列、**通道序无关**、去重只计一次、排序/守卫）。
- **`benchmark/report/manual_mutation_prenatal.py`**：变异器支持按 mutant 指定测试套件；
  新增 3 个 RRF 变异；**重同步 4 个陈旧条件变异**（covers / _day_component /
  合理性守卫下限 / 查询首窗优先）到当前重构后的 extract.py/schema.py/query.py。
- **`tests/test_prenatal_conditions.py`**：补 `test_query_takes_first_window`
  （M6 击杀依据）。
- **gauntlet**：ruff/覆盖纳入 retrieval/rrf.py；条件覆盖的 pytest 目标扩为全部
  `tests/test_prenatal_*.py`（覆盖重构后需辅助测试文件补齐的行）。

## 2. 门禁全绿（`bash benchmark/report/oldcoder_gauntlet.sh`）
- 全量非 baseline 套件通过（296 项）；
- ruff 通过；pyright 0 错 0 警；
- 覆盖 **条件包 100% (298/298)** + **retrieval/rrf.py 100% (21/21)**，`--fail-under=100` 通过；
- **手动变异 10/10 击杀**（7 条件 + 3 RRF）；
- 实跑：条件索引探针 + 冻结 B0 消融通过。

## 3. 变异门禁为何要"重同步"（重要）
`prenatal_rag/` 整体未提交 git。conditions 源码经历多次重构（如 `_weeks_to_days` →
`_day_component`、`_MIN_GA_DAYS` → `_GUARD_DAYS`、`covers` 重写、查询点并入抽取器
`_GA_SPECS` 末尾），导致继承的 4 个手动变异片段失配（fail-closed "出现次数≠1"）——
意味着该层其实没有在验证当前源码。本次按当前源码重写这 4 个变异的 old/new 片段，
并补充缺失的击杀测试（`test_query_takes_first_window`、既有
`test_lower_guard_rejects_early_start` 已覆盖下限守卫），重新满足 100% 击杀。

## 4. 后续对应关系（§5.1 流程）
- 第 2 步现具：BM25 通道 + RRF 合并（embedding / LightRAG 图 / 视觉通道仍待接入）；
- RRF 只出顺序，配合抽取器排序与 B1 三值过滤，即可串成
  「并行召回 → RRF 合并 → 真值层补条件 → 条件过滤 → 证据集合选择」的可确定性子集。

## 5. 下一步
- embedding / LightRAG 图通道接入 RRF（把多通道排名真正合并）；
- 证据集合选择：按三值适用性 + 证据角色从 RRF 合并结果里选可直接支持集；
- 条件配对题集（15 组变体）让 B1 Δ 可见；B1 满量真实运行（需 token）。