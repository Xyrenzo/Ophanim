"""Task description and tool specification shown to the agent at reset.

Everything here is public: it describes the rules of the game, never the answer.
"""

from __future__ import annotations

from ophanim.schemas import MAX_EVIDENCE_IDS, MAX_EXPLANATION_CHARS, MAX_FINDINGS

TASK_TEXT = f"""\
You are auditing the accounts-payable books of a fictional company for ONE reporting period.
The books may contain accounting errors, or they may be completely clean. Investigate with the
tools and finish with one `submit` action. Submitting nothing (an empty findings list) is a valid
answer for clean books. Exploration earns no reward; the episode is scored once, at the end.

Data (read-only): tables `ledger`, `invoices`, `payments`, `fx`; documents by doc_id
(invoices and payments). The manifest and policy below define currencies, exponents, the
company timezone, the period, FX and rounding rules. Amounts are integer minor units.

Report only these four discrepancy types. Each discrepancy must be reported exactly once.
All claimed amounts are the misstatement of the ledger in the BASE currency (minor units,
tolerance +/- policy.tolerance_minor) and `currency` must be the base currency code.

1. duplicate_invoice - the same supplier invoice (same entity_id and vendor_ref, same content)
   has two active postings in this ledger (a copy that was fully reversed is not an error;
   equal amounts or equal vendor_ref across different suppliers are not errors).
   affected_ids: the invoice_id of BOTH copies. amount: the AP amount booked for one copy.
   evidence: both invoice doc_ids + the AP (or expense) row of either copy.
2. payment_allocation - a remittance line in a payment's invoice_refs was not applied to that
   invoice's AP (the money was parked in Suspense instead).
   affected_ids: [payment_id, invoice_id]. amount: the remittance line converted at the
   INVOICE's policy rate (the AP left uncleared).
   evidence: payment doc_id, invoice doc_id, the payment's Suspense row, the payment's AP rows
   for its other (applied) lines, and the FX key for the invoice's accounting date if foreign.
3. fx_rate - a foreign-currency posting converted at a rate other than the policy rate.
   affected_ids: [invoice_id] or [payment_id]. amount: |booked - correct| of the invoice's AP
   credit, or of the payment's Bank credit.
   evidence: the doc_id, the AP (or expense) row / the Bank row, and the FX key of the
   accounting date ("YYYY-MM-DD:SRC:BASE").
4. period_attribution - a posting in this ledger whose source document's accounting date
   (local date in the company timezone) lies outside the period. Report such a posting only
   with this type. affected_ids: [invoice_id] or [payment_id]. amount: the AP credit (invoice)
   or Bank credit (payment) as booked. evidence: the doc_id and the AP (or expense) / Bank row.

Evidence ids are row_id (ledger), doc_id (documents) or FX keys "date:source:target". Every
evidence id must exist. Findings are matched one-to-one against the hidden answer on type,
affected_ids (as a set), amount within tolerance, currency and a complete evidence set.
Repeated findings count as false positives. Explanations are not scored.

Reward = clip(2*F1 - 1 - 0.002*inspection_steps, -1, 1), where inspection_steps counts every
step before submit (including invalid actions). Malformed findings end the episode with -1.
Limits: 100 steps including submit; 60 seconds; at most {MAX_FINDINGS} findings,
{MAX_EVIDENCE_IDS} evidence ids per finding, {MAX_EXPLANATION_CHARS} characters of explanation.
"""

# Actions are FLAT JSON objects: {"action": <name>, <field>: <value>, ...}.
TOOL_SPECS = [
    {"action": "list_records",
     "fields": {"table": "ledger | invoices | payments | fx", "cursor": "string or null (use next_cursor)",
                "limit": "integer 1-50 (default 50)"},
     "example": {"action": "list_records", "table": "ledger", "cursor": None, "limit": 50}},
    {"action": "get_record",
     "fields": {"table": "ledger | invoices | payments | fx",
                "id": "row_id | invoice_id | payment_id | FX key 'YYYY-MM-DD:SRC:BASE'"},
     "example": {"action": "get_record", "table": "fx", "id": "2026-03-14:EUR:USD"}},
    {"action": "get_document",
     "fields": {"doc_id": "doc_id of an invoice or payment"},
     "example": {"action": "get_document", "doc_id": "DOC-XXXXXXXXXX"}},
    {"action": "calculator",
     "fields": {"expression": "numbers, + - * / and parentheses only"},
     "example": {"action": "calculator", "expression": "(1250.00 * 1.083215) - 1354.02"}},
    {"action": "submit",
     "fields": {"findings": {
         "episode_id": "string (manifest.episode_id)",
         "findings": [{"type": "duplicate_invoice | payment_allocation | fx_rate | period_attribution",
                       "affected_ids": ["id"], "claimed_amount_minor": "integer >= 0", "currency": "base currency code",
                       "evidence_ids": ["id"], "explanation": "short justification"}]}},
     "example": {"action": "submit", "findings": {"episode_id": "EP-XXXXXXXXXXXX", "findings": []}}},
]
