# PACE 基础批次（十）：生成端版本一致性核验（答案须引当前版本）

日期：2026-09-15。范围：续批次九。批次八/九保证了**检索与选择层**不把被替代版本
当直接支持，但生成模型仍可能在答案正文里引用旧版编号（"2006 版指南指出…"）。
本批补上 §7 版本时态的**第三层：生成端核验**。

## 1. 新增 `prenatal_rag/evidence/version_citations.py`

确定性函数（无 LLM、无网络）：

```python
verify_version_citations(answer, contexts, supersession, *, as_of_year=None)
```

- 解析答案中的 ``[E{i}]`` 引用标记（与提示词 ``[E1]..[En]`` 约定一致），按 1-based
  下标映射回上下文记录得到被引来源；越界下标与空 ``source_id`` 安全跳过；
- 对每个**已被替代**的被引来源，取其当前版本（`as_of_year` 给定时用批次九的
  `current_version_at`）：
  - 当前版本**也在候选上下文内**却未被引用 → `missing_current`（陈旧引用，模型过失）；
  - 当前版本**不在候选上下文内** → `unavailable_current`（不可得，不计模型过失）；
  - 旧版与当前版并引 → 允许（版本比较是正当用法）。

状态：`CONSISTENT` / `STALE_ONLY` / `CURRENT_UNAVAILABLE` / `NO_CITATIONS`；
`is_consistent` 仅把 `STALE_ONLY` 视为失败。

## 2. 接入 B1 端到端评估

- `run_b1_evaluation(..., version_check=...)`：新增可选核验器（依赖注入，与
  `llm_func` 同风格）；提供时**持久化每题答案**（此前只存分数，无法事后核验）并记录
  两臂核验结论与 `version_check_summary`；
- CLI 默认由证据真值层构建核验器（`build_version_checker`，`--no-version-check` 可关）。

**作用面**（冻结 B0 上下文实测，`version_citation_probe.py`）：**22/50 题**的上下文含
被替代来源；其中 **20 题**对应当前版本同样在场（答案可被问责——只引旧版即判
`stale_only`），**2 题**当前版本不可得（判 `current_unavailable`，不计模型过失）。合成
"旧版+当前版"答案时有 19 题被接受为 `consistent`，另 3 题因**该旧版自身的**当前版本
不在上下文内而仍为 `current_unavailable`。

## 3. 过程中发现并修复的工程缺陷：字节码缓存污染

写批次的核验器单测时出现反常现象：`inspect.getsource` 显示
`successor_year > year`，而同一函数的**字节码**是 `<`（比较方向相反）——即进程
运行的是**变异体**。

根因：手动变异 runner 用等长改写（`>` → `<`，源码字节数相同），且写回原文与变异体
落在**同一秒**内，CPython 的 `mtime + size` 校验便认为旧 `.pyc` 仍然有效；于是变异
编译产物在恢复源码后继续被加载。危害有二：(1) 污染变异层之后的门禁层（后续"真实
执行"可能跑在变异体上）；(2) 使"击杀"结论失真（变异可能根本没生效，或残留生效）。

修复（本批落地）：

1. runner 在每次变异**前**与恢复**后**删除该模块的 `__pycache__/*.pyc`；
2. mutant 子进程以 `PYTHONDONTWRITEBYTECODE=1` 运行（不再产生缓存）；
3. gauntlet 在变异层之后新增**缓存完整性哨兵**：断言时间轴
   `current_version_at` 在 2005/2015/2025 分别给出 a/b/c，否则整层失败。

修复后全部门禁层重新跑过（本批数字均为修复后的新鲜结果）。

## 4. 门禁（最后一次代码编辑后的新鲜运行）

`bash benchmark/report/oldcoder_gauntlet.sh` → **6/6 ALL LAYERS PASS（EXIT=0）**：
- 全量非 baseline 套件 **460 例**通过（其中 `tests/test_prenatal_*.py` 子集 359 例；
  本批新增 14 例：核验器 13 + hypothesis 1）；
- ruff 0 警（新增 `version_citations` 模块、其测试、prenatal_rag_client 两文件入列）；
  pyright 0 错 0 警；
- 覆盖 **7 段 100%**：条件 298、rrf 21、**证据 155**（`__init__` 5 + selection 68 +
  supersession 82）、**version_citations 71**、graph 99、bridge 46、pipeline 45；
- **变异 38/38 击杀**（批次九 34 + 本批 4：陈旧判定失效 / 下标下界失效 /
  缺失与不可得互换 / 被替代判定取反）；
