"""Official matcher conventions (fintech-checks.txt): exact ids/type/currency, integer amounts,
evidence sets, structural limits, tau, maximum matching and the deterministic tie-break."""

from __future__ import annotations

import itertools

import pytest
from pydantic import ValidationError

from ophanim.evaluator.judge import validate_submission
from ophanim.evaluator.matcher import check_tolerance, eligibility, match
from ophanim.rng import DeterministicRng
from ophanim.schemas import Finding, TruthFile, TruthIssue

U = frozenset({"R1", "R2", "R3", "D1", "D2", "D3", "GL-1", "2026-01-05:EUR:USD"})
EID = "EP-1"


def issue(iid="A", ids=("R1", "R2"), amount=10000, sets=(("D1", "D2"),), type_="duplicate_invoice", cur="KZT"):
    return TruthIssue(issue_id=iid, type=type_, affected_ids=list(ids), expected_amount_minor=amount, currency=cur,
                      allowed_evidence_sets=[list(s) for s in sets])


def raw(ids=("R1", "R2"), amount=10000, cur="KZT", ev=("D1", "D2"), type_="duplicate_invoice", text="short"):
    return {"type": type_, "affected_ids": list(ids), "claimed_amount_minor": amount, "currency": cur,
            "evidence_ids": list(ev), "explanation": text}


def F(**kw) -> Finding:
    return Finding.model_validate(raw(**kw))


def ok(f: Finding, t: TruthIssue = None, tol: int = 0) -> bool:
    return eligibility(f, t or issue(), U, tol) == []


# ----------------------------------------------------------------------------- ids
def test_exact_id_match_and_set_semantics():
    assert ok(F(ids=("R1", "R2"))) and ok(F(ids=("R2", "R1", "R1")))       # M01: order and repeats ignored
    assert not ok(F(ids=("R1", "R2", "R3")))                                # M02: extra id
    assert not ok(F(ids=("R1",)))                                          # missing id


@pytest.mark.parametrize("variant", ["r1", " R1", "R1 ", "R1\t", "R1​"])
def test_id_variants_never_match(variant):
    assert not ok(F(ids=(variant, "R2")))
    assert "evidence_unknown_id" in eligibility(F(ev=(variant, "D1", "D2")), issue(), U, 0)


def test_numeric_id_is_a_type_error_not_a_string():
    sub, errors = validate_submission({"episode_id": EID, "findings": [dict(raw(), affected_ids=[1, "R2"])]}, EID)
    assert sub is None and errors
    sub, errors = validate_submission({"episode_id": EID, "findings": [dict(raw(), evidence_ids=["D1", 2])]}, EID)
    assert sub is None


def test_episode_id_is_exact():
    assert validate_submission({"episode_id": EID, "findings": []}, EID)[0] is not None
    for wrong in ("ep-1", " EP-1", "EP-1 "):
        assert validate_submission({"episode_id": wrong, "findings": []}, EID)[0] is None


# ----------------------------------------------------------------------------- currency and type
@pytest.mark.parametrize("cur,matches", [("KZT", True), ("kzt", False), (" KZT", False), ("KZT ", False), ("USD", False),
                                         ("₸", False), ("", False)])
def test_currency_is_compared_exactly_and_never_a_structure_error(cur, matches):
    f = F(cur=cur)                                                          # structurally valid for any string
    assert ok(f) is matches


@pytest.mark.parametrize("type_,matches", [("duplicate_invoice", True), ("DUPLICATE_INVOICE", False),
                                           (" duplicate_invoice", False), ("duplicate", False), ("fraud", False),
                                           ("fx_rate", False), ("", False)])
def test_type_is_compared_exactly_without_aliases(type_, matches):
    assert ok(F(type_=type_)) is matches


# ----------------------------------------------------------------------------- amount
def test_amount_semantics():
    assert ok(F(amount=10000)) and not ok(F(amount=10001)) and not ok(F(amount=9999))
    assert not ok(F(amount=-10000))                                         # negative: valid structure, no match
    assert not ok(F(amount=10**40))                                         # huge int: valid structure, no match


@pytest.mark.parametrize("bad", [True, False, "10000", 10000.0, 1e4, None, [10000], {"v": 10000}])
def test_amount_must_be_a_json_integer(bad):
    sub, _ = validate_submission({"episode_id": EID, "findings": [raw(amount=bad)]}, EID)
    assert sub is None


