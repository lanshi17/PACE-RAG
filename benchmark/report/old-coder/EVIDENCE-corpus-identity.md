# EVIDENCE — 语料身份层（DOI 家族去重）审查＋修复优化轮

- Tier: 2（附加数据丢失失败模型）
- Spec approval: **not obtained (autonomous run)** — 追溯审查＋用户指令授权的修复优化轮；SPEC 为事后审查物，置信度按规则降级。
- Source state: HEAD `ac6003b1cc9c32fcdf490061ef24a47790dbed87`，工作树含未提交改动；逐文件 sha256 由 `bash benchmark/report/old-coder/source_state.sh` 输出（运行时取值，文件清单见 SPEC setup plan）。未提交 git：用户未授权写操作。
- Toolchain: python 3.12.3；pytest 9.1.1；pytest-cov 7.1.0；hypothesis 6.168.0；pytest-randomly 5.0.0；mypy 2.3.1。gauntlet 工具经 `uv run --with` 临时叠加，不写入 pyproject。
- Entry point: `bash benchmark/report/old-coder/gauntlet.sh`。
- Independent verification: **not performed**（Tier 2，声明式降级）。

## Spec → Test mapping

| Scenario | Test | Status |
|---|---|---|
| B1 长名映射家族 ID | tests/test_common_corpus.py::TestCanonicalSourceIdFamilies::test_same_article_long_names_map_to_family_ids | pass |
| B2 错名 ISPD 更正 | …::test_mislabeled_ispd_pdf_resolves_to_nipt_id | pass |
| B3 页首 DOI 抽取（含 B3b 无标记回退） | …::TestExtractPage1Doi（5 例） | pass |
| B4 同家族去重决策 | tests/test_common_unified_corpus.py::TestPlanFamilyDuplicates（5 例） | pass |
| S6 端到端同文归并 | …::TestPrepareCorpusIdentity::test_same_doi_copies_collapse_end_to_end | pass |
| S7 孤儿清理＋保留文件存在 | …::test_stale_orphan_text_is_pruned | pass（首跑红灯→真实缺陷修复） |
| S8 已知问题警告注入 | …::test_known_source_issue_warning_is_injected | pass |
| S9 DOI 分歧不合并 | …::test_diverging_dois_are_kept_with_warning | pass |
| S10 字节级同文归并 | …::test_byte_identical_pair_collapses_with_reason | pass |
| S11 错误契约（缺/空 raw 目录） | …::test_missing_raw_dir_raises、test_empty_raw_dir_raises | pass |
| S12 dataset_path 分支 | …::test_dataset_path_branch_builds_source_coverage | pass |
| S13 警告不污染 duplicate 记录（修复优化轮 F3） | …::test_family_warning_skips_duplicate_records | pass |
| Must NOT: 既有套件零回归 | tests 层 | pass |
| Must NOT: 无新项目依赖 | supply chain：pyproject 仅增 `[tool.pyright]` 解释器配置（F2，非依赖）；dirty 清单核对 | pass |
| Must NOT: 保留文本稳定 | real-execution 层 | pass |
| Must NOT: manifest 消费方不受影响 | 既有 tests ＋全量套件 | pass |
| Must NOT: 变异不触碰 vendored/探针 | mutation_corpus_identity.py 变异表审计 | pass |

## Gauntlet（修复优化轮后的最终全新运行）

