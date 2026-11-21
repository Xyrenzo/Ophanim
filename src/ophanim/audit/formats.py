"""Format and schema checks of the public dataset (stdlib only)."""

from __future__ import annotations

import re
from datetime import datetime

from ophanim.audit.dataset import LEDGER_COLUMNS, PublicDataset
from ophanim.audit.rules import RATE_PATTERN

_CURRENCY = re.compile(r"^[A-Z]{3}$")
INVOICE_REQUIRED = ("doc_id", "invoice_id", "entity_id", "issued_at", "due_at", "currency", "total_minor", "line_items")
PAYMENT_REQUIRED = ("doc_id", "payment_id", "timestamp", "currency", "amount_minor", "invoice_refs")
MANIFEST_REQUIRED = ("schema_version", "episode_id", "base_currency", "period_start", "period_end", "timezone",
                     "record_counts", "document_count", "rounding")
POLICY_REQUIRED = ("base_currency", "timezone", "currency_exponents", "accounting_date", "reporting_period", "fx",
                   "rounding", "accounts", "tolerance_minor")


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _ts_ok(v) -> bool:
    if not isinstance(v, str) or "T" not in v:
        return False
    try:
        m = datetime.fromisoformat(v)
    except ValueError:
        return False
    return m.tzinfo is not None and v[-6] in "+-"  # explicit ±HH:MM offset


def check_formats(ds: PublicDataset) -> list[str]:
    p: list[str] = []
    for k in MANIFEST_REQUIRED:
        if k not in ds.manifest:
            p.append(f"manifest missing {k}")
    for k in POLICY_REQUIRED:
        if k not in ds.policy:
            p.append(f"policy missing {k}")
    exps = ds.policy.get("currency_exponents", {})
    base = ds.policy.get("base_currency")

    counts = ds.manifest.get("record_counts", {})
    for name, rows in (("ledger", ds.ledger), ("invoices", ds.invoices), ("payments", ds.payments), ("fx", ds.fx)):
        if counts.get(name) != len(rows):
            p.append(f"manifest count for {name} is wrong")
    if ds.manifest.get("document_count") != len(ds.invoices) + len(ds.payments):
        p.append("manifest document_count is wrong")

    seen: set[str] = set()
    for r in ds.ledger:
        if tuple(r.keys()) != LEDGER_COLUMNS:
            p.append(f"ledger row {r.get('row_id')}: wrong columns")
            continue
        if r["row_id"] in seen:
            p.append(f"duplicate row_id {r['row_id']}")
        seen.add(r["row_id"])
        if not (_is_int(r["debit_minor"]) and _is_int(r["credit_minor"])):
            p.append(f"row {r['row_id']}: amounts must be integers")
        elif r["debit_minor"] < 0 or r["credit_minor"] < 0 or (r["debit_minor"] > 0) == (r["credit_minor"] > 0):
            p.append(f"row {r['row_id']}: exactly one positive side required")
        if not _ts_ok(r["timestamp"]):
            p.append(f"row {r['row_id']}: timestamp needs ISO-8601 with offset")
        if r["currency"] != base:
            p.append(f"row {r['row_id']}: currency must be the base currency")
        for c in ("entity_id", "invoice_id", "payment_id"):
            if r[c] == "" or r[c] == "null":
                p.append(f"row {r['row_id']}: missing reference must be null")

    inv_ids = set()
    doc_ids: set[str] = set()
    for d in ds.invoices:
        for k in INVOICE_REQUIRED:
            if k not in d:
                p.append(f"invoice missing {k}")
        if d.get("doc_id") in doc_ids:
            p.append("duplicate doc_id")
        doc_ids.add(d.get("doc_id"))
        inv_ids.add(d.get("invoice_id"))
        if d.get("currency") not in exps:
            p.append(f"invoice {d.get('invoice_id')}: unknown currency")
        if not (_ts_ok(d.get("issued_at")) and _ts_ok(d.get("due_at"))):
            p.append(f"invoice {d.get('invoice_id')}: timestamps need offsets")
        elif datetime.fromisoformat(d["due_at"]) < datetime.fromisoformat(d["issued_at"]):
            p.append(f"invoice {d.get('invoice_id')}: due before issue")
        lines = d.get("line_items") or []
        if not _is_int(d.get("total_minor")) or sum(l["amount_minor"] for l in lines) != d.get("total_minor"):
            p.append(f"invoice {d.get('invoice_id')}: total differs from line items")
        for l in lines:
            if l["quantity"] * l["unit_price_minor"] != l["amount_minor"]:
                p.append(f"invoice {d.get('invoice_id')}: line amount != quantity x unit price")

    for d in ds.payments:
        for k in PAYMENT_REQUIRED:
            if k not in d:
                p.append(f"payment missing {k}")
        if d.get("doc_id") in doc_ids:
            p.append("duplicate doc_id")
        doc_ids.add(d.get("doc_id"))
        if d.get("currency") not in exps:
            p.append(f"payment {d.get('payment_id')}: unknown currency")
        if not _ts_ok(d.get("timestamp")):
            p.append(f"payment {d.get('payment_id')}: timestamp needs offset")
        refs = d.get("invoice_refs")
        if refs is not None:
            if not refs:
                p.append(f"payment {d.get('payment_id')}: empty remittance must be null")
            for x in refs:
                if x.get("invoice_id") not in inv_ids:
                    p.append(f"payment {d.get('payment_id')}: references an invoice not in invoices.jsonl")

    fx_seen = set()
    for r in ds.fx:
        if not RATE_PATTERN.match(str(r.get("rate", ""))):
            p.append(f"fx {r}: rate must be a decimal string")
        if not (_CURRENCY.match(r.get("source_currency", "")) and _CURRENCY.match(r.get("target_currency", ""))):
            p.append("fx: bad currency code")
        k = (r.get("date"), r.get("source_currency"), r.get("target_currency"))
        if k in fx_seen:
            p.append(f"fx: duplicate rate for {k}")
        fx_seen.add(k)
    return p