# ----------------------------------------------------------------------------- evidence
def test_evidence_rules():
    assert ok(F(ev=("D1", "D2")))                                           # complete allowed set
    assert ok(F(ev=("D2", "D1", "D3")))                                     # M03: extra existing id allowed
    assert ok(F(ev=("D1", "D2", "D1", "D2")))                               # repeats do not matter
    assert eligibility(F(ev=("D1",)), issue(), U, 0) == ["evidence_insufficient"]      # incomplete
    assert eligibility(F(ev=("D1", "D2", "NOPE")), issue(), U, 0) == ["evidence_unknown_id"]  # M04
    assert eligibility(F(ev=("D3",)), issue(), U, 0) == ["evidence_insufficient"]      # one valid id is not enough
    t = issue(sets=(("D1", "D2"), ("GL-1", "2026-01-05:EUR:USD")))         # any complete set suffices
    assert ok(F(ev=("GL-1", "2026-01-05:EUR:USD")), t) and not ok(F(ev=("D1", "GL-1")), t)


def test_inaccessible_evidence_does_not_match():
    universe = U | {"ENTITY-INTERNAL"}                                      # exists in the data model...
    accessible = U                                                          # ...but no tool returns it
    f = F(ev=("D1", "D2", "ENTITY-INTERNAL"))
    assert eligibility(f, issue(), accessible, 0) == ["evidence_unknown_id"]
    assert eligibility(f, issue(), universe, 0) == []


# ----------------------------------------------------------------------------- structure and limits
def sub_with(findings):
    return {"episode_id": EID, "findings": findings}


def test_limits_on_raw_lists_before_set_conversion():
    assert validate_submission(sub_with([raw()] * 30), EID)[0] is not None
    assert validate_submission(sub_with([raw()] * 31), EID)[0] is None
    assert validate_submission(sub_with([raw(ev=tuple(f"E{i}" for i in range(10)))]), EID)[0] is not None
    assert validate_submission(sub_with([raw(ev=tuple(f"E{i}" for i in range(11)))]), EID)[0] is None
    assert validate_submission(sub_with([raw(ev=("D1",) * 10 + ("D2",))]), EID)[0] is None          # M05


@pytest.mark.parametrize("ch", ["x", "ж", "₸", "𝄞"])                     # 1, 2, 3 and 4 UTF-8 bytes
def test_explanation_limit_counts_unicode_code_points(ch):
    assert validate_submission(sub_with([raw(text=ch * 1000)]), EID)[0] is not None
    assert validate_submission(sub_with([raw(text=ch * 1001)]), EID)[0] is None


@pytest.mark.parametrize("mutate", [
    lambda f: {k: v for k, v in f.items() if k != "evidence_ids"},       # missing field
    lambda f: dict(f, affected_ids="R1"),                                  # wrong type
    lambda f: dict(f, type=1),                                             # wrong type
    lambda f: dict(f, currency=None),                                      # wrong type
    lambda f: dict(f, explanation=5),                                      # wrong type
    lambda f: dict(f, confidence=0.9),                                     # unknown field (O1)
])
def test_structure_errors(mutate):
    assert validate_submission(sub_with([mutate(raw())]), EID)[0] is None


@pytest.mark.parametrize("payload", [[], "x", None, {"findings": []}, {"episode_id": EID}, {"episode_id": EID, "findings": {}}])
def test_malformed_top_level(payload):
    assert validate_submission(payload, EID)[0] is None


@pytest.mark.parametrize("mutate", [
    lambda f: dict(f, affected_ids=[]), lambda f: dict(f, affected_ids=[f"R{i}" for i in range(50)]),
    lambda f: dict(f, affected_ids=["X" * 500]), lambda f: dict(f, type="fraud"), lambda f: dict(f, currency="kzt"),
    lambda f: dict(f, claimed_amount_minor=-1), lambda f: dict(f, evidence_ids=[]),
])
def test_semantic_mismatches_are_structurally_valid(mutate):
    sub, errors = validate_submission(sub_with([mutate(raw())]), EID)
    assert sub is not None and errors == []
    assert match(sub.findings, [issue()], U, 0).tp == 0


# ----------------------------------------------------------------------------- tolerance
def test_default_tolerance_is_zero():
    t = TruthFile(schema_version="1.0", episode_id=EID, base_currency="KZT", issues=[])
    assert t.tolerance_minor == 0
    from ophanim.generator.presentation import TOLERANCE_MINOR
    assert TOLERANCE_MINOR == 0


