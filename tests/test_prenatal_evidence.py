"""证据集合选择测试：三值适用性×角色门控 + hypothesis 属性。"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from prenatal_rag.applicability import Applicability
from prenatal_rag.evidence import (
    EvidenceBucket,
    EvidenceCandidate,
    EvidenceRole,
    select_evidence,
)

_ROLES = list(EvidenceRole)


def _c(
    id_: str,
    verdict: Applicability,
    *,
    roles: frozenset[EvidenceRole] = frozenset(),
    anchor: bool = True,
) -> EvidenceCandidate:
    return EvidenceCandidate(id=id_, verdict=verdict, roles=roles, source_anchor=anchor)


_ST_CANDS = st.lists(
    st.builds(
        EvidenceCandidate,
        id=st.integers(min_value=0, max_value=1000).map(str),
        verdict=st.sampled_from(list(Applicability)),
        roles=st.frozensets(
            st.sampled_from(_ROLES), min_size=0, max_size=3
        ),
        source_anchor=st.booleans(),
    ),
    min_size=0,
    max_size=8,
    unique_by=lambda c: c.id,
)
_REQ = st.frozensets(st.sampled_from(_ROLES), min_size=0, max_size=3)
_BUDGET = st.one_of(st.none(), st.integers(min_value=1, max_value=10))


@given(_ST_CANDS, _REQ)
@settings(max_examples=200)
def test_every_candidate_lands_in_exactly_one_bucket(cands, req) -> None:
    sel = select_evidence(cands, required_roles=req)
    placed = sel.primary_support + sel.background + sel.applicability_unknown + sel.comparative
    assert sorted(placed) == sorted(c.id for c in cands)


@given(_ST_CANDS, _REQ)
@settings(max_examples=200)
def test_unknown_and_inapplicable_never_dropped(cands, req) -> None:
    sel = select_evidence(cands, required_roles=req)
    placed = set(sel.primary_support + sel.background + sel.applicability_unknown + sel.comparative)
    for c in cands:
        if c.verdict in (Applicability.UNKNOWN, Applicability.INAPPLICABLE):
            assert c.id in placed


@given(_ST_CANDS, _REQ)
@settings(max_examples=200)
def test_primary_support_only_applicable_role_match_anchored(cands, req) -> None:
    sel = select_evidence(cands, required_roles=req)
    for cid in sel.primary_support:
        c = next(c for c in cands if c.id == cid)
        assert c.verdict is Applicability.APPLICABLE
        assert bool(c.roles & req)
        assert c.source_anchor


@given(_ST_CANDS, _REQ)
@settings(max_examples=200)
def test_unknown_and_inapplicable_never_primary(cands, req) -> None:
    sel = select_evidence(cands, required_roles=req)
    allowed = {c.id for c in cands if c.verdict is Applicability.APPLICABLE}
    assert set(sel.primary_support) <= allowed


@given(_ST_CANDS, _REQ, _BUDGET)
@settings(max_examples=200)
def test_budget_caps_total_and_keeps_prefix(cands, req, budget) -> None:
    sel = select_evidence(cands, required_roles=req, budget=budget)
    if budget is None:
        placed = sum(len(x) for x in [sel.primary_support, sel.background,
                                      sel.applicability_unknown, sel.comparative])
        assert placed == len(cands)
    else:
        placed = sum(len(x) for x in [sel.primary_support, sel.background,
                                      sel.applicability_unknown, sel.comparative])
        assert placed == min(budget, len(cands))


def _buckets_of(sel) -> dict[EvidenceBucket, int]:
    return {
        EvidenceBucket.PRIMARY_SUPPORT: len(sel.primary_support),
        EvidenceBucket.BACKGROUND: len(sel.background),
        EvidenceBucket.APPLICABILITY_UNKNOWN: len(sel.applicability_unknown),
        EvidenceBucket.COMPARATIVE: len(sel.comparative),
    }


def test_applicable_role_match_anchor_is_primary() -> None:
    sel = select_evidence(
        [
            _c("g", Applicability.APPLICABLE, roles=frozenset({EvidenceRole.GUIDELINE}))
        ],
        required_roles=frozenset({EvidenceRole.GUIDELINE}),
    )
    assert sel.primary_support == ["g"]


def test_applicable_role_match_no_anchor_degraded_to_background() -> None:
    sel = select_evidence(
        [
            _c("g", Applicability.APPLICABLE, roles=frozenset({EvidenceRole.GUIDELINE}), anchor=False)
        ],
        required_roles=frozenset({EvidenceRole.GUIDELINE}),
    )
    assert sel.primary_support == []
    assert sel.background == ["g"]


def test_applicable_role_mismatch_to_background() -> None:
    sel = select_evidence(
        [_c("g", Applicability.APPLICABLE, roles=frozenset({EvidenceRole.BACKGROUND}))],
        required_roles=frozenset({EvidenceRole.GUIDELINE}),
    )
    assert sel.background == ["g"] and sel.primary_support == []


def test_unknown_bucketed_not_dropped() -> None:
    sel = select_evidence(
        [_c("u", Applicability.UNKNOWN, roles=frozenset({EvidenceRole.GUIDELINE}))],
        required_roles=frozenset({EvidenceRole.GUIDELINE}),
    )
    assert sel.applicability_unknown == ["u"]
    assert sel.primary_support == []


def test_inapplicable_kept_as_comparative() -> None:
    sel = select_evidence(
        [_c("w", Applicability.INAPPLICABLE, roles=frozenset({EvidenceRole.GUIDELINE}))],
        required_roles=frozenset({EvidenceRole.GUIDELINE}),
    )
    assert sel.comparative == ["w"]
    assert sel.primary_support == []


def test_budget_zero_yields_empty() -> None:
    sel = select_evidence(
        [_c("g", Applicability.APPLICABLE, roles=frozenset({EvidenceRole.GUIDELINE}))],
        required_roles=frozenset({EvidenceRole.GUIDELINE}),
        budget=0,
    )
    assert _buckets_of(sel) == {b: 0 for b in EvidenceBucket}