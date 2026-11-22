"""Provenance chain validation and finding traceability (evaluator side, never agent-facing).

A generated episode records how it was made (``provenance.json``): the clean books, every injected error as
a before/after transformation, and the internal-key -> public-id map. ``check_provenance`` replays that
record and requires the chain to be complete and consistent:

    clean ledger  --(injection 1)-->  ...  --(injection n)-->  published ledger

  1. ``id_map`` is injective and every public id in the clean and published tables has an internal key;
  2. truth issues and injections correspond one to one (issue_id, type, scenario), and the number of issues
     of each kind is exactly what the generation config requested;
  3. replay: starting from the clean ledger, each injection's ``rows_before`` must be present with the
     recorded values and is removed, then its ``rows_after`` / ``rows_added`` are applied. The final state must
     equal the published ledger row for row (rows created and consumed inside one scenario chain never
     become public and need no public id);
  4. every document added by the mutation is named by an injection; no document is removed or edited;
  5. each issue's affected ids are exactly the documents its injection names, and every allowed evidence id
     is tool-accessible and belongs to an affected document (its doc_id, one of its ledger rows, or the FX key
     of its currency);
  6. red herrings and scenario carriers reference known keys, and every carrier is used by an injection of its
     scenario. Red herrings whose whole point is that the documents are correct (a reversed duplicate, a
     vendor_ref shared by two suppliers, a correct refund) are never the subject of an error. Other red-herring
     documents (a split or partial payment, a recurring invoice) may legitimately also carry an injected error.

No accounting arithmetic is repeated here: the independent auditor (``ophanim.audit``) recomputes the
books separately. This module only checks that the recorded history explains the published data exactly.

``trace_findings`` links each finding of a submission to its matched issue, the injection that caused it,
the clean and mutated rows, and whether its evidence is complete.
"""

from __future__ import annotations

from collections import Counter

from ophanim.evaluator.integrity import evidence_universe
from ophanim.evaluator.matcher import check_tolerance, match
from ophanim.schemas import Finding, TruthFile

_SNAPSHOT = ("account", "debit_minor", "credit_minor", "invoice", "payment")
_DOC_KEYS = ("original", "copy", "invoice", "payment")
# Red herrings that are only meaningful if their documents stay correct (see the injector's protected set).
PROTECTED_RED_HERRINGS = ("reversed_duplicate", "vendor_ref_collision", "correct_refund")


def _public_snapshot(row: dict, inverse: dict[str, str]) -> tuple:
    """A published/clean ledger row in the provenance snapshot form (internal document keys)."""
    return (row["account"], row["debit_minor"], row["credit_minor"],
            inverse.get(row["invoice_id"]) if row["invoice_id"] is not None else None,
            inverse.get(row["payment_id"]) if row["payment_id"] is not None else None)


def _documents(tables: dict) -> dict[str, dict]:
    docs = {d["invoice_id"]: d for d in tables["invoices"]}
    docs.update({d["payment_id"]: d for d in tables["payments"]})
    return docs


def _affected_keys(inj: dict) -> set[str]:
    d = inj["details"]
    if inj["type"] == "duplicate_invoice":
        return {d["original"], d["copy"]}
    if inj["type"] == "payment_allocation":
        return {d["payment"], d["invoice"]}
    # fx_rate / period_attribution: a payment-level error names the payment (an invoice key may be context)
    return {d["payment"]} if d.get("payment") else {d["invoice"]}


def _expected_counts(config: dict) -> Counter:
    want: Counter = Counter()
    for t, n in config.get("errors", {}).items():
        want[(t, "single")] += n
    scen = config.get("scenarios", {})
    for name in ("fx_partial_payment_boundary", "fx_invoice_unapplied_payment"):
        want[("fx_rate", name)] += scen.get(name, 0)
        want[("payment_allocation", name)] += scen.get(name, 0)
    return +want


