"""Provenance chain validation, referential integrity and finding traceability (evaluator side).

A correct episode must pass; every broken link in the chain clean books -> injections -> published books ->
truth -> evidence must be detected.
"""

from __future__ import annotations

import copy

import pytest

from ophanim.audit.dataset import PublicDataset
from ophanim.audit.reconcile import reconcile
from ophanim.evaluator.integrity import check_integrity
from ophanim.evaluator.oracle import oracle_submission
from ophanim.evaluator.provenance_check import PROTECTED_RED_HERRINGS, check_provenance, trace_findings
from ophanim.evaluator.verifier import verify, verify_generated
from ophanim.generator.episode import generate_episode

CFG = {"errors": {"duplicate_invoice": 1, "payment_allocation": 1, "fx_rate": 1, "period_attribution": 1},
       "scenarios": {"fx_partial_payment_boundary": 1, "fx_invoice_unapplied_payment": 1}, "distractors": "high"}


@pytest.fixture(scope="module")
def episode():
    return generate_episode(4242, CFG)


def _copy(ep):
    return copy.deepcopy(ep.public.tables), copy.deepcopy(ep.sealed.provenance), ep.sealed.truth.model_copy(deep=True)


def _chain(tables, prov, truth, ep):
    return check_provenance(tables, prov, truth, ep.public.manifest)


def test_generated_episode_has_a_complete_chain(episode):
    tables, prov, truth = _copy(episode)
    assert _chain(tables, prov, truth, episode) == []
    assert check_integrity(tables, truth) == []
    assert verify_generated(episode).ok


@pytest.mark.parametrize("seed,cfg", [
    (11, {}), (12, {"errors": {"payment_allocation": 3}, "allocation_mode": "partial", "size": "small"}),
    (13, {"scenarios": {"fx_partial_payment_boundary": 3, "fx_invoice_unapplied_payment": 3}, "size": "large"}),
    (14, {"errors": {"duplicate_invoice": 3, "period_attribution": 3}, "presentation": {"order": "shuffled", "timestamp_offset": "company"}}),
])
def test_chain_holds_across_configurations(seed, cfg):
    ep = generate_episode(seed, cfg)
    assert _chain(ep.public.tables, ep.sealed.provenance, ep.sealed.truth, ep) == []
    assert check_integrity(ep.public.tables, ep.sealed.truth) == []


def test_s1_chain_uses_an_intermediate_row_that_never_becomes_public(episode):
    prov = episode.sealed.provenance
    produced = {r["row"] for i in prov["injections"] for r in i["details"].get("rows_after", [])}
    consumed = {r["row"] for i in prov["injections"] for r in i["details"].get("rows_before", [])}
    intermediate = (produced & consumed) - set(prov["id_map"])
    assert intermediate, "scenario S1 rewrites the payment twice; the first result is replaced by the second"


# ----------------------------------------------------------------------------- broken chains are detected
def _first(prov, type_):
    return next(i for i in prov["injections"] if i["type"] == type_)


def test_a_missing_injection_is_detected(episode):
    tables, prov, truth = _copy(episode)
    prov["injections"].pop(0)
    problems = _chain(tables, prov, truth, episode)
    assert any("correspond one to one" in p for p in problems)
    assert any("replay mismatch" in p or "differ from the configuration" in p for p in problems)


def test_a_falsified_mutation_record_is_detected(episode):
    tables, prov, truth = _copy(episode)
    single = next(i for i in prov["injections"] if i["type"] == "fx_rate" and i["scenario"] == "single")
    row = single["details"]["rows_after"][0]
    row["debit_minor" if row["debit_minor"] else "credit_minor"] += 1
    assert any("replay mismatch" in p for p in _chain(tables, prov, truth, episode))


def test_a_falsified_intermediate_step_breaks_the_scenario_chain(episode):
    tables, prov, truth = _copy(episode)
    s1 = next(i for i in prov["injections"] if i["type"] == "fx_rate" and i["scenario"] == "fx_partial_payment_boundary")
    row = next(r for r in s1["details"]["rows_after"] if r["row"] not in prov["id_map"])
    row["debit_minor" if row["debit_minor"] else "credit_minor"] += 1
    assert any("before-state not found" in p for p in _chain(tables, prov, truth, episode))