- **缓存哨兵 OK**；真实执行 6 段。

## 5. 满量 judge 运行结果（50 题，`--judge-mode required`，约 56 分钟）

产物 `benchmark/results/corpus-condition-20260915/b1_end_to_end_ctrl.json`（本批同时
持久化每题答案与两臂核验结论，为后续审计留痕）：

- **双臂评分**（受控重生成，同一冻结上下文）：b0_ctrl final **0.8795**、b1 final **0.8815**；
  recall 0.96 / 0.96，precision 0.7887 / **0.7917**，coverage 0.9413 / 0.9413，
  faithfulness 0.9794 / **0.9834**，completeness **0.7574** / 0.754，
  answer_correctness 0.9004 / **0.9088**。仅 **2 题**发生条件过滤（共 drop 6 条），
  且只有这 2 题两臂答案不同。
- **版本核验（本批新增）**：
  - b0_ctrl：`consistent` 13、`no_citations` 36、**`stale_only` 1**；
  - b1：`consistent` 14、`no_citations` 35、**`stale_only` 1**。
- 唯一的陈旧引用是 **PU-L3-029**（胎儿 MRI 相关问题）：两臂都引用 `[E8]` =
  **MRI 2017 指南**，而 **2023 更新版就在同一上下文内**却未被引用——这正是本批门控
  要抓的真实生成端缺陷。（附带观察：批次九的检索探针里 MRI 链"未被触发"，而这题的
  冻结上下文确实同时含 2017 与 2023 两版——两个探针的"触发面"定义不同，各自如实。）
- **覆盖率限制（诚实记录）**：**72%（36/50）的答案没有给出任何 `[Ei]` 编号**，尽管
  系统提示明确要求引用编号与来源。`no_citations` 不判失败，但会显著削弱该门控的
  观测面：50 题里只有约 14 题可被实际核验。改进方向：强化提示词的引用格式要求，
  或在答案后处理阶段按来源字符串匹配，而非仅依赖 `[Ei]` 编号。

## 6. 对应的 §7 位置与下一步

§7 版本时态至此三层齐备：**结构层（批次八）→ 时点层（批次九）→ 生成端核验（批次十）**。

下一步候选：**embedding 第三通道**（已勘查：B0 投影内含 `vdb_chunks.json` 13.5 MB 等
向量库，通道可直接复用存储向量，仅查询需一次 embedding 调用）；把版本核验接入答案
后处理（自动补引当前版本或标注陈旧）；强化提示词引用格式以提高可核验率；
注册表 `valid_until` 实际填值。

## 7. EVIDENCE 要素（old-coder）

- **SPEC**：批次 10 = 生成端版本一致性核验，沿续跑模式执行。
- **层**：pytest(460) / ruff(0 警) / pyright(0 错) / coverage(fail-under=100 ×7)
  / mutation(38/38) / cache sentinel / real execution(7 探针)
  / 满量 judge 运行(50 题，双臂评分 + 答案持久化 + 版本核验)。
- **工具**：Python 3.12.3、pytest 9.1.1、coverage 7.16.1、hypothesis 6.168.0、
  ruff 0.15.17、pyright 1.1.410。judge 走 `benchmark/.env` 的 OpenAI-compatible
  端点（经本地代理）；运行约 56 分钟。
- **产物**：`benchmark/results/corpus-condition-20260915/b1_end_to_end_ctrl.json`
  （含 50 题答案与两臂 `version_check`）、
  `benchmark/results/corpus-condition-20260915/version_citation_probe.json`、
  `benchmark/results/corpus-condition-20260915/supersedes_probe.json`。
- **环境界定**：会话环境 `NO_PROXY` 含畸形项 `[::1]`（httpx 报
  `Invalid port: ':1]'`），网络运行前需将其修正为 `localhost,127.0.0.1,::1`。
- **源状态**：git HEAD `ac6003b`；改动未提交（沿用历批次约定）。
- **已知局限**：核验只覆盖"对应当前版本同在上下文"的 20 题（另 2 题当前版本不可得，
  不问责）；其余 28 题上下文不含被替代来源，核验恒为 `CONSISTENT`/`NO_CITATIONS`；
  核验依赖模型是否按提示词给出 `[Ei]` 编号（未引用时记为 `NO_CITATIONS`，不判失败）；
  核验不判断答案对旧版的**表述**是否恰当，只判断引用覆盖。
