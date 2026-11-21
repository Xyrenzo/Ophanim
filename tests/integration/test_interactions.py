"""FX, period and interacting scenarios: each produces exactly the intended discrepancies,
and the interactions are real (a shortcut that ignores one error gets the other wrong)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import pytest

from ophanim.evaluator.verifier import verify_generated
from ophanim.timeutil import parse_offset

from tests.conftest import episode

S1 = {"scenarios": {"fx_partial_payment_boundary": 1}}
S2 = {"scenarios": {"fx_invoice_unapplied_payment": 1}}


def _index(ep):
    t = ep.public.tables
    return ({i["invoice_id"]: i for i in t["invoices"]}, {p["payment_id"]: p for p in t["payments"]},
            {r["row_id"]: r for r in t["ledger"]}, {f"{r['date']}:{r['source_currency']}:{r['target_currency']}": r for r in t["fx"]})


def _convert(amount_minor, src_exp, rate: str, dst_exp):
    v = Decimal(amount_minor) / Decimal(10) ** src_exp * Decimal(rate)
    return int((v.quantize(Decimal(1) / Decimal(10) ** dst_exp, rounding=ROUND_HALF_UP)) * Decimal(10) ** dst_exp)


@pytest.mark.parametrize("seed", range(15))
def test_s1_partial_foreign_payment_at_boundary(seed):
    ep = episode(seed, S1)
    assert verify_generated(ep).ok
    issues = ep.sealed.truth.issues
    assert sorted(t.type for t in issues) == ["fx_rate", "payment_allocation"]
    assert {t.scenario for t in issues} == {"fx_partial_payment_boundary"}
    fx = next(t for t in issues if t.type == "fx_rate")
    alloc = next(t for t in issues if t.type == "payment_allocation")
    (pay_id,) = fx.affected_ids
    assert pay_id in alloc.affected_ids                      # same payment, linked issues
    invoices, payments, rows, _ = _index(ep)
    pay = payments[pay_id]
    tz = parse_offset(ep.public.manifest["timezone"])
    ts = datetime.fromisoformat(pay["timestamp"])
    local, utc = ts.astimezone(tz).date(), ts.astimezone(timezone.utc).date()
    start = datetime.fromisoformat(ep.public.manifest["period_start"]).date()
    end = datetime.fromisoformat(ep.public.manifest["period_end"]).date()
    assert start <= local <= end and not (start <= utc <= end)  # at the boundary; UTC date is outside
    assert len(pay["invoice_refs"]) == 2                     # partial: the other line was applied
    # Interaction: the Suspense amount (wrong payment-date rate) is NOT the right answer.
    susp = next(rows[e] for e in alloc.allowed_evidence_sets[0] if e in rows and rows[e]["account"] == "2090")
    assert susp["debit_minor"] != alloc.expected_amount_minor


@pytest.mark.parametrize("seed", range(15))
def test_s2_wrong_rate_invoice_with_unapplied_payment_line(seed):
    ep = episode(seed, S2)
    assert verify_generated(ep).ok
    issues = ep.sealed.truth.issues
    assert sorted(t.type for t in issues) == ["fx_rate", "payment_allocation"]
    fx = next(t for t in issues if t.type == "fx_rate")
    alloc = next(t for t in issues if t.type == "payment_allocation")
    (inv_id,) = fx.affected_ids
    assert inv_id in alloc.affected_ids
    invoices, payments, rows, _ = _index(ep)
    inv = invoices[inv_id]
    booked_ap = sum(r["credit_minor"] for r in rows.values() if r["invoice_id"] == inv_id and r["payment_id"] is None and r["account"] == "2000")
    # The line covers the whole invoice, so a shortcut "AP left open = booked AP" is off by exactly the FX error.
    assert abs(booked_ap - alloc.expected_amount_minor) == fx.expected_amount_minor
    assert inv["currency"] != ep.public.manifest["base_currency"]


@pytest.mark.parametrize("seed", range(20))
def test_period_attribution_is_a_utc_versus_local_date_error(seed):
    ep = episode(seed, {"errors": {"period_attribution": 2}})
    assert verify_generated(ep).ok
    invoices, payments, rows, _ = _index(ep)
    tz = parse_offset(ep.public.manifest["timezone"])
    start = datetime.fromisoformat(ep.public.manifest["period_start"]).date()
    end = datetime.fromisoformat(ep.public.manifest["period_end"]).date()
    for t in ep.sealed.truth.issues:
        (doc_id,) = t.affected_ids
        doc = invoices.get(doc_id) or payments[doc_id]
        ts = datetime.fromisoformat(doc.get("issued_at") or doc["timestamp"])
        assert not (start <= ts.astimezone(tz).date() <= end)     # outside in company time ...
        assert start <= ts.astimezone(timezone.utc).date() <= end  # ... but inside by UTC date


@pytest.mark.parametrize("seed", range(20))
def test_fx_errors_recompute_from_the_cited_rate(seed):
    ep = episode(seed, {"errors": {"fx_rate": 2}})
    invoices, payments, rows, fx = _index(ep)
    exps = ep.public.policy["currency_exponents"]
    base = ep.public.manifest["base_currency"]
    for t in ep.sealed.truth.issues:
        ev = t.allowed_evidence_sets[0]
        rate = next(fx[e]["rate"] for e in ev if e in fx)
        (doc_id,) = t.affected_ids
        if doc_id in invoices:
            doc = invoices[doc_id]
            correct = _convert(doc["total_minor"], exps[doc["currency"]], rate, exps[base])
            booked = next(rows[e]["credit_minor"] or rows[e]["debit_minor"] for e in ev if e in rows)
        else:
            doc = payments[doc_id]
            correct = _convert(doc["amount_minor"], exps[doc["currency"]], rate, exps[base])
            booked = next(rows[e]["credit_minor"] for e in ev if e in rows)
        assert abs(booked - correct) == t.expected_amount_minor >= 3


@pytest.mark.parametrize("error_type", ["fx_rate", "period_attribution"])
@pytest.mark.parametrize("count", [0, 1, 3])
def test_p2_types_are_independently_configurable(error_type, count):
    ep = episode(41, {"errors": {error_type: count}})
    types = Counter(t.type for t in ep.sealed.truth.issues)
    assert types == (Counter({error_type: count}) if count else Counter())
    assert verify_generated(ep).ok


@pytest.mark.parametrize("seed", range(8))
def test_maximum_twelve_issues_mixing_everything(seed):
    cfg = {"size": "large", "scenarios": {"fx_partial_payment_boundary": 1, "fx_invoice_unapplied_payment": 1},
           "errors": {"duplicate_invoice": 2, "payment_allocation": 2, "fx_rate": 2, "period_attribution": 2}}
    ep = episode(seed, cfg)
    assert len(ep.sealed.truth.issues) == 12
    rep = verify_generated(ep)
    assert rep.ok, rep.problems[:3]
    assert rep.issues_found_independently == 12
