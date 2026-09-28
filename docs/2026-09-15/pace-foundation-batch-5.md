# PACE 基础批次（五）：证据集合选择（三值适用性×证据角色联合门控）

日期：2026-09-15。范围：续批次四。落地主文档 **§5.2 集合目标 / §5.1 第 5 步**
的核心算法 —— **证据集合选择**：把"三值适用性 × 证据角色"的联合门控、
"Unknown 永不丢"、"Inapplicable 不删除只降级为比较材料"正式化为确定性可测代码。

## 1. 新增 `prenatal_rag/evidence/`

- **`selection.py`**：
  - `EvidenceRole`：必需证据角色（指南条款/观察/背景），由任务模板定义（§5.2）。
  - `EvidenceBucket`：输出四桶（§5.1 第 5 步）——`primary_support` / `background` /
    `applicability_unknown` / `comparative`。
  - `EvidenceCandidate`：id、三值 verdict、证据角色集、来源锚点回指标记。
  - `select_evidence(candidates, *, required_roles, budget=None, require_source_anchor=True)`：
    - **直接支持仅限 Applicable∧角色匹配∧(可选)来源锚点**（§5.2 门控）；
    - **Unknown 永不丢**，只入 `applicability_unknown`，不得承担直接支持；
    - **Inapplicable 不删除**，入 `comparative` 作真实分歧/版本比较材料；
    - Applicable 但不满足角色/锚点 → `background`；
    - 确定性（按输入顺序入桶）、预算 `budget` 封顶。
- `__init__.py` 导出。

## 2. 测试与门禁
`tests/test_prenatal_evidence.py`：7 个残缺语义 + hypothesis 属性
- 每个候选取一桶（并集守恒）；
- **Unknown/Inapplicable 永不丢弃**（属性）；
- **primary_support 仅 Applicable∧角色匹配∧锚点**（属性）；
- 预算封顶且保前缀。

`bash benchmark/report/oldcoder_gauntlet.sh` **全绿**：
- 全量非 baseline 套件通过；ruff 通过；pyright 0 错 0 警；
- 覆盖 **证据包 100% (61/61)**，连同条件(298)/rrf(21) 均 `--fail-under=100` 通过；
- **手动变异 13/13 击杀**（条件 7 + RRF 3 + 证据 3）。

## 3. 一个架构取舍（变异测试暴露）
预算守卫 `budget<=0` 返回空集那一行，经变异测试证明是**冗余分支**：循环内的
`_total >= budget` 截断已对 budget=0/负值生效，守卫改动无观测差异 → 移除该变异，
保留真正有语义的 3 个证据门控变异（角色匹配丢失 / Unknown 降桶 / Inapplicable 入错桶）。

## 4. 对应的 §5.1 流程位置
现在 §5.1 的确定性可复现子集已串成：**查询条件解析 → (BM25+RRF 合并) →
三值适用性判断 → 证据集合选择（按证据角色+适用性分桶，预算封顶）**。
embedding / LightRAG 图通道与领域 reranker 仍待接入；原子陈述生成与核验、补充检索未实现。

## 5. 下一步候选
- embedding / LightRAG 图通道接入 RRF 合并（真正多通道）；
- 用真实检索出的候选（B0 上下文）演示证据集合选择的分桶结果（真实数据探针）；
- 条件配对题集（15 组变体）让 B1 检索/生成 Δ 可见；B1 满量真实运行（需 token）；SUPERSEDES 条款级试点。