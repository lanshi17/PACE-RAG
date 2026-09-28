"""PACE：产前超声条件化证据检索与可核验生成（研究包）。

设计文档：docs/2026-09-12/prenatal-ace-framework.md（主文档）及同日续记。

子包：
- evidence_store: 证据真值层（SQLite 原型：来源身份、页/span 锚点、chunk 文本）。
  LightRAG 图与向量库是可重建投影；span 级锚点只能由本层承担（续记 §1#5）。
- applicability: 孕周以天解析与三值适用性判断（主文档 §4.2）。
- retrieval: BM25 召回通道（主文档 §5.1；各通道只输出排名，由上层 RRF 合并）。
- conditions: chunk 级条件抽取、GaWindow 窗口、三值分类与 B1 显式过滤
  （主文档 §4.1/§4.2/§5.1；batch 文档 §5.4 的条件抽取项）。

本包刻意不依赖 benchmark.*：评测适配在 benchmark/baseline/prenatal_rag_client/
另行接入，包本身保持可独立发布与复现。
"""

from __future__ import annotations
