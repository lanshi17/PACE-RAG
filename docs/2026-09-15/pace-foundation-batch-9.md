# PACE 基础批次（九）：版本生效期与时点（as-of）证据选择

日期：2026-09-15。范围：续批次八。批次八把"被替代版本不得承担直接支持"落成
结构层门控（``SupersessionGraph``）。本批补上 **时间层**：

> **"替代"本身是时点相关的事实。** 2016 年时，心脏筛查的当前版本是 **2013 版**
> （2006 版已被替代、2023 版尚未发布）。只有把版本知识放进时间轴，证据选择才能
> 回答"截至某年，哪些证据可承担直接支持"。

## 1. `SupersessionGraph` 扩展为"替代图 + 时间轴"

构造：`SupersessionGraph(edges, years=..., valid_until=...)`（两个新参数均可选，
批次八调用方式完全不变）。

新增 API：

| API | 语义 |
| --- | --- |
| `publication_year(s)` | 出版年；未知 → `None` |
| `is_effective_at(s, y)` | `y` 时点是否已出版且未失效（`[生效年, 失效年)` 半开） |
| `is_superseded_at(s, y)` | 替代 `s` 的版本是否已在 `y` 时点发布 |
| `current_version_at(s, y)` | `y` 时点该链的当前版本 |

**fail-safe 口径（不丢证据，只降级）**：出版年未知时，`is_superseded_at` 按
"已替代"处理（保守降级为比较材料），`is_effective_at` 按"已生效"处理（不因信息
缺失阻塞证据）。构造期新增校验：替代边的年份必须**严格递增**，否则
`ValueError("版本年份非递增：…")`（fail-closed）。

已知边界（写在 docstring 里）：`current_version_at` 只沿后继**向前**走，故查询
起点自身尚未出版时返回起点本身（链上不存在可回退的更早版本）；是否生效由
`is_effective_at` 单独判定。

## 2. 证据选择接入 `as_of_year`

`select_evidence(..., supersession=..., as_of_year=None)`：

- `as_of_year is None` → 沿用批次八的结构层判定（行为完全不变）；
- 给出 `as_of_year` → 改用 `_temporally_blocked`：**未生效**（早于出版年、
  或超过 `valid_until`）**或在该时点已被替代** → `comparative`；
- ``Unknown`` 仍优先入 `applicability_unknown`（"Unknown 永不丢"高于时间门控）；
- 仍然只改变证据所在桶，绝不删除。

## 3. 加载器

`benchmark/common/versions.py` 从注册表补入出版年与失效年：结构边仍以 DOI 为桥；
`year` → 出版年；`valid_until` → 失效年。**注册表 `valid_until` 当前全部为未设置**，
故时间轴实际由"后继版本的出版年"驱动；`valid_until` 通路已实现并被单测覆盖，一旦
注册表填值即生效。

## 4. 真实探针（`benchmark/report/supersedes_probe.py`，零 LLM）

结果 `benchmark/results/corpus-condition-20260915/supersedes_probe.json`：

- 时点当前版本（as-of 2010 / 2016 / 2024）：
  - `ISUOG_2005_basic-cardiac-screening` → 2005 / **2013** / **2023**
  - `…sonographic-screening-fetal-heart`（2013 版）→ 2013 / 2013 / **2023**
  - `ISUOG-Practice-Guidelines-fetal-MRI`（2017 版）→ 自身 / 自身 / **2023 更新版**
- 29/50 题命中被替代来源；开时间门控后 **primary_support 总数随时点上升**：
  as-of 2010 = **136**、2016 = **148**、2024 = **319**（越晚的时点有越多来源已生效）。
- 单题示例 `PU-L1-002`：@2010 primary=1 / comparative=15；@2016 primary=4 / comparative=12；
  @2024 primary=11 / comparative=5 —— 同一检索集，随时点改变"谁可承担直接支持"。
- 结构层门控（批次八口径）在同一探针里仍报告：29 题、**共 108 个候选降级**。

## 5. 门禁（最后一次代码编辑后的新鲜运行）

`bash benchmark/report/oldcoder_gauntlet.sh` → **6/6 ALL LAYERS PASS（EXIT=0）**：
- 全量非 baseline 套件 **446 例**通过（其中 `tests/test_prenatal_*.py` 子集 345 例；
  本批新增 18 例：时间轴 9 + as-of 选择 8 + hypothesis 1）；
- ruff 0 警；pyright 0 错 0 警；
- 覆盖 **6 段 100%**：条件 298、rrf 21、**证据 154**（selection 68 +
  **supersession 82** + `__init__` 4）、graph 99、bridge 46、pipeline 45；
- **变异 34/34 击杀**（批次八 28 + 本批 6：年份非递增校验失效 / 后继年份未知时不保守 /
  `valid_until` 半开写成闭 / `current_version_at` 比较反向 / 门控忽略 as-of /
  时点替代判定失效）；
- 真实执行 6 段（含 `supersedes_probe.py` 的 as-of 演示）。

### 数字口径更正（诚实记录）

批次六/七/八文档曾把"全量非 baseline 套件"写成 337 / 337 / 356 例。经以
`pytest --collect-only` 逐文件求和核对，那三个数字实际是 **仅 `tests/test_prenatal_*.py`
子集**的口径（各批子集 308 / 308 / 327 例），全量应为 **409 / 409 / 428 例**。
三份文档已按实测更正并标注子集口径；本批起两个口径都写清。

## 6. 对应的 §7 位置与下一步

§5.1 确定性子集现为：条件解析 → 并行召回(BM25+图) → RRF → 三值适用性 →
**证据集合选择（角色 × 适用性 × 版本时态（结构+时点）联合门控）**。
§7 的"版本时态"至此在证据层具备了完整的**时点感知**。

下一步候选：embedding 第三通道（需模型 API）；生成端核验（答案须引当前版本）；
注册表 `valid_until` 实际填值（当前全 None，时间轴暂由后继出版年驱动）。

## 7. EVIDENCE 要素（old-coder）

- **SPEC**：批次 9 = 版本生效期／时点（as-of）证据选择，沿续跑模式执行。
- **层**：pytest(446) / ruff(0 警) / pyright(0 错) / coverage(fail-under=100 ×6)
  / mutation(34/34) / real execution(6 探针) —— 单入口
  `benchmark/report/oldcoder_gauntlet.sh` 复跑。
- **工具**：Python 3.12.3、pytest 9.1.1、coverage 7.16.1、hypothesis 6.168.0、
  ruff 0.15.17、pyright 1.1.410。
- **源状态**：git HEAD `ac6003b`；改动未提交（沿用历批次约定），关键文件：
  `prenatal_rag/evidence/supersession.py`、`prenatal_rag/evidence/selection.py`、
  `tests/test_prenatal_supersession.py`、`benchmark/common/versions.py`、
  `benchmark/report/supersedes_probe.py`、`benchmark/report/manual_mutation_prenatal.py`、
  `benchmark/report/oldcoder_gauntlet.sh`、
  `benchmark/results/corpus-condition-20260915/supersedes_probe.json`、
  `docs/2026-09-15/pace-foundation-batch-{6,7,8}.md`（数字口径更正）、本文档。
- **已知局限**：`valid_until` 全 None（通路已测但数据未填）；时间轴仅覆盖 3 条替代边
  （5 个来源）；MRI 链未被 50 题集触发；`current_version_at` 不能向前回溯
  （起点未出版时返回自身）；探针为机制演示，非端到端问答评测。
