"""指南版本替代（SUPERSEDES）图与证据选择集成测试。"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

from prenatal_rag.applicability import Applicability
from prenatal_rag.evidence import (
    EvidenceCandidate,
    EvidenceRole,
    SupersessionGraph,
    select_evidence,
)

_ROLES = frozenset({EvidenceRole.GUIDELINE})


def _c(
    id_: str,
    *,
    verdict: Applicability = Applicability.APPLICABLE,
    source_id: str = "",
    roles: frozenset[EvidenceRole] = _ROLES,
    anchor: bool = True,
) -> EvidenceCandidate:
    return EvidenceCandidate(
        id=id_, verdict=verdict, roles=roles, source_anchor=anchor, source_id=source_id
    )


# ── SupersessionGraph 语义 ───────────────────────────────────────────────


class TestGraph:
    def test_empty_graph(self) -> None:
        g = SupersessionGraph({})
        assert g.successor("x") is None
        assert g.is_superseded("x") is False
        assert g.chain("x") == ("x",)
        assert g.current_version("x") == "x"
        assert g.depth_to_current("x") == 0
        assert g.superseded_sources() == frozenset()
        assert g.edges == {}

    def test_single_edge(self) -> None:
        g = SupersessionGraph({"old": "new"})
        assert g.successor("old") == "new"
        assert g.successor("new") is None
        assert g.is_superseded("old") is True
        assert g.is_superseded("new") is False
        assert g.chain("old") == ("old", "new")
        assert g.current_version("old") == "new"
        assert g.current_version("new") == "new"
        assert g.depth_to_current("old") == 1
        assert g.depth_to_current("new") == 0
        assert g.superseded_sources() == frozenset({"old"})

    def test_transitive_chain(self) -> None:
        g = SupersessionGraph({"a2006": "a2013", "a2013": "a2023"})
        assert g.chain("a2006") == ("a2006", "a2013", "a2023")
        assert g.chain("a2013") == ("a2013", "a2023")
        assert g.chain("a2023") == ("a2023",)
        assert g.current_version("a2006") == "a2023"
        assert g.depth_to_current("a2006") == 2
        assert g.depth_to_current("a2013") == 1
        assert g.superseded_sources() == frozenset({"a2006", "a2013"})

    def test_unknown_source_is_current(self) -> None:
        g = SupersessionGraph({"old": "new"})
        assert g.chain("unrelated") == ("unrelated",)
        assert g.current_version("unrelated") == "unrelated"
        assert g.depth_to_current("unrelated") == 0

    def test_edges_is_a_copy(self) -> None:
        g = SupersessionGraph({"old": "new"})
        snapshot = g.edges
        snapshot["x"] = "y"  # type: ignore[index]
        assert g.edges == {"old": "new"}

    def test_self_edge_rejected(self) -> None:
        with pytest.raises(ValueError, match="自环"):
            SupersessionGraph({"x": "x"})

    def test_two_node_cycle_rejected(self) -> None:
        with pytest.raises(ValueError, match="替代环"):
            SupersessionGraph({"a": "b", "b": "a"})

    def test_three_node_cycle_rejected(self) -> None:
        with pytest.raises(ValueError, match="替代环"):
            SupersessionGraph({"a": "b", "b": "c", "c": "a"})


# ── 证据选择 × 版本替代集成 ─────────────────────────────────────────────


class TestSelectionSupersession:
    def test_superseded_demoted_to_comparative(self) -> None:
        g = SupersessionGraph({"old": "new"})
        sel = select_evidence(
            [_c("c1", source_id="old")], required_roles=_ROLES, supersession=g
        )
        assert sel.primary_support == []
        assert sel.comparative == ["c1"]

    def test_current_version_can_support(self) -> None:
        g = SupersessionGraph({"old": "new"})
        sel = select_evidence(
            [_c("c1", source_id="new")], required_roles=_ROLES, supersession=g
        )
        assert sel.primary_support == ["c1"]
        assert sel.comparative == []

    def test_without_graph_old_source_still_supports(self) -> None:
        sel = select_evidence([_c("c1", source_id="old")], required_roles=_ROLES)
        assert sel.primary_support == ["c1"]

    def test_unknown_superseded_stays_unknown(self) -> None:
        # "Unknown 永不丢" 优先于版本降级。
        g = SupersessionGraph({"old": "new"})
        sel = select_evidence(
            [_c("c1", verdict=Applicability.UNKNOWN, source_id="old")],
            required_roles=_ROLES,
            supersession=g,
        )
        assert sel.applicability_unknown == ["c1"]
        assert sel.comparative == []

    def test_inapplicable_superseded_stays_comparative(self) -> None:
        g = SupersessionGraph({"old": "new"})
        sel = select_evidence(
            [_c("c1", verdict=Applicability.INAPPLICABLE, source_id="old")],
            required_roles=_ROLES,
            supersession=g,
        )
        assert sel.comparative == ["c1"]

    def test_empty_source_id_not_demoted(self) -> None:
        g = SupersessionGraph({"old": "new"})
        sel = select_evidence(
            [_c("c1", source_id="")], required_roles=_ROLES, supersession=g
        )
        assert sel.primary_support == ["c1"]

    def test_superseded_without_role_match_is_comparative(self) -> None:
        g = SupersessionGraph({"old": "new"})
        sel = select_evidence(
            [_c("c1", source_id="old", roles=frozenset({EvidenceRole.BACKGROUND}))],
            required_roles=_ROLES,
            supersession=g,
        )
        assert sel.comparative == ["c1"]
        assert sel.background == []

    def test_mixed_versions_split_correctly(self) -> None:
        g = SupersessionGraph({"a2006": "a2013", "a2013": "a2023"})
        sel = select_evidence(
            [
                _c("old", source_id="a2006"),
                _c("mid", source_id="a2013"),
                _c("new", source_id="a2023"),
            ],
            required_roles=_ROLES,
            supersession=g,
        )
        assert sel.primary_support == ["new"]
        assert sel.comparative == ["old", "mid"]

    def test_budget_counts_demoted_candidates(self) -> None:
        g = SupersessionGraph({"old": "new"})
        sel = select_evidence(
            [_c("c1", source_id="old"), _c("c2", source_id="new")],
            required_roles=_ROLES,
            budget=1,
            supersession=g,
        )
        assert sel.comparative == ["c1"]
        assert sel.primary_support == []


# ── 生效期/时点语义（as-of） ────────────────────────────────────────────

_CHAIN = {"a2006": "a2013", "a2013": "a2023"}
_YEARS = {"a2006": 2006, "a2013": 2013, "a2023": 2023}


class TestTimeline:
    def test_years_and_valid_until_are_copies(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS, valid_until={"a2006": 2013})
        assert g.years == _YEARS
        assert g.valid_until == {"a2006": 2013}
        g.years["x"] = 1  # type: ignore[index]
        g.valid_until["x"] = 1  # type: ignore[index]
        assert "x" not in g.years
        assert "x" not in g.valid_until

    def test_non_increasing_years_rejected(self) -> None:
        with pytest.raises(ValueError, match="年份非递增"):
            SupersessionGraph({"old": "new"}, years={"old": 2023, "new": 2013})

    def test_equal_years_rejected(self) -> None:
        with pytest.raises(ValueError, match="年份非递增"):
            SupersessionGraph({"old": "new"}, years={"old": 2013, "new": 2013})

    def test_missing_year_skips_increasing_check(self) -> None:
        g = SupersessionGraph({"old": "new"}, years={"old": 2023})
        assert g.publication_year("old") == 2023
        assert g.publication_year("new") is None
        assert g.publication_year("unknown") is None

    def test_is_superseded_at_is_time_indexed(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        assert g.is_superseded_at("a2006", 2012) is False  # 2013 版尚未发布
        assert g.is_superseded_at("a2006", 2013) is True
        assert g.is_superseded_at("a2013", 2016) is False  # 2023 版尚未发布
        assert g.is_superseded_at("a2013", 2024) is True
        assert g.is_superseded_at("a2023", 2024) is False  # 无后继
        assert g.is_superseded_at("unrelated", 2024) is False

    def test_missing_successor_year_is_conservative(self) -> None:
        g = SupersessionGraph({"old": "new"})
        assert g.is_superseded_at("old", 1900) is True

    def test_is_effective_at_uses_year_and_valid_until(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS, valid_until={"a2006": 2013})
        assert g.is_effective_at("a2023", 2016) is False  # 尚未出版
        assert g.is_effective_at("a2023", 2023) is True
        assert g.is_effective_at("a2006", 2012) is True
        assert g.is_effective_at("a2006", 2013) is False  # valid_until 半开区间
        assert g.is_effective_at("unrelated", 2024) is True  # 年份未知不阻塞

    def test_current_version_at_walks_timeline(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        assert g.current_version_at("a2006", 2010) == "a2006"
        assert g.current_version_at("a2006", 2016) == "a2013"
        assert g.current_version_at("a2006", 2024) == "a2023"
        assert g.current_version_at("a2013", 2024) == "a2023"
        assert g.current_version_at("unrelated", 2024) == "unrelated"

    def test_current_version_at_missing_years_treats_as_published(self) -> None:
        g = SupersessionGraph(_CHAIN)
        assert g.current_version_at("a2006", 1900) == "a2023"


class TestSelectionAsOf:
    @staticmethod
    def _candidates() -> list[EvidenceCandidate]:
        return [
            _c("old", source_id="a2006"),
            _c("mid", source_id="a2013"),
            _c("new", source_id="a2023"),
        ]

    def test_as_of_2010_selects_2006(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        sel = select_evidence(
            self._candidates(), required_roles=_ROLES, supersession=g, as_of_year=2010
        )
        assert sel.primary_support == ["old"]
        assert sel.comparative == ["mid", "new"]  # 2013/2023 均尚未出版

    def test_as_of_2016_selects_2013(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        sel = select_evidence(
            self._candidates(), required_roles=_ROLES, supersession=g, as_of_year=2016
        )
        assert sel.primary_support == ["mid"]
        assert sel.comparative == ["old", "new"]

    def test_as_of_2024_selects_2023(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        sel = select_evidence(
            self._candidates(), required_roles=_ROLES, supersession=g, as_of_year=2024
        )
        assert sel.primary_support == ["new"]
        assert sel.comparative == ["old", "mid"]

    def test_structural_mode_ignores_years(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        sel = select_evidence(
            self._candidates(), required_roles=_ROLES, supersession=g
        )
        assert sel.primary_support == ["new"]
        assert sel.comparative == ["old", "mid"]

    def test_valid_until_expires_source(self) -> None:
        g = SupersessionGraph(
            {"s": "t"}, years={"s": 2000, "t": 2030}, valid_until={"s": 2020}
        )
        expired = select_evidence(
            [_c("c", source_id="s")],
            required_roles=_ROLES,
            supersession=g,
            as_of_year=2021,
        )
        assert expired.comparative == ["c"]
        live = select_evidence(
            [_c("c", source_id="s")],
            required_roles=_ROLES,
            supersession=g,
            as_of_year=2019,
        )
        assert live.primary_support == ["c"]

    def test_unknown_still_wins_with_as_of(self) -> None:
        g = SupersessionGraph(_CHAIN, years=_YEARS)
        sel = select_evidence(
            [_c("u", verdict=Applicability.UNKNOWN, source_id="a2006")],
            required_roles=_ROLES,
            supersession=g,
            as_of_year=2024,
        )
        assert sel.applicability_unknown == ["u"]
        assert sel.comparative == []

    def test_as_of_without_supersession_is_noop(self) -> None:
        sel = select_evidence(
            [_c("c", source_id="a2006")], required_roles=_ROLES, as_of_year=2024
        )
        assert sel.primary_support == ["c"]

    def test_as_of_with_unknown_years_demotes(self) -> None:
        g = SupersessionGraph({"old": "new"})
        sel = select_evidence(
            [_c("c", source_id="old")],
            required_roles=_ROLES,
            supersession=g,
            as_of_year=1900,
        )
        assert sel.comparative == ["c"]


# ── hypothesis 属性 ─────────────────────────────────────────────────────

_N = 6


@st.composite
def _acyclic_edges(draw: st.DrawFn) -> dict[str, str]:
    """用置换生成无环边集：仅当 p[i] > i 时连边，索引严格递增 → 无环。"""
    perm = draw(st.permutations(range(_N)))
    return {str(i): str(perm[i]) for i in range(_N) if perm[i] > i}


@given(edges=_acyclic_edges())
@settings(max_examples=100)
def test_chain_properties(edges: dict[str, str]) -> None:
    g = SupersessionGraph(edges)
    for node in [*edges, *(str(i) for i in range(_N))]:
        chain = g.chain(node)
        assert chain[0] == node
        assert g.current_version(node) == chain[-1]
        assert g.depth_to_current(node) == len(chain) - 1
        # 当前版本不再被替代；链中每个节点指向下一个。
        assert not g.is_superseded(chain[-1])
        for older, newer in zip(chain, chain[1:], strict=False):
            assert g.successor(older) == newer


@given(edges=_acyclic_edges())
@settings(max_examples=100)
def test_superseded_never_primary_support(edges: dict[str, str]) -> None:
    g = SupersessionGraph(edges)
    candidates = [_c(f"c{i}", source_id=s) for i, s in enumerate(g.superseded_sources())]
    if not candidates:
        candidates = [_c("c0", source_id="none")]
    sel = select_evidence(candidates, required_roles=_ROLES, supersession=g)
    for cid in sel.primary_support:
        src = next(c.source_id for c in candidates if c.id == cid)
        assert not g.is_superseded(src)


@given(edges=_acyclic_edges(), year=st.integers(min_value=0, max_value=_N + 1))
@settings(max_examples=100)
def test_current_version_at_is_time_consistent(
    edges: dict[str, str], year: int
) -> None:
    """时点当前版本：在 year 前已出版、且在该时点未被替代。"""
    years = {n: int(n) for n in set(edges) | set(edges.values())}
    g = SupersessionGraph(edges, years=years)
    for node in [*edges, *(str(i) for i in range(_N))]:
        current = g.current_version_at(node, year)
        if current != node:
            published = g.publication_year(current)
            assert published is None or published <= year
        assert g.is_superseded_at(current, year) is False