| Layer | Command | Result |
|---|---|---|
| Tests | `uv run pytest -q` | **157 passed, 0 failed**（含 38 个语料层用例） |
| Coverage run | `uv run --with pytest-cov pytest tests/test_common_{corpus,unified_corpus}.py --cov=benchmark.common --cov-branch --cov-report=term-missing --cov-report=json:coverage.json` | 38 passed；corpus.py 95%（106-108 非目标函数）；unified_corpus.py 98%（行 55 非目标） |
| Changed-line coverage gate | `check_changed_coverage.py coverage.json` | 4/4 目标函数零缺失行 |
| Types | `uv run --with mypy mypy --ignore-missing-imports benchmark/common/{corpus,unified_corpus}.py` | 0 errors——**全量跟随导入**（修复优化轮 F1 后移除 silent 降级，层强于上一轮） |
| Lint | `uv run ruff check <变更文件＋old-coder>` | All checks passed |
| Property (DOI) | `property_doi.py` | 4/4 properties（P1/P2/P3 各 150 例、P4 200 例） |
| Property (plan_family，O2 新增) | `property_plan_family.py` | I1–I5 不变量 300 例全持 |
| Mutation | `mutation_corpus_identity.py` | manual mutation: **6/6 killed**（唯一模式断言＋字节差断言＋__pycache__ 清理＋恢复校验） |
| Real execution | `real_execution_check.py` | 真实 33-PDF：26 indexed / 7 duplicates / 0 errors / pruned 0 / 26 txt |
| Supply chain | 能力差核查 | F2 仅新增编辑器配置；O1 删除"落盘后清理"抖动（能力收敛而非扩张）；无新增网络/子进程/env |
| Suite health | `--with pytest-randomly pytest -q -p randomly --randomly-seed=20260914` | 随机顺序 157 passed |

GAUNTLET PASS — 层清单审计：tests coverage-run coverage-gate types lint property(×2) mutation real-execution suite-health。

## Independent verification (never omit)

- Verifier: 无（未运行）；协议文件未读未执行 → 记 `not performed`，非 `passed`。
- Rounds: 0（上限 2）；Attacked：由 6 个手动变异体（含数据丢失模式 M6）＋对抗用例（S7 孤儿、S9 分歧、S13 警告隔离）部分替代——是替代，不是独立验证。

## Layers not run as specified

- **N-A**: dependency audit / license check（依赖集零变更）。
- **SUBSTITUTED**: secret scan（人工检查差异文件；非 gitleaks 全模式扫描）。

## Dismissed review findings

- 无——两轮发现全部修复或转入性质层/盲区清单。

## Structural blind spot

- 真实世界畸形/扫描 PDF 的健壮性无证据（测试仅用两类手工文本层 PDF）。
- 孤儿清理的文件系统失败路径（权限/只读）无测试——`unlink` 异常将使 prepare_corpus 在写 manifest 前中断（fail-closed，但无测试钉住）。
- 性质层覆盖 DOI 解析与去重决策；prepare_corpus 的 IO 编排仍以集成用例＋变异体保护。

## Honest notes

- gauntlet 在本任务中抓到并修复的真实缺陷共 2 处：① S7 首跑红——`pruned_text_count` 把同轮重提取后丢弃的副本计入孤儿数（重跑 2≠1），修正为"仅统计运行前已存在的孤儿"；② 首次完整运行失败于 types-mypy——3 个既有错误位于未触碰文件（`qa/annotation_agreement.py:116`、`common/usage.py:41`×2），首按 baseline 规则以 `--follow-imports=silent` 限定层作用域，修复优化轮经用户授权后真正修复（海象表达式收窄＋等价除法重写），类型层恢复全量跟随导入。
- 过程性缺陷（均被机制自身拦截）：变异负对照 C0 v1 old/new 相同字符串被字节差断言拦下；本会话编辑工具 4 次行号错位（2 次造成语法损坏，均经重读修复并全量验证）。
- Pyright 对 corpus.py 的 `pypdf` 导入错误为解释器未指向 `.venv` 的环境问题，修复优化轮以 `[tool.pyright]` venv 配置消除（LSP diagnostics: OK）。
- 分支 286->283 曾为结构性单边；F3 测试补出真实 False 路径（duplicate 记录存在于警告源组）后，该分支两侧均被测试执行。
- spec approval 未获得（自主运行）；本报告与 SPEC 为事后审查物。
