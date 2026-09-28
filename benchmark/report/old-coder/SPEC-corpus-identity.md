# SPEC — 语料身份层（DOI 家族去重）追溯审查

- Tier: **2**（正常变更；但因去重与孤儿清理具备"删错文件 = 证据数据丢失"的失败模式，附加一个小型失败模型：错误归并丢内容 / 误删保留文本 / DOI 抽取被页内引用污染 / 陈旧文件复活。每种模式对应一个变异体或集成测试。）
- 性质说明：本 SPEC 为**追溯性**文件——实现已于 2026-09-12 落地（commit ac6003b 之后的未提交改动），本次按 old-coder 流程补齐规约与证据。代码已存在，故 RED 阶段以"变异证明测试可失败"代替"先看失败"。
- Spec approval: **not obtained (autonomous run)** — 用户指令为"用 old-coder 检查代码"，是对审查的授权而非对本 SPEC 的批准；置信度按规则降级，SPEC 是事后审查物。

## Setup plan
- Tools to install: 无（项目依赖不变）。gauntlet 以 `uv run --with <tool>` 临时叠加：`pytest-cov`（变更行覆盖率门）、`hypothesis`（DOI 解析性质测试）、`pytest-randomly`（套件顺序随机化）、`mypy`（静态类型层；项目类型检查此前依赖会话内 Pyright）——均为工具层，不写入 pyproject。
- Git: **不做任何提交**（用户未授权提交；批次 1 改动保持未提交状态）。源状态以 `source_state.sh` 记录（HEAD SHA + 脏标志 + 变更文件 sha256）。
- Files the gauntlet will add, by path:
  - `benchmark/report/old-coder/SPEC-corpus-identity.md`（本文件）
  - `benchmark/report/old-coder/EVIDENCE-corpus-identity.md`
  - `benchmark/report/old-coder/mutation_corpus_identity.py`（变异层，持久化、可复跑、fail-closed）
  - `benchmark/report/old-coder/check_changed_coverage.py`（变更行覆盖门，fail-closed）
  - `benchmark/report/old-coder/property_doi.py`（性质层）
  - `benchmark/report/old-coder/gauntlet.sh`（唯一入口，逐层显式处理退出码）
  - `benchmark/report/old-coder/source_state.sh`
- New dependencies: 无（见上，工具均为运行期临时叠加）。

## Scenarios

```gherkin
Feature: 语料身份解析与 DOI 家族去重（benchmark/common/corpus.py, unified_corpus.py）

  Scenario: B1 长名同文映射到家族 ID
    Given 文件名 ISUOG-Practice-Guidelines-routine-mid-trimester-fetal-ultrasound.pdf
    When  canonical_source_id 解析
    Then  返回 "ISUOG-midtrimester-2022"；intrapartum/biometry/invasive 三个长名同理

  Scenario: B2 错名 ISPD 文件更正
    Given 文件名 ISPD_2023_genome-wide-sequencing-position.pdf
    When  canonical_source_id 解析
    Then  返回 "ISPD-nipt-2023"，且该文件名存在于 KNOWN_SOURCE_ISSUES

  Scenario: B3 页首 DOI 抽取
    Given 语料格式文本（SOURCE_ID 头 + "## Page 1" 标记）
    When  extract_page1_doi 运行
    Then  页 1 的 "DOI: 10.1002/uog.24888" → "10.1002/uog.24888"；
          仅出现在页 2 的 DOI → None；无 DOI → None；尾部句点被剥离

  Scenario: B4 同家族去重决策（plan_family_duplicates）
    Given 同 source_id、同 page1_doi、不同 hash 的两条 ok 记录（80k/61k 字符）
    When  plan_family_duplicates 运行
    Then  恰好 1 条 drop：较小者，duplicate_of=较大者，duplicate_reason="same-page1-doi"，
          input_file 指向保留者的文本；warnings 为空
    And   同 source_id 但 page1_doi 分歧 → 0 drop 且产生 1 条 (source_id, 警告) 元组
    And   多副本组中存在 page1_doi=None → 0 drop 且警告
    And   status 为 duplicate/error 的记录永不成为候选
    And   字符数并列时按 pdf_file 字典序保留

  Scenario: S6 端到端同文归并（prepare_corpus，真实文本层 PDF）
    Given 临时 raw 目录含已知家族的两个文件名，页 1 同印 "DOI: 10.1002/uog.24888"，
          第一个文件正文更长
    When  prepare_corpus 运行
    Then  indexed_document_count==1 且 duplicate_count==1；duplicate 记录
          duplicate_reason=="same-page1-doi" 且 duplicate_of 为正文更长者；
          input/ 目录恰好 1 个 txt，且其 SOURCE_ID 头为家族 ID

  Scenario: S7 孤儿文本清理（数据丢失模式的反向护栏）
    Given 已生成的语料目录，input/ 中手工放入 stale--deadbeef.txt
    When  prepare_corpus 再次运行
    Then  stale--deadbeef.txt 被删除，且 manifest 引用的每个 txt 仍存在

  Scenario: S8 已知问题警告注入
    Given raw 目录含 ISPD_2023_genome-wide-sequencing-position.pdf（文本层，页 1 印
          DOI 10.1002/pd.6357）
    When  prepare_corpus 运行
    Then  该文档 source_id=="ISPD-nipt-2023"，warnings 包含 KNOWN_SOURCE_ISSUES 中的原文

  Scenario: S9 DOI 分歧不合并（端到端）
    Given CNS-part1 家族两个文件名，页 1 分别印 DOI A 与 DOI B（A≠B）
    When  prepare_corpus 运行
    Then  两份均 indexed，且两条记录的 warnings 均包含含 "page1_doi" 的归并警告
```

