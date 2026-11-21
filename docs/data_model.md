# Data model

One episode = one fictional company, one reporting period (a calendar month), accounts payable only.
All companies, people, invoices and money are synthetic.

## Files

Public files (what the agent can read through the tools):

| file | content |
|---|---|
| `manifest.json` | `schema_version`, `env_version`, `episode_id`, `company_name`, `company_profile`, `base_currency`, `period_start`, `period_end`, `timezone`, `record_counts`, `document_count`, `rounding` (mode, currency exponents, formats) |
| `policy.json` | accounting date rule, reporting-period boundaries, FX rule, rounding rule, chart of accounts, posting rules, allocation and duplicate rules, `tolerance_minor` |
| `ledger.csv` | exactly `row_id,timestamp,account,debit_minor,credit_minor,currency,entity_id,invoice_id,payment_id` |
| `invoices.jsonl` | `doc_id, invoice_id, entity_id, issued_at, due_at, currency, total_minor, line_items` + `vendor_ref`, `entity_name` |
| `payments.jsonl` | `doc_id, payment_id, timestamp, currency, amount_minor, invoice_refs` + `entity_id`, `entity_name` |
| `fx.csv` | exactly `date,source_currency,target_currency,rate` |

Evaluator-only files (never reachable from the agent tools): `truth.json` (`issue_id, type, affected_ids,
expected_amount_minor, currency, allowed_evidence_sets`, plus `scenario`) and `provenance.json` (seed,
config, id map, red herrings, every injected transformation with before/after rows, and the complete
pre-mutation public dataset).

## Value formats

* **Money**: integers in minor units. Exponents are published per currency
  (`USD 2, EUR 2, GBP 2, CHF 2, KZT 2, CNY 2, AED 2, SGD 2, JPY 0, KWD 3`).
* **FX rates**: decimal strings (`"0.002061538"`), `1 source unit = rate target units`; target is always
  the base currency. One rate per calendar day for every foreign currency of the profile.
* **Time**: ISO-8601 with an explicit offset. Ledger and payment timestamps are written in UTC by default;
  invoice timestamps in the supplier's own offset. Company time zones are fixed offsets (no DST).
* **Missing references are explicit nulls**: JSON `null`; the literal `null` in CSV. A payment without
  remittance information has `invoice_refs: null`.
* `invoice_refs` is a list of `{"invoice_id", "amount_minor"}` remittance lines (amounts in the payment
  currency, which equals the invoice currency).

## Accounting rules (from `policy.json`)

* **Accounting date** = local calendar date, in the company offset, of the source document timestamp
  (`issued_at` for invoices, `timestamp` for payments).
* **Period**: a posting belongs to the period iff its source document's accounting date lies in
  `[period_start, period_end]`.
* **FX**: use the rate dated on the accounting date.
* **Rounding**: `convert(x) = round_half_up(x / 10**exp(src) * rate, exp(base))`, applied once per document
  amount or remittance line.
* **Postings** (all rows in base currency, every posting balances):
  * invoice: `Dr expense / Cr 2000 AP` = convert(total, invoice rate);
  * payment with remittance: one `Dr 2000 AP` row per line at the *invoice's* rate, `Cr 1000 Bank` at the
    *payment's* rate, the difference to `7900 FX gain/loss`;
  * payment without remittance: `Dr 2090 Suspense / Cr 1000 Bank` (correct treatment);
  * reversal: mirror image of an invoice posting.

## Error types (what the truth describes)

Every amount is the **absolute misstatement of the ledger in base-currency minor units**.

| type | causal transformation | `affected_ids` | expected amount | allowed evidence sets |
|---|---|---|---|---|
| `duplicate_invoice` | the same supplier invoice (same entity, vendor_ref, content) is captured and posted twice | both invoice ids | AP booked for one copy | both doc_ids + the AP or expense row of either copy (4 sets) |
| `payment_allocation` | a remittance line is not applied to its invoice; the money is parked in Suspense (single-line payment: *missing*; multi-line: *partial*) | payment id + invoice id | the line converted at the invoice's policy rate (AP left uncleared) | payment doc, invoice doc, the Suspense row, the AP rows of the other lines, FX key of the invoice date if foreign |
| `fx_rate` | a foreign posting converted at the rate of the wrong date (UTC date, due date, 1-3 day stale, month start) | invoice id or payment id | \|booked − correct\| of AP credit (invoice) or Bank credit (payment), always ≥ 3 | doc, AP/expense row or Bank row, FX key of the correct date |
| `period_attribution` | a document of the adjacent month posted into this period because the period was derived from the UTC date | invoice id or payment id | AP credit or Bank credit as booked | doc + AP/expense row or Bank row |

Reporting precedence: a posting outside the period is reported only as `period_attribution`.

### Interacting scenarios

* **S1 `fx_partial_payment_boundary`** — a two-line foreign payment at the period boundary whose UTC date
  falls in the adjacent month. The bank leg is converted at the UTC-date rate (`fx_rate`) **and** one line
  is parked in Suspense at that wrong rate (`payment_allocation`). The correct allocation amount uses the
  invoice's policy rate; the Suspense amount is provably different (test-enforced).
* **S2 `fx_invoice_unapplied_payment`** — a foreign invoice booked at a wrong-date rate (`fx_rate`) **and**
  its payment's remittance line left unapplied (`payment_allocation`). The shortcut "AP left open = booked
  AP" is wrong by exactly the FX error (test-enforced).

### Legitimate red herrings (present in clean books)

Recurring monthly invoices with equal amounts; repeat orders (same supplier and amount, different
vendor_ref); the same vendor_ref used by two different suppliers; a duplicate capture fully reversed in the
period; split payments; partial payments; one payment for several invoices; payments without remittance in
Suspense; documents whose UTC date differs from their accounting date, including at the period boundary.

## Generation pipeline

1. profile ("Financial DNA": retail, trading, software, manufacturing, logistics, consulting) and period;
2. consistent hidden history (suppliers, invoices, payments, FX) with red herrings;
3. correct postings; generator self-check of the accounting equalities;
4. snapshot of the clean books (kept in provenance);
5. causal error injection (truth + provenance);
6. presentation: random public ids, names, order, timestamp representation;
7. public dataset + sealed evaluator bundle.

Every generated episode is then checked by the **independent verifier** (see `security_model.md` and
`evaluation_protocol.md`).

Episode sizes (medium default): 244–355 ledger rows, 122–163 documents; small 149–231 rows; large
336–429 rows, 167–208 documents; 0–12 issues.
