"""Causal error injection.

Each injector takes a *correct* world and applies one realistic bookkeeping
mistake as an explicit transformation, recording:
  * the error type and the affected source documents,
  * the exact misstatement of the ledger in base-currency minor units,
  * the allowed evidence sets (public records sufficient to prove it),
  * a causal explanation and before/after rows for provenance.

Invariants every injector must keep (checked by the independent verifier):
  * every posting still balances (errors are misclassifications, not arithmetic slips);
  * the transformation creates exactly the declared discrepancy and nothing else;
  * a document involved in one injected issue is not reused by another, except
    inside a designed interacting scenario.

Evidence items are internal references:
    ("doc", <invoice or payment key>) | ("row", <row key>) | ("fx", <ISO date>, <currency>)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta, timezone
from decimal import Decimal

from ophanim.generator.model import ACCOUNT_SUSPENSE, GenerationError, Invoice, LineItem, Posting, Row, World
from ophanim.generator.posting import allocation_base_amount, fx_balancing_row, post_invoice
from ophanim.generator.profiles import PROFILES
from ophanim.money import convert_minor
from ophanim.rng import DeterministicRng
from ophanim.schemas import EpisodeConfig

EvidenceItem = tuple


@dataclass
class InjectedIssue:
    type: str
    affected: list[str]
    amount_minor: int
    evidence_sets: list[list[EvidenceItem]]
    scenario: str
    cause: str
    details: dict = field(default_factory=dict)


def _snapshot(rows: list[Row]) -> list[dict]:
    return [
        {"row": r.key, "account": r.account, "debit_minor": r.debit_minor, "credit_minor": r.credit_minor,
         "invoice": r.invoice_key, "payment": r.payment_key, "role": r.role}
        for r in rows
    ]


class ErrorInjector:
    def __init__(self, world: World, rng: DeterministicRng) -> None:
        self.world = world
        self.rng = rng
        self.used: set[str] = set()
        self.issues: list[InjectedIssue] = []
        # Rate actually used on a payment's bank row when an FX error replaced the policy rate.
        self.booked_payment_rate: dict[str, object] = {}
        # Documents whose legitimacy is the point of a red herring are never targeted.
        self.protected: set[str] = set()
        for d in world.distractors:
            if d["kind"] in ("reversed_duplicate", "vendor_ref_collision"):
                self.protected.update(d.get("invoices", []))
            if d["kind"] == "correct_refund":  # the refund and the refunded payment stay correct (D03)
                self.protected.update(d.get("payments", []))

    # ------------------------------------------------------------------ driver
    def run(self, config: EpisodeConfig) -> list[InjectedIssue]:
        w = self.world
        for c in w.scenario_carriers:  # carriers are reserved for their scenario
            self.used.add(c["payment"])
            self.used.update(c["invoices"])
        for i, c in enumerate(x for x in w.scenario_carriers if x["scenario"] == "fx_partial_payment_boundary"):
            self.issues.extend(self.scenario_fx_partial_payment_boundary(self.rng.child(f"s1/{i}"), c))
        for i, c in enumerate(x for x in w.scenario_carriers if x["scenario"] == "fx_invoice_unapplied_payment"):
            self.issues.extend(self.scenario_fx_invoice_unapplied_payment(self.rng.child(f"s2/{i}"), c))
        mode = config.allocation_mode
        alloc_carriers = [c for c in w.scenario_carriers if c["scenario"] == f"allocation_{mode}"]

        def allocation(r: DeterministicRng, i: int) -> InjectedIssue:
            if mode == "auto":
                return self.payment_allocation(r)
            c = alloc_carriers[i]  # an explicit mode never falls back to random selection
            return self.payment_allocation(r, payment_key=c["payment"], invoice_key=r.choice(c["invoices"]),
                                           required_kind=mode)

        plan = [
            ("duplicate_invoice", config.errors.duplicate_invoice, lambda r, i: self.duplicate_invoice(r)),
            ("payment_allocation", config.errors.payment_allocation, allocation),
            ("fx_rate", config.errors.fx_rate, lambda r, i: self.fx_rate(r)),
            ("period_attribution", config.errors.period_attribution, lambda r, i: self.period_attribution(r)),
        ]
        for name, count, fn in plan:
            for i in range(count):
                self.issues.append(fn(self.rng.child(f"{name}/{i}"), i))
        return self.issues

    # ------------------------------------------------------------------ helpers
    def _free(self, *keys: str) -> bool:
        return not any(k in self.used or k in self.protected for k in keys)

    def _posted_period_invoices(self) -> list[Invoice]:
        w = self.world
        out = []
        for p in w.postings:
            if p.kind == "invoice" and p.source_key not in w.reversals:
                inv = w.invoices[p.source_key]
                if inv.origin == "period" and self._free(inv.key):
                    out.append(inv)
        return sorted(out, key=lambda i: i.key)

    def _posting(self, source_key: str, kind: str) -> Posting:
        p = self.world.posting_for(source_key, kind)
        if p is None:
            raise GenerationError(f"no {kind} posting for {source_key}")
        return p

    @staticmethod
    def _row(posting: Posting, role: str, invoice_key: str | None = None) -> Row:
        for r in posting.rows:
            if r.role == role and (invoice_key is None or r.invoice_key == invoice_key):
                return r
        raise GenerationError(f"posting {posting.key} has no {role} row")

    def _fx_item(self, inv_or_pay_currency: str, moment) -> list[EvidenceItem]:
        w = self.world
        if inv_or_pay_currency == w.base_currency:
            return []
        return [("fx", w.accounting_date(moment).isoformat(), inv_or_pay_currency)]

    # ------------------------------------------------------------------ type 1
    def duplicate_invoice(self, r: DeterministicRng) -> InjectedIssue:
        """The same supplier invoice is captured a second time and posted again."""
        w = self.world
        candidates = self._posted_period_invoices()
        if not candidates:
            raise GenerationError("no invoice available for a duplicate")
        original = r.choice(candidates)
        copy = Invoice(
            key=w.new_invoice_key(), supplier_key=original.supplier_key, vendor_ref=original.vendor_ref,
            issued_at=original.issued_at, due_at=original.due_at, currency=original.currency,
            lines=[LineItem(l.description, l.quantity, l.unit_price_minor, l.service_period) for l in original.lines],
            origin="duplicate_copy",
        )
        w.invoices[copy.key] = copy
        posting = post_invoice(w, copy)
        w.postings.append(posting)
        self.used.update({original.key, copy.key})
        orig_posting = self._posting(original.key, "invoice")
        amount = self._row(posting, "ap").credit_minor
        evidence = []
        for p in (orig_posting, posting):
            for role in ("ap", "expense"):
                evidence.append([("doc", original.key), ("doc", copy.key), ("row", self._row(p, role).key)])
        return InjectedIssue(
            type="duplicate_invoice",
            affected=[original.key, copy.key],
            amount_minor=amount,
            evidence_sets=evidence,
            scenario="single",
            cause=(f"Supplier invoice {original.vendor_ref} was captured twice; the second capture {copy.key} "
                   f"was posted as a new invoice, overstating AP and expense by {amount}."),
            details={"original": original.key, "copy": copy.key, "rows_added": _snapshot(posting.rows)},
        )

    # ------------------------------------------------------------------ type 2
    def payment_allocation(self, r: DeterministicRng, payment_key: str | None = None,
                           invoice_key: str | None = None, scenario: str = "single",
                           required_kind: str | None = None) -> InjectedIssue:
        """A remittance line is not applied to its invoice; the money is parked in Suspense.

        Single-line payment -> missing allocation (nothing applied); multi-line payment -> partial
        allocation (0 < applied < amount). ``required_kind`` ("missing"/"partial") is enforced: a payment of
        the wrong shape raises instead of silently producing the other kind.
        Misstatement = AP of the invoice left uncleared = line amount at the invoice's policy rate.
        """
        w = self.world
        if required_kind is not None and payment_key is not None:
            n_lines = len(w.payments[payment_key].refs or [])
            if (required_kind == "missing") != (n_lines == 1) or n_lines == 0:
                raise GenerationError(f"carrier cannot produce a {required_kind} allocation")
        if payment_key is None:
            candidates = []
            for p in w.postings:
                if p.kind != "payment":
                    continue
                pay = w.payments[p.source_key]
                if pay.refs and self._free(pay.key, *[a.invoice_key for a in pay.refs]):
                    candidates.append(pay)
            if not candidates:
                raise GenerationError("no payment available for an allocation error")
            pay = r.choice(sorted(candidates, key=lambda x: x.key))
            line = r.choice(pay.refs)
        else:
            pay = w.payments[payment_key]
            line = next(a for a in pay.refs if a.invoice_key == invoice_key)
        posting = self._posting(pay.key, "payment")
        before = _snapshot(posting.rows)
        inv = w.invoices[line.invoice_key]

        # Booked payment rate = what the bank row actually used (may itself be wrong in S1).
        bank_row = self._row(posting, "bank")
        removed = [x for x in posting.rows if x.role == "ap_clear" and x.invoice_key == inv.key]
        if not removed:
            raise GenerationError("remittance line already unapplied")
        posting.rows = [x for x in posting.rows if x not in removed and x.role != "fx"]
        booked_rate = self.booked_payment_rate.get(pay.key) or w.rate(pay.currency, w.accounting_date(pay.timestamp))
        parked = convert_minor(line.amount_minor, pay.currency, w.base_currency, booked_rate)
        suspense = Row(key=w.new_row_key(), timestamp=pay.timestamp, account=ACCOUNT_SUSPENSE, debit_minor=parked,
                       credit_minor=0, entity_key=pay.supplier_key, invoice_key=None, payment_key=pay.key, role="suspense")
        posting.rows.insert(0, suspense)
        applied = sum(x.debit_minor for x in posting.rows if x.role in ("ap_clear", "suspense"))
        fx = fx_balancing_row(w, pay, bank_row.credit_minor, applied)
        if fx is not None:
            posting.rows.append(fx)
        self.used.update({pay.key, inv.key})

        amount = allocation_base_amount(w, inv.key, line.amount_minor)
        other_ap = [("row", x.key) for x in posting.rows if x.role == "ap_clear"]
        evidence = [[("doc", pay.key), ("doc", inv.key), ("row", suspense.key), *other_ap,
                     *self._fx_item(inv.currency, inv.issued_at)]]
        kind = "missing" if len(pay.refs) == 1 else "partial"
        return InjectedIssue(
            type="payment_allocation",
            affected=[pay.key, inv.key],
            amount_minor=amount,
            evidence_sets=evidence,
            scenario=scenario,
            cause=(f"Remittance line {inv.key} ({line.amount_minor} {pay.currency}) of payment {pay.key} was not "
                   f"applied ({kind} allocation); it was posted to Suspense, leaving AP overstated by {amount}."),
            details={"payment": pay.key, "invoice": inv.key, "allocation_kind": kind,
                     "rows_before": before, "rows_after": _snapshot(posting.rows)},
        )

    # ------------------------------------------------------------------ type 3
    MIN_FX_DELTA = 3  # minor units: an injected FX error is always a clearly visible discrepancy

    def _wrong_rate_options(self, currency: str, moment, amount_minor: int, due_at=None,
                            force: str | None = None) -> list[tuple[str, date, Decimal, int]]:
        """Plausible wrong rate dates that produce a clear discrepancy: (cause, day, rate, delta)."""
        w = self.world
        correct_day = w.accounting_date(moment)
        correct = convert_minor(amount_minor, currency, w.base_currency, w.rate(currency, correct_day))
        candidates: list[tuple[str, date]] = []
        utc_day = moment.astimezone(timezone.utc).date()
        if utc_day != correct_day:
            candidates.append(("utc_date", utc_day))
        if force is None:
            if due_at is not None:
                candidates.append(("due_date", w.accounting_date(due_at)))
            for k in (1, 2, 3):
                candidates.append((f"stale_rate_{k}d", correct_day - timedelta(days=k)))
            candidates.append(("month_start_rate", correct_day.replace(day=1)))
        out = []
        for cause, day in candidates:
            if force is not None and cause != force:
                continue
            if day == correct_day or (day, currency) not in w.fx:
                continue
            rate = w.fx[(day, currency)]
            delta = convert_minor(amount_minor, currency, w.base_currency, rate) - correct
            if abs(delta) >= self.MIN_FX_DELTA:
                out.append((cause, day, rate, delta))
        return out

    def fx_rate(self, r: DeterministicRng) -> InjectedIssue:
        """A foreign-currency posting translated at the rate of the wrong date."""
        first = "invoice" if r.chance(1, 2) else "payment"
        for kind in (first, "payment" if first == "invoice" else "invoice"):
            try:
                return self.fx_rate_invoice(r) if kind == "invoice" else self.fx_rate_payment(r)
            except GenerationError:
                continue
        raise GenerationError("no foreign-currency posting available for an fx_rate error")

    def fx_rate_invoice(self, r: DeterministicRng, invoice_key: str | None = None, scenario: str = "single") -> InjectedIssue:
        w = self.world
        if invoice_key is None:
            pool = [i for i in self._posted_period_invoices() if i.currency != w.base_currency]
            r.shuffle(pool)
        else:
            pool = [w.invoices[invoice_key]]
        for inv in pool:
            options = self._wrong_rate_options(inv.currency, inv.issued_at, inv.total_minor, due_at=inv.due_at)
            if not options:
                continue
            cause, day, rate, delta = r.choice(options)
            posting = self._posting(inv.key, "invoice")
            before = _snapshot(posting.rows)
            booked = convert_minor(inv.total_minor, inv.currency, w.base_currency, rate)
            for row in posting.rows:
                if row.role == "expense":
                    row.debit_minor = booked
                elif row.role == "ap":
                    row.credit_minor = booked
            self.used.add(inv.key)
            correct_day = w.accounting_date(inv.issued_at)
            fx = ("fx", correct_day.isoformat(), inv.currency)
            return InjectedIssue(
                type="fx_rate", affected=[inv.key], amount_minor=abs(delta),
                evidence_sets=[[("doc", inv.key), ("row", self._row(posting, "ap").key), fx],
                               [("doc", inv.key), ("row", self._row(posting, "expense").key), fx]],
                scenario=scenario,
                cause=(f"Invoice {inv.key} was translated at the {day.isoformat()} rate ({cause}) instead of the "
                       f"{correct_day.isoformat()} policy rate; AP and expense misstated by {abs(delta)}."),
                details={"invoice": inv.key, "wrong_rate_date": day.isoformat(), "wrong_rate_cause": cause,
                         "rows_before": before, "rows_after": _snapshot(posting.rows)},
            )
        raise GenerationError("no invoice available for an fx_rate error")

    def fx_rate_payment(self, r: DeterministicRng, payment_key: str | None = None, force: str | None = None,
                        scenario: str = "single") -> InjectedIssue:
        w = self.world
        if payment_key is None:
            pool = []
            for p in w.postings:
                if p.kind == "payment":
                    pay = w.payments[p.source_key]
                    if pay.currency != w.base_currency and self._free(pay.key):
                        pool.append(pay)
            pool.sort(key=lambda x: x.key)
            r.shuffle(pool)
        else:
            pool = [w.payments[payment_key]]
        for pay in pool:
            options = self._wrong_rate_options(pay.currency, pay.timestamp, pay.amount_minor, force=force)
            if not options:
                continue
            cause, day, rate, delta = r.choice(options)
            posting = self._posting(pay.key, "payment")
            before = _snapshot(posting.rows)
            bank_row = self._row(posting, "bank")
            booked_bank = convert_minor(pay.amount_minor, pay.currency, w.base_currency, rate)
            bank_row.credit_minor = booked_bank
            for row in posting.rows:  # an unidentified payment parks the same (wrong) amount in Suspense
                if row.role == "suspense" and pay.refs is None:
                    row.debit_minor = booked_bank
            posting.rows = [x for x in posting.rows if x.role != "fx"]
            applied = sum(x.debit_minor for x in posting.rows if x.role in ("ap_clear", "suspense"))
            fx_row = fx_balancing_row(w, pay, booked_bank, applied)
            if fx_row is not None:
                posting.rows.append(fx_row)
            self.booked_payment_rate[pay.key] = rate
            self.used.add(pay.key)
            correct_day = w.accounting_date(pay.timestamp)
            return InjectedIssue(
                type="fx_rate", affected=[pay.key], amount_minor=abs(delta),
                evidence_sets=[[("doc", pay.key), ("row", bank_row.key), ("fx", correct_day.isoformat(), pay.currency)]],
                scenario=scenario,
                cause=(f"Payment {pay.key} was translated at the {day.isoformat()} rate ({cause}) instead of the "
                       f"{correct_day.isoformat()} policy rate; Bank misstated by {abs(delta)}."),
                details={"payment": pay.key, "wrong_rate_date": day.isoformat(), "wrong_rate_cause": cause,
                         "rows_before": before, "rows_after": _snapshot(posting.rows)},
            )
        raise GenerationError("no payment available for an fx_rate error")

    # ------------------------------------------------------------------ type 4
    def period_attribution(self, r: DeterministicRng) -> InjectedIssue:
        """A document from the adjacent period is posted into this period.

        Cause: the posting period was derived from the UTC date of the document timestamp
        instead of the local date in the company timezone. Positive offsets pull early-morning
        documents of the NEXT month in; negative offsets pull late-evening documents of the
        PREVIOUS month in.
        """
        w = self.world
        if w.offset_minutes == 0:
            raise GenerationError("period_attribution via UTC dating needs a non-zero company offset")
        first = "invoice" if r.chance(1, 2) else "payment"
        for kind in (first, "payment" if first == "invoice" else "invoice"):
            try:
                return self._period_invoice(r) if kind == "invoice" else self._period_payment(r)
            except GenerationError:
                continue
        raise GenerationError("cannot place a period_attribution error")

    def _adjacent_moment(self, r: DeterministicRng):
        from ophanim.generator.history import utc_date_shift_time

        w = self.world
        day = w.period_end + timedelta(days=1) if w.offset_minutes > 0 else w.period_start - timedelta(days=1)
        return utc_date_shift_time(r, day, w.offset_minutes)

    def _period_invoice(self, r: DeterministicRng) -> InjectedIssue:
        from ophanim.generator.history import make_lines, new_invoice

        w = self.world
        suppliers = [w.suppliers[k] for k in sorted(w.suppliers) if not w.suppliers[k].recurring] or \
                    [w.suppliers[k] for k in sorted(w.suppliers)]
        s = r.choice(suppliers)
        category = next(c for c in PROFILES[w.profile_name].categories if c.name == s.category)
        moment = self._adjacent_moment(r)
        origin = "next" if w.offset_minutes > 0 else "prior"
        inv = new_invoice(w, r, s, moment, make_lines(r, category, s.currency, None), origin)
        posting = post_invoice(w, inv)
        w.postings.append(posting)
        self.used.add(inv.key)
        amount = self._row(posting, "ap").credit_minor
        return InjectedIssue(
            type="period_attribution", affected=[inv.key], amount_minor=amount,
            evidence_sets=[[("doc", inv.key), ("row", self._row(posting, "ap").key)],
                           [("doc", inv.key), ("row", self._row(posting, "expense").key)]],
            scenario="single",
            cause=(f"Invoice {inv.key} dated {w.accounting_date(moment).isoformat()} (company time) was assigned to "
                   f"this period from its UTC date {moment.astimezone(timezone.utc).date().isoformat()}."),
            details={"invoice": inv.key, "local_date": w.accounting_date(moment).isoformat(),
                     "utc_date": moment.astimezone(timezone.utc).date().isoformat(),
                     "rows_added": _snapshot(posting.rows)},
        )

    def _period_payment(self, r: DeterministicRng) -> InjectedIssue:
        from ophanim.generator.history import make_lines, new_invoice, new_payment
        from ophanim.generator.model import Allocation
        from ophanim.generator.posting import post_payment

        w = self.world
        moment = self._adjacent_moment(r)
        if w.offset_minutes > 0:
            # Next-month payment settling an open invoice of this period.
            referenced = {a.invoice_key for p in w.payments.values() for a in (p.refs or [])}
            pool = [i for i in self._posted_period_invoices() if i.key not in referenced]
            if not pool:
                raise GenerationError("no open invoice for an adjacent payment")
            inv = r.choice(pool)
        else:
            # Previous-month payment settling an older invoice from that month.
            suppliers = [w.suppliers[k] for k in sorted(w.suppliers) if not w.suppliers[k].recurring] or \
                        [w.suppliers[k] for k in sorted(w.suppliers)]
            s = r.choice(suppliers)
            category = next(c for c in PROFILES[w.profile_name].categories if c.name == s.category)
            issued = moment - timedelta(days=r.randint(5, 20))
            inv = new_invoice(w, r, s, issued, make_lines(r, category, s.currency, None), "prior")
        pay = new_payment(w, inv.supplier_key, moment, inv.currency, inv.total_minor,
                          [Allocation(inv.key, inv.total_minor)], origin="adjacent")
        posting = post_payment(w, pay)
        w.postings.append(posting)
        self.used.update({pay.key, inv.key})
        bank = self._row(posting, "bank")
        return InjectedIssue(
            type="period_attribution", affected=[pay.key], amount_minor=bank.credit_minor,
            evidence_sets=[[("doc", pay.key), ("row", bank.key)]],
            scenario="single",
            cause=(f"Payment {pay.key} made on {w.accounting_date(moment).isoformat()} (company time) was assigned "
                   f"to this period from its UTC date {moment.astimezone(timezone.utc).date().isoformat()}."),
            details={"payment": pay.key, "invoice": inv.key, "local_date": w.accounting_date(moment).isoformat(),
                     "utc_date": moment.astimezone(timezone.utc).date().isoformat(),
                     "rows_added": _snapshot(posting.rows)},
        )

    # ------------------------------------------------------------------ interacting scenarios
    def scenario_fx_partial_payment_boundary(self, r: DeterministicRng, carrier: dict) -> list[InjectedIssue]:
        """S1. One root cause (the payment system dates rates by UTC) plus one handling slip.

        The two-line foreign payment sits at the period boundary; its UTC date falls in the
        adjacent month. (a) Bank is translated at the UTC-date rate -> fx_rate on the payment.
        (b) One remittance line is parked in Suspense at that wrong rate -> payment_allocation.
        The allocation misstatement is the AP left open, valued at the INVOICE's policy rate:
        neither the Suspense amount nor the (wrong) payment rate gives the right answer.
        """
        name = "fx_partial_payment_boundary"
        fx_issue = self.fx_rate_payment(r, payment_key=carrier["payment"], force="utc_date", scenario=name)
        line = r.choice(carrier["invoices"])
        alloc_issue = self.payment_allocation(r, payment_key=carrier["payment"], invoice_key=line, scenario=name)
        return [fx_issue, alloc_issue]

    def scenario_fx_invoice_unapplied_payment(self, r: DeterministicRng, carrier: dict) -> list[InjectedIssue]:
        """S2. A foreign invoice booked at a wrong-date rate, and its payment line left unapplied.

        The allocation misstatement must be valued at the invoice's POLICY rate, not at the
        rate implied by its (wrong) AP posting, so the fx_rate error changes the right answer
        for the payment_allocation error.
        """
        name = "fx_invoice_unapplied_payment"
        (invoice_key,) = carrier["invoices"]
        fx_issue = self.fx_rate_invoice(r, invoice_key=invoice_key, scenario=name)
        alloc_issue = self.payment_allocation(r, payment_key=carrier["payment"], invoice_key=invoice_key, scenario=name)
        return [fx_issue, alloc_issue]
