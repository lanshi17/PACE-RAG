# PACE conditions v1：R2 公开构建框架

状态：2026-10-13，**开发草案和隐藏集配额框架，不是可评测的冻结题集**。
本目录不含真正隐藏的题干或 gold，不直接传入旧 `evaluate --dataset`。

| 文件 | 内容 |
| --- | --- |
| [task_blueprint.json](task_blueprint.json) | 五类任务、规模起点、变体和主终点规划 |
| [dev_families.json](dev_families.json) | 10 家族规划：9 个有三变体草案，1 个真实冲突缺源；共 27 题，全部 gold 为 null |
| [evidence_candidates.json](evidence_candidates.json) | 12 段候选原文及页码、字符区间、来源身份与哈希；医学审核待完成 |
| [hidden_allocation.json](hidden_allocation.json) | 每类 12 个未分配配额位；实际隐藏家族/题目为 0 |
| [legacy_exposure_inventory.json](legacy_exposure_inventory.json) | 历史题库、公开草案和条件变体的文件指纹与 ID 清单 |

每个开发家族保存 task/template/family ID、唯一变动条件、base/condition_change/
invariant_control、候选证据 ID 和待核验行为关系。`proposed_relation` 与
`clinical_review_focus` 都是作者草案，不是 gold；`review_records=[]` 表示未审核。
原文坐标属于原始 corpus 文本，不与 evidence_store 去水印坐标混用。

隐藏配额刻意不指定临床模板、来源或题目。独立保管者在仓库外出题、审查开发模板重叠、
完成双审仲裁并保存私有清单。gitignore 不能提供访问隔离。本轮公开草案永久用于开发，
改写或条件变体不得转入隐藏集。

离线结构检查（仅 Python 标准库）：

```bash
python -m benchmark.pace_research.validate_r2_scaffold
# 本机已有原始 corpus 时，增加文本指纹、页码与摘录定位核验
python -m benchmark.pace_research.validate_r2_scaffold --check-corpus
```

成功仅表示框架与已有产物一致，不代表临床审核或冻结通过。框架规格变更时，需要同步
更新任务配额和文档；测试规模须经功效论证另行冻结，不能靠增加改写实现。

出题、审核、隔离、指标与预算详见
[R2 挑战集框架](../../../../docs/2026-10-13/r2-challenge-framework.md)；
比较对象与贡献边界见
[R2 先例矩阵](../../../../docs/2026-10-13/r2-prior-art-matrix.md)。