## Must NOT
- 全量既有测试套件保持全绿（零回归）；新增依赖进入 pyproject = 违规。
- 保留文本内容不变（重跑为确定性再抽取；kept txt 文件名含 pdf sha256，字节级稳定）。
- 既有 manifest 消费方（`source_coverage`、各 baseline 的 `load_corpus_manifest`、`benchmark_protocol._corpus_fingerprint`）不受新字段影响（全部 `.get()` 访问，既有测试覆盖）。
- 变异层不得触碰 `benchmark/baseline/libs/`（vendored 第三方）与两个研究探针脚本（`corpus_diff_probe.py`、`condition_density_probe.py`——研究工具， assurance boundary 之外，仅纳入 lint/类型层）。
- 孤儿清理只允许删除 `input/*.txt` 中 manifest 未引用者；不得触碰 raw/。

## Mutation plan（手动变异，工具不可用；持久化于 mutation_corpus_identity.py）
| # | 文件 | 变异（唯一字符串替换，应用次数必须==1） | 预期杀死者 |
|---|---|---|---|
| M1 | unified_corpus.py | 排序键 `-record["text_characters"]` → `record["text_characters"]`（保留较小副本） | B4 同 DOI 用例 + 并列决胜用例 |
| M2 | unified_corpus.py | `by_doi.setdefault(doi, ...)` → `by_doi.setdefault(source_id, ...)`（无视 DOI） | B4 分歧用例 + None 用例 |
| M3 | unified_corpus.py | 候选过滤 `{"ok", "partial"}` → `{"ok", "partial", "duplicate"}` | B4 候选排除用例 |
| M4 | corpus.py | `DOI_RE.search(page1)` → `DOI_RE.search(text)`（全文搜索） | B3 "页 2 DOI 忽略"用例 |
| M5 | corpus.py | `rstrip(".")` 删除 | B3 尾句点用例 |
| M6 | unified_corpus.py | 孤儿判断 `not in` → `in`（删保留文本，数据丢失模式） | S7 保留文件存在断言 |

运行器必须证明每个变异体真被执行：应用前断言替换计数==1；每次运行前删除相关 `__pycache__`；记录被测文件的 mtime 与内容哈希，pytest 结束后与原始哈希比对确认恢复。

## Revisions
- 2026-09-14 初版（追溯建立；实现先于 SPEC 存在，见性质说明）。

## Revisions（续）
- 2026-09-14 gauntlet 过程记录：S7 集成测试首次运行即红——`pruned_text_count` 把同轮内"重提取后因去重丢弃"的副本也计入孤儿数（重跑时计数 2 而非 1）。判定为实现语义缺陷（SPEC S7 语义不变、测试未改），实现修正为"仅统计运行前已存在的孤儿"，单步验证后转绿。
- 2026-09-14 场景补充（追溯）：S10 字节级同文归并（identical-bytes 分支此前无测试，覆盖门据此拦截）；S11 缺失/空 raw 目录错误契约；S12 `dataset_path` 分支（惰性导入 + `source_coverage` 集成）；B3b 无页标记时的前 6000 字符回退。
- 2026-09-14 变异层负对照 C0（行为保持的 docstring 变异，必须存活）：C0 v1 的 old/new 写成相同字符串，被运行器的字节变化断言以 pattern-error 拦截——运行器 fail-closed 生效；修正后 C0 存活、6/6 真实变异体全部被杀。
- 2026-09-14 覆盖门负对照：向 `plan_family_duplicates` 行 59 注入伪造缺失行，门以 exit 1 精确报告后通过。
- 2026-09-14 修复优化轮（用户指令"进行修复优化"授权）：F1 修复 3 个既有 mypy 错误（usage.py 的 None 收窄改海象表达式；annotation_agreement.py 的 int→float 除法重写，数学等价）——修复后类型层恢复全量跟随导入（移除 --follow-imports=silent，更强的层）；F2 pyproject 增 `[tool.pyright]` venv 配置，Pyright 对 pypdf 的解析错误消除；F3 分支 286->283 单边问题以新测试 test_family_warning_skips_duplicate_records 补出真实 False 路径；O1 prepare_corpus 两阶段化——被去重丢弃的副本不再落盘（先内存暂存 body，去重后仅物化保留文本），消除"先写后删"抖动；O2 新增性质脚本 property_plan_family.py（I1–I5 五条不变量，300 例）接入 gauntlet。全部修正后 gauntlet 全层通过。
