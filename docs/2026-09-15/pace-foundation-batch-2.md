# PACE 基础批次（二）：chunk 级条件抽取 + B1 三值过滤器

日期：2026-09-15。范围：续 [PACE 基础批次（一）](../2026-09-14/pace-foundation-batch.md) §5.4 指定的下一步——B1 前置的 chunk 级条件元数据。新增 `prenatal_rag/conditions/` 包（确定性规则抽取 + 三值过滤），并让证据存储持久化每 chunk 条件。未重建任何基线索引、未运行 LLM、未训练模型。

## 1. 动机（衔接 §5.4 的第 4 条）

B1 要求"显式 metadata/区间过滤需要每 chunk 的 GA/人群/检查条件"；这就是 条件 schema → 条款级抽取 的桥。在 chunk 条件落地前不实现退化版 B1（source 级过滤是稻草人比较）。

策略与主文档 §5.1 第 3 步一致：**硬规则只判断有明确依据的数值/身份**（孕周窗口、人群/胎数、技术/切面），其余语义分类留给后续经校准的小模型，保留 Unknown。

## 2. `prenatal_rag/conditions/` 包

刻意不依赖 `benchmark.*`，与包内其他子包同构、可独立发布。

- **`schema.py`**：`ConditionType`（gestational_age / population / technique）；`GaWindow`（孕周窗口，天，支持无界侧：`26+0–28+6`→[182,202]、`≥34 周`→[238,∞)、`up to 24 周`→(-∞,168]；`overlaps`/`covers` 兼容无界）；`ChunkCondition`（类型/取值/来源文档绝对 char 区间/原文片段/pattern_id 溯源）。
- **`extract.py`**：`extract_conditions` 规则抽取。GA 六类正则（plus-window / mixed-right-plus / plain-window / 前缀≥ / 后缀≥ / 前缀≤），按具体→通用注册并经 span 去重、长者为胜；**孕周合理性守卫**剔除非孕周语义的时间短语（`_MIN_GA_DAYS=42`，抹掉 "1–2 weeks" 随访间隔这类假窗口）。人群/技术为受控词表。`index_conditions` 把抽取写回存储。
- **`filter.py`**：**三值分类器**。`classify(chunk_conditions, query)` → Applicable / Inapplicable / Unknown：
  - GA：任一窗口覆盖查询→Applicable；无覆盖但有部分重叠→Unknown (跨越边界不取中点)；全部无交集→Inapplicable；缺 GA 条件→Unknown。
  - 人群/技术：命中兼容值→Applicable；显式正对（twin↔singleton、mono↔di）→Inapplicable；否则 Unknown。
  - 合并：任一 Inapplicable→Inapplicable；任一 Unknown→Unknown；否则 Applicable。
  - `filter_chunks` 的 B1 过滤**只剔除明确 Inapplicable**，Unknown 与 Applicable 均保留（主文档 §4.2）。

## 3. 证据存储持久化

`EvidenceStore` 新增 `chunk_conditions` 表（`ON DELETE CASCADE` 挂 chunk），方法：
`rewrite_chunk_conditions`（整份替换，支持幂等/抽取器迭代）、`conditions_for`、`iter_conditions`、`build_condition_index`（便捷全量建索引）。存放内容为绝对 span，与证据存储锚点自洽。

## 4. 验证

- 新增 `tests/test_prenatal_conditions.py`（GaWindow 往返/无界、六类 GA 窗口形态、人群/技术抽取、三值分类、filter_chunks、store 持久化），全量 prenatal 测试通过，`ruff check` 通过。
- 真语料冒烟（`benchmark/report/condition_extract_probe.py`，P1.5）：341 chunks → **2651 条条件**（GA 361、population 1457、technique 833）。GA 窗口分布还原了 15 组变体的真实条款窗口：`[77,97]`(11+0–13+6)、`[84,98]`(12–14)、`[126,168]`(18–24)、`[182,202]`(26+0–28+6)、`[203,223]`(29+0–31+6)、`[224,237]`(32–33+6)、`[238,∞)`(≥34) 均正确。
- 三值抽样：20 周 vs「18–24 周」→Applicable；20 周 vs「11+0–13+6」→Inapplicable；单胎查询 vs「monochorionic twins」→Inapplicable。

> **old-coder 门禁（异步于本批，同日补齐）**：本模块按 old-coder 跑通完整 gauntlet——
> 非 baseline 套件 192 通过、pyright 0 错、ruff 通过、conditions 包**变更行覆盖 100%**、
> **5/5 手动变异击杀**、hypothesis 不变量通过、真语料实跑通过。Property 测试暴露并修复了
> `GaWindow.covers` 对无界上界查询的判错（例驱动未覆盖）；变异首轮暴露下界守卫被上界遮蔽的测试盲点。
> SPEC 与证据见 `oldcoder-spec-prenatal-conditions.md` / `oldcoder-evidence-prenatal-conditions.md`；
> 复现入口 `benchmark/report/oldcoder_gauntlet.sh`。

## 5. 边界与下一步

- 确定性规则是 B1 的保守首层：`(-∞,168]`(≤24)、`[140,∞)`(≥20) 等无界口来自条款中的 "up to / before / after / and beyond" 措辞，临床合理但语义权重需后续协议。条款级**语义**消歧（如 1–2 周随访间隔 vs 孕周窗口、绒毛膜性子类型）按主文档留给经校准的小模型分类。
- 下一步：① 用 15 组变体的**条件配对/负例**固化 `prenatal_rag_client` 下的 B1 评测；② `prenatal_rag_client` 协议适配（benchmark/baseline），把 B1 过滤接入 50 题评估与 B0 对比（fixed：B0 vs B1 检索层差异）；③ SUPERSEDES 条款级试点（MRI 2017→2023）。