def test_a_falsified_clean_snapshot_is_detected(episode):
    tables, prov, truth = _copy(episode)
    target = _first(prov, "payment_allocation")["details"]["rows_before"][0]["row"]
    public_id = prov["id_map"][target]
    row = next(r for r in prov["pre_mutation"]["tables"]["ledger"] if r["row_id"] == public_id)
    row["account"] = "9999"
    assert any("before-state not found" in p for p in _chain(tables, prov, truth, episode))


def test_an_unexplained_published_row_is_detected(episode):
    tables, prov, truth = _copy(episode)
    extra = dict(tables["ledger"][0], row_id="GL-UNEXPLAINED")
    tables["ledger"].append(extra)
    problems = _chain(tables, prov, truth, episode)
    assert any("without provenance" in p for p in problems)
    assert any("unexplained in the published ledger" in p for p in problems)


def test_an_edited_document_is_detected(episode):
    tables, prov, truth = _copy(episode)
    tables["invoices"][0]["vendor_ref"] += "-X"
    assert any("edited by the mutation" in p for p in _chain(tables, prov, truth, episode))


def test_a_non_injective_id_map_is_detected(episode):
    tables, prov, truth = _copy(episode)
    keys = sorted(k for k in prov["id_map"] if k.startswith("R"))
    prov["id_map"][keys[1]] = prov["id_map"][keys[0]]
    assert any("same public id" in p for p in _chain(tables, prov, truth, episode))


def test_wrong_affected_ids_in_truth_are_detected(episode):
    tables, prov, truth = _copy(episode)
    issue = next(t for t in truth.issues if t.type == "fx_rate")
    other = next(d["invoice_id"] for d in tables["invoices"] if d["invoice_id"] not in issue.affected_ids)
    issue.affected_ids = [other]
    assert any("differ from the injected documents" in p for p in _chain(tables, prov, truth, episode))


def test_evidence_from_an_unrelated_document_is_detected(episode):
    tables, prov, truth = _copy(episode)
    issue = next(t for t in truth.issues if t.type == "duplicate_invoice")
    unrelated = next(r["row_id"] for r in tables["ledger"]
                     if r["invoice_id"] not in issue.affected_ids and r["payment_id"] is None)
    issue.allowed_evidence_sets = [sorted(issue.allowed_evidence_sets[0][:-1] + [unrelated])]
    assert any("belongs to no affected document" in p for p in _chain(tables, prov, truth, episode))


def test_a_configuration_that_does_not_match_the_injections_is_detected(episode):
    tables, prov, truth = _copy(episode)
    prov["generation"]["config"]["errors"]["fx_rate"] = 2
    assert any("differ from the configuration" in p for p in _chain(tables, prov, truth, episode))


def test_an_unused_scenario_carrier_is_detected(episode):
    tables, prov, truth = _copy(episode)
    carrier = prov["scenario_carriers"][0]
    spare = next(k for k in sorted(prov["id_map"]) if k.startswith("P") and k != carrier["payment"]
                 and all(i["details"].get("payment") != k for i in prov["injections"]))
    carrier["payment"] = spare
    assert any("not used by a matching injection" in p for p in _chain(tables, prov, truth, episode))


@pytest.mark.parametrize("kind", PROTECTED_RED_HERRINGS)
def test_a_protected_red_herring_that_carries_an_error_is_detected(episode, kind):
    tables, prov, truth = _copy(episode)
    victim = _first(prov, "fx_rate")["details"]
    key = victim.get("payment") or victim["invoice"]
    field = "payments" if key.startswith("P") else "invoices"
    prov["distractors"].append({"kind": kind, "note": "tampered", field: [key]})
    assert any(f"red herring {kind}" in p for p in _chain(tables, prov, truth, episode))