@pytest.mark.parametrize("bad", [-1, True, "1", 1.0, None])
def test_invalid_tolerance_configuration_is_rejected(bad):
    with pytest.raises(ValidationError):
        TruthFile(schema_version="1.0", episode_id=EID, base_currency="KZT", tolerance_minor=bad, issues=[])
    with pytest.raises(ValueError):
        match([], [], U, bad)
    with pytest.raises(ValueError):
        check_tolerance(bad)


def test_tolerance_boundaries():
    t = issue()
    for tol, inside, outside in ((0, (0,), (1, -1)), (1, (0, 1, -1), (2, -2)), (5, (5, -5, 3), (6, -6))):
        for d in inside:
            assert ok(F(amount=10000 + d), t, tol), (tol, d)                # M08: boundary inclusive
        for d in outside:
            assert not ok(F(amount=10000 + d), t, tol), (tol, d)


# ----------------------------------------------------------------------------- matching
def _ev_issues(n):
    """n issues identical except for their required evidence id: eligibility is driven by evidence."""
    return [issue(iid=chr(ord("A") + j), sets=((f"E{j}",),)) for j in range(n)]


def _finding_for(js):
    return F(ev=tuple(f"E{j}" for j in js))


EU = U | {f"E{j}" for j in range(6)}


def test_maximum_cardinality_beats_greedy_m10():
    # F0 fits A and B, F1 fits only A. Greedy F0->A would leave F1 unmatched (TP=1); the maximum is 2.
    res = match([_finding_for([0, 1]), _finding_for([0])], _ev_issues(2), EU, 0)
    assert (res.tp, res.fp, res.fn) == (2, 0, 0)
    assert dict(res.pairs) == {1: "A", 0: "B"}                              # F1->A, F0->B


def test_official_tie_break_m11_and_order_independence():
    both = _finding_for([0, 1])
    res = match([both, both], _ev_issues(2), EU, 0)
    assert (res.tp, res.fp, res.fn) == (2, 0, 0) and dict(res.pairs) == {0: "A", 1: "B"}   # A->F0, B->F1


def test_tie_break_sorts_issue_ids_by_code_point():
    a = issue(iid="a", sets=(("E0",),))
    B = issue(iid="B", sets=(("E0",),))                                     # "B" (U+0042) < "a" (U+0061)
    res = match([_finding_for([0]), _finding_for([0])], [a, B], EU, 0)
    assert dict(res.pairs) == {0: "B", 1: "a"}


def test_duplicates_stay_separate_vertices():
    res = match([F(), F(), F()], [issue()], U, 0)
    assert (res.tp, res.fp, res.fn) == (1, 2, 0) and dict(res.pairs) == {0: "A"}   # M12 / test 5


def _brute_force(findings, issues, universe):
    ordered = sorted(issues, key=lambda t: t.issue_id)
    edges = {(i, j) for i, f in enumerate(findings) for j, t in enumerate(ordered) if not eligibility(f, t, universe, 0)}
    best_k, best_seq = 0, ()
    for k in range(min(len(findings), len(ordered)), 0, -1):
        cands = []
        for js in itertools.combinations(range(len(ordered)), k):
            for fs in itertools.permutations(range(len(findings)), k):
                pairs = list(zip(js, fs))
                if all(p in {(e[1], e[0]) for e in edges} for p in pairs):
                    cands.append(tuple((ordered[j].issue_id, i) for j, i in pairs))
        if cands:
            best_k, best_seq = k, min(cands)
            break
    return best_k, best_seq


def test_matching_equals_exhaustive_search_on_random_graphs():
    rng = DeterministicRng.from_seed(2026).child("matcher-brute-force")
    for trial in range(300):
        n_f, n_i = rng.randint(0, 5), rng.randint(0, 4)
        issues = _ev_issues(n_i)
        findings = [_finding_for([j for j in range(n_i) if rng.chance(1, 2)]) for _ in range(n_f)]
        res = match(findings, issues, EU, 0)
        k, seq = _brute_force(findings, issues, EU)
        assert res.tp == k, trial
        assert tuple(sorted((iid, i) for i, iid in res.pairs)) == seq, trial
        assert res.fp == n_f - k and res.fn == n_i - k