def check_provenance(tables: dict[str, list[dict]], provenance: dict, truth: TruthFile,
                     manifest: dict | None = None) -> list[str]:
    p: list[str] = []
    id_map: dict[str, str] = provenance["id_map"]
    inverse = {v: k for k, v in id_map.items()}
    if len(inverse) != len(id_map):
        p.append("id_map maps two internal keys to the same public id")
    clean = provenance["pre_mutation"]["tables"]
    if provenance.get("episode_id") != truth.episode_id or (manifest and manifest.get("episode_id") != truth.episode_id):
        p.append("provenance, truth and manifest disagree on episode_id")

    # 1. every public id is traceable to an internal key
    for label, tbls in (("published", tables), ("clean", clean)):
        public_ids = {r["row_id"] for r in tbls["ledger"]}
        for t, key in (("invoices", "invoice_id"), ("payments", "payment_id")):
            for d in tbls[t]:
                public_ids.update((d[key], d["doc_id"], d["entity_id"]))
        unmapped = sorted(public_ids - set(inverse))
        if unmapped:
            p.append(f"{label} tables contain ids without provenance: {unmapped[:3]}")

    # 2. truth <-> injections, and the requested configuration
    injections = provenance["injections"]
    by_issue = {i["issue_id"]: i for i in injections}
    if len(by_issue) != len(injections) or set(by_issue) != {t.issue_id for t in truth.issues}:
        p.append("truth issues and provenance injections do not correspond one to one")
    for t in truth.issues:
        inj = by_issue.get(t.issue_id)
        if inj and (inj["type"], inj["scenario"]) != (t.type, t.scenario):
            p.append(f"{t.issue_id}: truth says {t.type}/{t.scenario}, provenance {inj['type']}/{inj['scenario']}")
    got = Counter((i["type"], i["scenario"]) for i in injections)
    want = _expected_counts(provenance["generation"]["config"])
    if got != want:
        p.append(f"injected issues {dict(got)} differ from the configuration {dict(want)}")

    # 3. causal replay of the ledger
    state: dict[str, tuple] = {}
    for r in clean["ledger"]:
        state[inverse.get(r["row_id"], r["row_id"])] = _public_snapshot(r, inverse)
    for n, inj in enumerate(injections):
        d = inj["details"]
        for r in d.get("rows_before", []):
            snap = tuple(r[k] for k in _SNAPSHOT)
            if state.get(r["row"]) != snap:
                p.append(f"injection {n} ({inj['type']}): row {r['row']} before-state not found as recorded")
            state.pop(r["row"], None)
        for r in d.get("rows_after", []) + d.get("rows_added", []):
            if r in d.get("rows_added", []) and r["row"] in state:
                p.append(f"injection {n} ({inj['type']}): added row {r['row']} already exists")
            state[r["row"]] = tuple(r[k] for k in _SNAPSHOT)
    published = {inverse.get(r["row_id"], r["row_id"]): _public_snapshot(r, inverse) for r in tables["ledger"]}
    for key in sorted(set(state) ^ set(published))[:5]:
        p.append(f"replay mismatch: row {id_map.get(key, key)} {'missing from' if key in state else 'unexplained in'} the published ledger")
    for key in sorted(k for k in set(state) & set(published) if state[k] != published[k])[:5]:
        p.append(f"replay mismatch: row {id_map.get(key, key)} has unexplained values")

    # 4. documents
    pub_docs, clean_docs = _documents(tables), _documents(clean)
    named = {id_map.get(d["details"].get(k)) for d in injections for k in _DOC_KEYS if d["details"].get(k)}
    for doc in sorted(set(pub_docs) - set(clean_docs)):
        if doc not in named:
            p.append(f"document {doc} was added without an injection")
    for doc in sorted(set(clean_docs) - set(pub_docs)):
        p.append(f"document {doc} disappeared from the published data")
    for doc in sorted(set(clean_docs) & set(pub_docs)):
        if clean_docs[doc] != pub_docs[doc]:
            p.append(f"document {doc} was edited by the mutation")

    # 5. affected ids and evidence trace back to the injected documents
    universe = evidence_universe(tables)
    rows_by_id = {r["row_id"]: r for r in tables["ledger"]}
    for t in truth.issues:
        inj = by_issue.get(t.issue_id)
        if inj is None:
            continue
        keys = _affected_keys(inj)
        if any(k not in id_map for k in keys):
            p.append(f"{t.issue_id}: injection names unknown keys")
            continue
        affected = {id_map[k] for k in keys}
        if set(t.affected_ids) != affected:
            p.append(f"{t.issue_id}: affected ids {sorted(t.affected_ids)} differ from the injected documents {sorted(affected)}")
        docs = [pub_docs[a] for a in affected if a in pub_docs]
        doc_ids = {d["doc_id"] for d in docs}
        currencies = {d["currency"] for d in docs}
        for s in t.allowed_evidence_sets:
            for e in s:
                if e not in universe:
                    p.append(f"{t.issue_id}: evidence {e} is not accessible")
                elif e in rows_by_id:
                    r = rows_by_id[e]
                    if r["invoice_id"] not in affected and r["payment_id"] not in affected:
                        p.append(f"{t.issue_id}: evidence row {e} belongs to no affected document")
                elif e.count(":") == 2:
                    if e.split(":")[1] not in currencies:
                        p.append(f"{t.issue_id}: FX evidence {e} is not in an affected document's currency")
                elif e not in doc_ids and e not in affected:
                    p.append(f"{t.issue_id}: evidence {e} is not a document of the issue")

    # 6. red herrings and scenario carriers
    error_docs = {k for i in injections for k in _affected_keys(i)}
    for x in provenance["distractors"]:
        keys = x.get("invoices", []) + x.get("payments", [])
        if any(k not in id_map for k in keys):
            p.append(f"red herring {x['kind']} references unknown keys")
        if x["kind"] in PROTECTED_RED_HERRINGS and error_docs & set(keys):
            p.append(f"red herring {x['kind']} document is also the subject of an error")
    for c in provenance["scenario_carriers"]:
        keys = [c["payment"], *c.get("invoices", [])]
        if any(k not in id_map for k in keys):
            p.append(f"scenario carrier {c['scenario']} references unknown keys")
        users = [i for i in injections if i["details"].get("payment") == c["payment"]]
        if c["scenario"].startswith("allocation_"):
            kind = c["scenario"].split("_", 1)[1]
            ok = any(i["type"] == "payment_allocation" and i["details"].get("allocation_kind") == kind for i in users)
        else:
            ok = any(i["scenario"] == c["scenario"] for i in users)
        if not ok:
            p.append(f"scenario carrier {c['scenario']} ({c['payment']}) is not used by a matching injection")
    return p


