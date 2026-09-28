"""指南版本时态：结构替代图 + 生效期时间轴（确定性、无 LLM、无网络）。

PACE 主文档的"版本时态"有两层含义，本模块同时承载：

**结构层（SUPERSEDES）**：同一指南多版本（如 ISUOG 心脏筛查
2006 → 2013 → 2023）共存时，被替代版本不得承担直接支持，只能作版本比较
材料（``comparative``）：

- 边 ``older -> newer``（immediately superseding）；
- ``chain(s)`` 返回 ``[s, 后继, ..., 当前版本]``；``current_version(s)`` 为链尾；
  ``depth_to_current(s)`` 为距当前版本跳数（当前版本 0，越旧越大）；
- 构造期校验自环与替代环，非法输入抛 ``ValueError``（fail-closed）。

**时间层（生效期 / valid_until）**：版本知识带**出版年份**，于是"替代"变成
**时点相关**的事实——2016 年时 2013 版才是当前版本（2006 已废、2023 未发布）。
另可给出来源自身的 ``valid_until``（失效年，``[生效年, 失效年)`` 半开区间）：

- ``publication_year(s)``：出版年；未知返回 ``None``；
- ``is_effective_at(s, y)``：``y`` 时点该来源是否已生效且未失效；
- ``is_superseded_at(s, y)``：后继版本是否已在 ``y`` 时点发布；
- ``current_version_at(s, y)``：``y`` 时点该链的当前版本。

**fail-safe 口径**（不丢证据、只降级）：出版年未知时，``is_superseded_at``
按"已替代"处理（保守降级为比较材料），``is_effective_at`` 按"已生效"处理
（不因年份缺失而阻塞）。``select_evidence`` 中无论如何都只改变证据所在桶，
绝不丢弃。

本模块只承载**关系与时点语义**；边与年份从何处来（证据真值层的 DOI 关联、
指南注册表）由调用方注入，``prenatal_rag`` 不依赖 ``benchmark.*``。
"""

from __future__ import annotations

from collections.abc import Mapping


class SupersessionGraph:
    """指南版本替代图 + 生效期时间轴（确定性、无副作用）。"""

    def __init__(
        self,
        edges: Mapping[str, str],
        *,
        years: Mapping[str, int] | None = None,
        valid_until: Mapping[str, int] | None = None,
    ) -> None:
        self._edges: dict[str, str] = dict(edges)
        self._years: dict[str, int] = dict(years) if years else {}
        self._valid_until: dict[str, int] = dict(valid_until) if valid_until else {}
        self._validate()
        self._validate_timeline()

    def _validate(self) -> None:
        for older, newer in self._edges.items():
            if older == newer:
                raise ValueError(f"自环：{older!r} 被自身替代")
        # 环检测：从每个起点走链，若在当前链内重访则成环。
        for start in self._edges:
            seen: set[str] = set()
            node: str | None = start
            while node is not None:
                if node in seen:
                    raise ValueError(f"检测到替代环，起点 {start!r}")
                seen.add(node)
                node = self._edges.get(node)

    def _validate_timeline(self) -> None:
        """替代边的年份必须严格递增（后一版本晚于前一版本）。"""
        for older, newer in self._edges.items():
            older_year = self._years.get(older)
            newer_year = self._years.get(newer)
            if older_year is None or newer_year is None:
                continue
            if newer_year <= older_year:
                raise ValueError(
                    f"版本年份非递增：{older!r}({older_year}) -> {newer!r}({newer_year})"
                )

    @property
    def edges(self) -> Mapping[str, str]:
        """返回 ``older -> newer`` 的只读视图副本。"""
        return dict(self._edges)

    @property
    def years(self) -> Mapping[str, int]:
        """返回 ``source_id -> 出版年`` 的只读视图副本。"""
        return dict(self._years)

    @property
    def valid_until(self) -> Mapping[str, int]:
        """返回 ``source_id -> 失效年`` 的只读视图副本。"""
        return dict(self._valid_until)

    def successor(self, source_id: str) -> str | None:
        """直接替代该来源的更新版本；无则 ``None``。"""
        return self._edges.get(source_id)

    def is_superseded(self, source_id: str) -> bool:
        """该来源是否已被更新版本替代（结构层，忽略时点）。"""
        return source_id in self._edges

    def chain(self, source_id: str) -> tuple[str, ...]:
        """``[source_id, 后继, ..., 当前版本]``；未知来源返回单元素元组。"""
        out: list[str] = [source_id]
        node = self._edges.get(source_id)
        while node is not None:
            out.append(node)
            node = self._edges.get(node)
        return tuple(out)

    def current_version(self, source_id: str) -> str:
        """该来源所在替代链的当前（最新）版本（结构层，忽略时点）。"""
        return self.chain(source_id)[-1]

    def depth_to_current(self, source_id: str) -> int:
        """距当前版本的跳数：当前版本 0，被替代一层 1，依此类推。"""
        return len(self.chain(source_id)) - 1

    def superseded_sources(self) -> frozenset[str]:
        """所有已被替代的来源集合。"""
        return frozenset(self._edges)

    def publication_year(self, source_id: str) -> int | None:
        """该来源的出版年；未知返回 ``None``。"""
        return self._years.get(source_id)

    def is_superseded_at(self, source_id: str, year: int) -> bool:
        """``year`` 时点，替代该来源的版本是否已发布。

        后继版本出版年未知时按 **已替代** 处理（保守降级，不丢证据）。
        """
        successor = self._edges.get(source_id)
        if successor is None:
            return False
        successor_year = self._years.get(successor)
        if successor_year is None:
            return True
        return year >= successor_year

    def is_effective_at(self, source_id: str, year: int) -> bool:
        """``year`` 时点该来源是否已生效（出版）且未失效（``valid_until``）。

        年份未知时按 **已生效** 处理（不因缺失信息阻塞证据）。
        失效语义为半开区间 ``[生效年, 失效年)``：``year >= valid_until`` 即失效。
        """
        end = self._valid_until.get(source_id)
        if end is not None and year >= end:
            return False
        start = self._years.get(source_id)
        return start is None or year >= start

    def current_version_at(self, source_id: str, year: int) -> str:
        """``year`` 时点该替代链的当前版本。

        沿后继前进，直到后继尚未发布（无后继视为永久当前）；后继出版年未知
        时视为已发布（与 ``is_superseded_at`` 同一保守口径）。

        注意：只能沿后继**向前**走，故当查询起点自身在 ``year`` 时点尚未出版
        时返回起点本身（链上不存在可回退的更早版本）；调用方应另以
        ``is_effective_at`` 判定其是否生效。
        """
        node = source_id
        while True:
            successor = self._edges.get(node)
            if successor is None:
                return node
            successor_year = self._years.get(successor)
            if successor_year is not None and successor_year > year:
                return node
            node = successor


__all__ = ["SupersessionGraph"]
