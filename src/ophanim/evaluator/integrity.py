"""Referential integrity of a published episode (evaluator side).

Complements ``ophanim.audit.formats`` (per-record formats, duplicate row_id/doc_id, dangling invoice_refs
and refund_of). This module checks the relations *between* records and between the truth and the data:

  * business keys are unique (invoice_id, payment_id) and id namespaces do not overlap, so an id names
    exactly one record;
  * every ledger reference resolves: invoice_id / payment_id point to existing documents and the row's
    entity_id is the entity of that document;
  * each entity has one name; remittance lines name an invoice of the same supplier and currency with a
    positive amount; a refund returns an existing outbound payment;
  * every truth issue names existing documents and only cites existing, tool-accessible evidence.

It contains no accounting arithmetic (that stays in the independent auditor) and never changes data.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations

from ophanim.schemas import TruthFile


def _fx_key(row: dict) -> str:
    return f"{row['date']}:{row['source_currency']}:{row['target_currency']}"


def evidence_universe(tables: dict[str, list[dict]]) -> frozenset[str]:
    """Same definition as ``PublicEpisode.evidence_universe``: every id a tool can return."""
    ids = {r["row_id"] for r in tables["ledger"]}
    for table, key in (("invoices", "invoice_id"), ("payments", "payment_id")):
        ids.update(d["doc_id"] for d in tables[table])
        ids.update(d[key] for d in tables[table])
    ids.update(_fx_key(r) for r in tables["fx"])
    return frozenset(ids)


def check_integrity(tables: dict[str, list[dict]], truth: TruthFile | None = None) -> list[str]:
    p: list[str] = []
    ledger, invoices, payments = tables["ledger"], tables["invoices"], tables["payments"]

    for label, rows, key in (("invoice_id", invoices, "invoice_id"), ("payment_id", payments, "payment_id"),
                             ("row_id", ledger, "row_id")):
        for value, n in Counter(r[key] for r in rows).items():
            if n > 1:
                p.append(f"{label} {value} used by {n} records")

    namespaces = {
        "row_id": {r["row_id"] for r in ledger},
        "doc_id": {d["doc_id"] for d in invoices} | {d["doc_id"] for d in payments},
        "invoice_id": {d["invoice_id"] for d in invoices},
        "payment_id": {d["payment_id"] for d in payments},
        "entity_id": {d["entity_id"] for d in invoices} | {d["entity_id"] for d in payments},
    }
    for (a, sa), (b, sb) in combinations(namespaces.items(), 2):
        for value in sorted(sa & sb)[:3]:
            p.append(f"id {value} is both a {a} and a {b}")

    inv = {d["invoice_id"]: d for d in invoices}
    pay = {d["payment_id"]: d for d in payments}

    names: dict[str, set[str]] = defaultdict(set)
    for d in (*invoices, *payments):
        if "entity_name" in d:
            names[d["entity_id"]].add(d["entity_name"])
    for entity, ns in sorted(names.items()):
        if len(ns) > 1:
            p.append(f"entity {entity} has {len(ns)} different names")

    for r in ledger:
        doc = None
        if r["payment_id"] is not None:
            doc = pay.get(r["payment_id"])
            if doc is None:
                p.append(f"row {r['row_id']}: payment {r['payment_id']} does not exist")
        if r["invoice_id"] is not None and r["invoice_id"] not in inv:
            p.append(f"row {r['row_id']}: invoice {r['invoice_id']} does not exist")
        if doc is None and r["invoice_id"] is not None:
            doc = inv.get(r["invoice_id"])
        if doc is not None and r["entity_id"] != doc["entity_id"]:
            p.append(f"row {r['row_id']}: entity {r['entity_id']} differs from its document's entity {doc['entity_id']}")

    for d in payments:
        for ref in d["invoice_refs"] or []:
            target = inv.get(ref["invoice_id"])
            if target is None:
                continue  # reported by audit.formats
            if target["entity_id"] != d["entity_id"]:
                p.append(f"payment {d['payment_id']}: remittance names an invoice of another supplier")
            if target["currency"] != d["currency"]:
                p.append(f"payment {d['payment_id']}: remittance currency differs from the invoice currency")
            if not isinstance(ref["amount_minor"], int) or ref["amount_minor"] <= 0:
                p.append(f"payment {d['payment_id']}: remittance amount must be a positive integer")
        if d.get("refund_of") is not None:
            original = pay.get(d["refund_of"])
            if original is not None and original.get("direction", "outbound") != "outbound":
                p.append(f"payment {d['payment_id']}: refunds a payment that is not outbound")

    if truth is not None:
        universe = evidence_universe(tables)
        documents = set(inv) | set(pay)
        for iid, n in Counter(t.issue_id for t in truth.issues).items():
            if n > 1:
                p.append(f"truth issue_id {iid} used {n} times")
        for t in truth.issues:
            for a in t.affected_ids:
                if a not in documents:
                    p.append(f"{t.issue_id}: affected id {a} is not a document")
            for s in t.allowed_evidence_sets:
                missing = [e for e in s if e not in universe]
                if missing:
                    p.append(f"{t.issue_id}: evidence {missing[:3]} not accessible through the tools")
    return p