def test_the_verifier_reports_a_broken_chain(episode):
    tables, prov, truth = _copy(episode)
    prov["injections"][0]["details"].setdefault("rows_added", []).append(
        {"row": "R99999", "account": "6900", "debit_minor": 1, "credit_minor": 0, "invoice": None, "payment": None, "role": "expense"})
    ds = PublicDataset.from_tables(episode.public.manifest, episode.public.policy, tables)
    rep = verify(ds, truth, prov["pre_mutation"]["tables"], prov)
    assert not rep.ok and any(p.startswith("provenance: replay mismatch") for p in rep.problems)


# ----------------------------------------------------------------------------- referential integrity
def test_integrity_detects_duplicate_and_dangling_ids(episode):
    tables, _, truth = _copy(episode)
    tables["payments"][1]["payment_id"] = tables["payments"][0]["payment_id"]
    row = next(r for r in tables["ledger"] if r["invoice_id"] and r["payment_id"] is None)
    row["invoice_id"] = "INV-DOES-NOT-EXIST"
    problems = check_integrity(tables, truth)
    assert any("used by 2 records" in p for p in problems)
    assert any("does not exist" in p for p in problems)


def test_integrity_detects_inconsistent_entities_and_remittance(episode):
    tables, _, truth = _copy(episode)
    row = next(r for r in tables["ledger"] if r["invoice_id"] and r["payment_id"] is None)
    other_entity = next(d["entity_id"] for d in tables["invoices"] if d["entity_id"] != row["entity_id"])
    row["entity_id"] = other_entity
    pay = next(d for d in tables["payments"] if d["invoice_refs"])
    foreign = next(d["invoice_id"] for d in tables["invoices"] if d["entity_id"] != pay["entity_id"])
    pay["invoice_refs"][0]["invoice_id"] = foreign
    problems = check_integrity(tables, truth)
    assert any("differs from its document's entity" in p for p in problems)
    assert any("another supplier" in p for p in problems)


def test_integrity_detects_truth_that_cites_missing_records(episode):
    tables, _, truth = _copy(episode)
    truth.issues[0].affected_ids = ["INV-NOWHERE"]
    truth.issues[1].allowed_evidence_sets = [["GL-NOWHERE"]]
    problems = check_integrity(tables, truth)
    assert any("is not a document" in p for p in problems)
    assert any("not accessible through the tools" in p for p in problems)


# ----------------------------------------------------------------------------- traceability of findings
def _auditor_submission(ep) -> dict:
    report = reconcile(PublicDataset.from_tables(ep.public.manifest, ep.public.policy, ep.public.tables))
    return {"episode_id": ep.public.episode_id, "findings": [
        {"type": f.type, "affected_ids": list(f.affected_ids), "claimed_amount_minor": f.amount_minor,
         "currency": f.currency, "evidence_ids": list(f.evidence_ids), "explanation": f.note} for f in report.findings]}


def test_every_auditor_finding_traces_to_its_injection(episode):
    trace = trace_findings(episode.public.tables, episode.sealed.provenance, episode.sealed.truth, _auditor_submission(episode))
    assert len(trace) == len(episode.sealed.truth.issues)
    for t in trace:
        assert t["matched_issue"] and t["evidence_accessible"] and t["evidence_set_covered"] is not None
        assert t["cause"] and t["mutated_rows"]
        assert all(r.startswith("GL-") for r in t["mutated_rows"] + t["clean_rows"])


def test_trace_explains_a_wrong_finding_and_lists_the_missed_issue(episode):
    sub = oracle_submission(episode.sealed)
    sub["findings"][0] = dict(sub["findings"][0], claimed_amount_minor=sub["findings"][0]["claimed_amount_minor"] + 1)
    trace = trace_findings(episode.public.tables, episode.sealed.provenance, episode.sealed.truth, sub)
    wrong = next(t for t in trace if t["finding"] == 0)
    assert wrong["matched_issue"] is None and "amount" in wrong["reasons"]
    missed = [t for t in trace if t.get("missed")]
    assert len(missed) == 1 and missed[0]["cause"]