def trace_findings(tables: dict[str, list[dict]], provenance: dict, truth: TruthFile, submission: dict) -> list[dict]:
    """Evaluator-only trace: finding -> matched issue -> causal injection -> clean and mutated rows."""
    findings = [Finding.model_validate(f) for f in submission["findings"]]
    universe = evidence_universe(tables)
    result = match(findings, truth.issues, universe, check_tolerance(truth.tolerance_minor))
    by_issue = {i["issue_id"]: i for i in provenance["injections"]}
    id_map = provenance["id_map"]
    issues = {t.issue_id: t for t in truth.issues}
    out = []
    for v in result.verdicts:
        f = findings[v.index]
        row = {"finding": v.index, "type": f.type, "affected_ids": f.affected_ids,
               "evidence_accessible": all(e in universe for e in f.evidence_ids),
               "matched_issue": v.matched_issue, "reasons": list(v.reasons)}
        if v.matched_issue is not None:
            inj, t = by_issue[v.matched_issue], issues[v.matched_issue]
            d = inj["details"]
            before = [r["row"] for r in d.get("rows_before", [])]
            after = [r["row"] for r in d.get("rows_after", []) + d.get("rows_added", [])]
            row.update({
                "cause": inj["cause"],
                "scenario": inj["scenario"],
                # Public ids only; rows created and replaced inside one scenario chain are counted separately.
                "clean_rows": [id_map[k] for k in before if k in id_map],
                "mutated_rows": [id_map[k] for k in after if k in id_map],
                "intermediate_rows": sum(1 for k in before + after if k not in id_map),
                "evidence_set_covered": next((i for i, s in enumerate(t.allowed_evidence_sets) if set(s) <= set(f.evidence_ids)), None),
            })
        out.append(row)
    for iid in result.unmatched_issues:
        out.append({"finding": None, "matched_issue": iid, "missed": True, "type": issues[iid].type,
                    "cause": by_issue[iid]["cause"]})
    return out
