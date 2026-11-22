"""Generate a consistent hidden accounts-payable history for one period.

Everything produced here is *correct* bookkeeping. Errors are injected later by
``injectors.py`` as explicit causal transformations.

Legitimate red herrings planted here (recorded in ``world.distractors``):
  * recurring monthly invoices with identical amounts (different vendor_ref)
  * repeat orders: same supplier, same lines and amount, different vendor_ref
  * the same vendor_ref used by two *different* suppliers
  * a duplicate capture that was reversed within the period (net zero)
  * split payments, partial payments, one payment covering several invoices
  * payments without remittance information parked in Suspense
  * documents whose UTC date differs from their local accounting date,
    including at the period boundary
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal

from ophanim.generator.model import Allocation, GenerationError, Invoice, LineItem, Payment, Supplier, World
from ophanim.generator.profiles import PROFILES, SIZE_RANGES, Category, Profile
from ophanim.money import USD_VALUE, normalize_rate, to_minor
from ophanim.rng import DeterministicRng
from ophanim.schemas import EpisodeConfig
from ophanim.timeutil import local_datetime

FX_DAYS_BEFORE = 50  # prior-period invoices are at most 45 days old
FX_DAYS_AFTER = 10

_DISTRACTOR_LEVEL = {"low": 0, "normal": 1, "high": 2}


# --------------------------------------------------------------------------- times
def business_time(r: DeterministicRng, day: date, offset: int) -> datetime:
    return local_datetime(day, r.randint(8, 18), r.randint(0, 59), r.randint(0, 59), offset)


def utc_date_shift_time(r: DeterministicRng, day: date, offset: int) -> datetime:
    """A local time on ``day`` whose UTC calendar date is a different day.

    Positive offsets: early morning (UTC is still the previous day).
    Negative offsets: late evening (UTC is already the next day).
    """
    hours = abs(offset) // 60
    if hours == 0:
        return business_time(r, day, offset)
    if offset > 0:
        return local_datetime(day, r.randint(0, hours - 1), r.randint(0, 59), r.randint(0, 59), offset)
    return local_datetime(day, r.randint(24 - hours, 23), r.randint(0, 59), r.randint(0, 59), offset)


def doc_time(r: DeterministicRng, day: date, offset: int, odd_pct: int) -> datetime:
    if r.chance(odd_pct, 100):
        return utc_date_shift_time(r, day, offset)
    return business_time(r, day, offset)


# --------------------------------------------------------------------------- amounts
def usd_cents_to_minor(cents: int, currency: str) -> int:
    value = Decimal(cents) / Decimal(100) / USD_VALUE[currency]
    return max(1, to_minor(value, currency))


def make_lines(r: DeterministicRng, category: Category, currency: str, service_period: str | None) -> list[LineItem]:
    count = 1 if category.quantity == (1, 1) else r.randint(1, 3)
    lines = []
    for _ in range(count):
        lines.append(
            LineItem(
                description=r.choice(category.descriptions),
                quantity=r.randint(*category.quantity),
                unit_price_minor=usd_cents_to_minor(r.randint(*category.unit_price_usd_cents), currency),
                service_period=service_period,
            )
        )
    return lines


def _month_label(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _prev_month_same_day(day: date) -> date:
    year, month = (day.year - 1, 12) if day.month == 1 else (day.year, day.month - 1)
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


# --------------------------------------------------------------------------- builder
class HistoryBuilder:
    def __init__(self, rng: DeterministicRng, config: EpisodeConfig) -> None:
        self.rng = rng
        self.config = config
        self.level = _DISTRACTOR_LEVEL[config.distractors]

    def build(self) -> World:
        r = self.rng.child("profile")
        profile_name = self.config.profile if self.config.profile != "auto" else r.choice(sorted(PROFILES))
        profile = PROFILES[profile_name]
        base = r.choice(profile.base_currencies)
        offset = r.choice(profile.offsets_minutes)
        year, month = r.randint(2025, 2026), r.randint(1, 12)
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        world = World(profile_name=profile.name, base_currency=base, offset_minutes=offset, period_start=start, period_end=end)
        self.profile = profile
        self.world = world
        self._build_fx(self.rng.child("fx"))
        self._build_suppliers(self.rng.child("suppliers"))
        self._build_invoices(self.rng.child("invoices"))
        self._build_payments(self.rng.child("payments"))
        self._plant_document_distractors(self.rng.child("distractors"))
        self._guarantee_split_payment(self.rng.child("split_guarantee"))
        self._plant_refund(self.rng.child("refunds"))
        return world

    # ------------------------------------------------------------------ fx
    def _build_fx(self, r: DeterministicRng) -> None:
        w = self.world
        w.fx_start = w.period_start - timedelta(days=FX_DAYS_BEFORE)
        w.fx_end = w.period_end + timedelta(days=FX_DAYS_AFTER)
        w.fx_currencies = sorted(c for c in self.profile.foreign_currencies if c != w.base_currency)
        days = (w.fx_end - w.fx_start).days + 1
        for currency in w.fx_currencies:
            cr = r.child(currency)
            rate = USD_VALUE[currency] / USD_VALUE[w.base_currency]
            rate = rate * (Decimal(1) + Decimal(cr.randint(-300, 300)) / Decimal(10000))
            for i in range(days):
                day = w.fx_start + timedelta(days=i)
                # Daily move of 0.05%-0.60% in either direction: consecutive days
                # always differ, so a wrong-date rate is always a real discrepancy.
                step = cr.randint(5, 60) * (1 if cr.chance(1, 2) else -1)
                rate = rate * (Decimal(1) + Decimal(step) / Decimal(10000))
                w.fx[(day, currency)] = normalize_rate(rate)

    # ------------------------------------------------------------------ suppliers
    def _build_suppliers(self, r: DeterministicRng) -> None:
        w, p = self.world, self.profile
        n = r.randint(*SIZE_RANGES[self.config.size]["suppliers"])
        foreign_options = w.fx_currencies
        for i in range(n):
            category = r.choice(p.categories)
            # The first two suppliers are always foreign so every episode has FX activity
            # (clean and erroneous episodes alike - no structural tell).
            foreign = bool(foreign_options) and (i < 2 or r.chance(p.foreign_supplier_pct, 100))
            currency = r.choice(foreign_options) if foreign else w.base_currency
            recurring = category.quantity == (1, 1) or category.name in ("subscriptions", "cloud")
            recurring = recurring and r.chance(p.recurring_pct + 30, 100)
            supplier = Supplier(
                key=f"S{i + 1:02d}",
                currency=currency,
                doc_offset_minutes=r.choice((w.offset_minutes, w.offset_minutes, 0, 60, 120, 480, -300)),
                expense_account=category.expense_account,
                category=category.name,
                ref_prefix=r.choice(("INV-", "SI", "A/", "F", "BILL-", "No.")),
                next_ref=r.randint(100, 9000),
                terms_days=r.choice(p.terms_days),
                recurring=recurring,
            )
            w.suppliers[supplier.key] = supplier

    def _category(self, supplier: Supplier) -> Category:
        for c in self.profile.categories:
            if c.name == supplier.category:
                return c
        raise GenerationError("unknown category")

    def _next_ref(self, r: DeterministicRng, supplier: Supplier) -> str:
        supplier.next_ref += r.randint(1, 7)
        return f"{supplier.ref_prefix}{supplier.next_ref}"

    def _new_invoice(self, r, supplier, issued_at, lines, origin) -> Invoice:
        w = self.world
        inv = Invoice(
            key=w.new_invoice_key(),
            supplier_key=supplier.key,
            vendor_ref=self._next_ref(r, supplier),
            issued_at=issued_at,
            due_at=issued_at + timedelta(days=supplier.terms_days),
            currency=supplier.currency,
            lines=lines,
            origin=origin,
        )
        w.invoices[inv.key] = inv
        return inv

    # ------------------------------------------------------------------ invoices
    def _build_invoices(self, r: DeterministicRng) -> None:
        w = self.world
        sizes = SIZE_RANGES[self.config.size]
        suppliers = [w.suppliers[k] for k in sorted(w.suppliers)]
        period_days = (w.period_end - w.period_start).days + 1
        odd_pct = 4 + 4 * self.level

        # Recurring suppliers: one invoice this month and one last month (same amount).
        for s in suppliers:
            if not s.recurring:
                continue
            category = self._category(s)
            day = w.period_start + timedelta(days=r.randint(0, 4))
            lines = make_lines(r, category, s.currency, None)
            this_inv = self._new_invoice(r, s, business_time(r, day, w.offset_minutes), [
                LineItem(l.description, l.quantity, l.unit_price_minor, _month_label(day)) for l in lines
            ], "period")
            prev_day = _prev_month_same_day(day)
            prev_inv = self._new_invoice(r, s, business_time(r, prev_day, w.offset_minutes), [
                LineItem(l.description, l.quantity, l.unit_price_minor, _month_label(prev_day)) for l in lines
            ], "prior")
            w.distractors.append({
                "kind": "recurring_same_amount",
                "invoices": [prev_inv.key, this_inv.key],
                "note": "Monthly recurring invoice: same supplier, lines and amount; different vendor_ref and service period.",
            })

        target = r.randint(*sizes["period_invoices"])
        already = sum(1 for i in w.invoices.values() if i.origin == "period")
        weights = [1 if s.recurring else 4 for s in suppliers]
        for _ in range(max(0, target - already)):
            s = r.weighted_choice(suppliers, weights)
            day = w.period_start + timedelta(days=r.randint(0, period_days - 1))
            self._new_invoice(r, s, doc_time(r, day, w.offset_minutes, odd_pct), make_lines(r, self._category(s), s.currency, None), "period")

        # Boundary red herring (D05): a legitimate in-period FOREIGN-currency invoice whose UTC date is in the
        # adjacent month. Correct treatment needs the company-time accounting date for both the period and
        # the FX rate (the rate of the UTC date would be wrong).
        if w.offset_minutes != 0 and self.level >= 1:
            foreign = [x for x in suppliers if x.currency != w.base_currency]
            s = r.choice([x for x in foreign if not x.recurring] or foreign or suppliers)
            day = w.period_start if w.offset_minutes > 0 else w.period_end
            inv = self._new_invoice(r, s, utc_date_shift_time(r, day, w.offset_minutes), make_lines(r, self._category(s), s.currency, None), "period")
            w.distractors.append({"kind": "boundary_utc_date", "invoices": [inv.key],
                                  "note": "Issued inside the period in company time; its UTC date falls in the adjacent month."})

        # Open invoices from the previous period, paid during this period.
        prior_target = r.randint(*sizes["prior_invoices"])
        prior_now = sum(1 for i in w.invoices.values() if i.origin == "prior")
        non_recurring = [s for s in suppliers if not s.recurring] or suppliers
        for _ in range(max(0, prior_target - prior_now)):
            s = r.choice(non_recurring)
            day = w.period_start - timedelta(days=r.randint(5, 45))
            self._new_invoice(r, s, business_time(r, day, w.offset_minutes), make_lines(r, self._category(s), s.currency, None), "prior")

    # ------------------------------------------------------------------ payments
    def _new_payment(self, supplier_key, moment, currency, amount, refs) -> Payment:
        w = self.world
        pay = Payment(key=w.new_payment_key(), supplier_key=supplier_key, timestamp=moment, currency=currency,
                      amount_minor=amount, refs=refs, origin="period")
        w.payments[pay.key] = pay
        return pay

    def _pay_day(self, r: DeterministicRng, inv: Invoice, min_gap: int = 1) -> date | None:
        w = self.world
        first = max(w.accounting_date(inv.issued_at) + timedelta(days=min_gap), w.period_start)
        if first > w.period_end:
            return None
        return first + timedelta(days=r.randint(0, (w.period_end - first).days))

    def _build_payments(self, r: DeterministicRng) -> None:
        w = self.world
        off = w.offset_minutes
        odd_pct = 4 + 4 * self.level
        invoices = [w.invoices[k] for k in sorted(w.invoices)]
        batch_pool: dict[tuple[str, str], list[Invoice]] = {}

        for inv in invoices:
            if inv.origin == "prior":
                mode = r.weighted_choice(["full", "split", "partial"], [60, 25, 15])
            else:
                mode = r.weighted_choice(["unpaid", "full", "split", "partial", "batch"], [35, 35, 10, 10, 10])
            total = inv.total_minor
            if mode == "unpaid":
                continue
            if mode == "batch":
                batch_pool.setdefault((inv.supplier_key, inv.currency), []).append(inv)
                continue
            if mode == "split" and total >= 2:
                d1 = self._pay_day(r, inv)
                if d1 is None:
                    continue
                d2_first = d1 + timedelta(days=1)
                if d2_first <= w.period_end:
                    d2 = d2_first + timedelta(days=r.randint(0, (w.period_end - d2_first).days))
                    a1 = total * r.randint(30, 70) // 100
                    a1 = min(max(a1, 1), total - 1)
                    p1 = self._new_payment(inv.supplier_key, doc_time(r, d1, off, odd_pct), inv.currency, a1, [Allocation(inv.key, a1)])
                    p2 = self._new_payment(inv.supplier_key, doc_time(r, d2, off, odd_pct), inv.currency, total - a1, [Allocation(inv.key, total - a1)])
                    w.distractors.append({"kind": "split_payment", "invoices": [inv.key], "payments": [p1.key, p2.key],
                                          "note": "One invoice settled by two payments; both fully applied."})
                    continue
                mode = "full"
            day = self._pay_day(r, inv)
            if day is None:
                continue
            if mode == "partial" and total >= 2:
                amount = min(max(total * r.randint(30, 80) // 100, 1), total - 1)
                p = self._new_payment(inv.supplier_key, doc_time(r, day, off, odd_pct), inv.currency, amount, [Allocation(inv.key, amount)])
                w.distractors.append({"kind": "partial_payment", "invoices": [inv.key], "payments": [p.key],
                                      "note": "Payment covers part of the invoice; fully applied; remainder legitimately open."})
            else:
                self._new_payment(inv.supplier_key, doc_time(r, day, off, odd_pct), inv.currency, total, [Allocation(inv.key, total)])

        # One payment covering several invoices of the same supplier and currency.
        for key in sorted(batch_pool):
            group = batch_pool[key]
            if len(group) < 2:
                for inv in group:
                    day = self._pay_day(r, inv)
                    if day is not None:
                        self._new_payment(inv.supplier_key, doc_time(r, day, off, odd_pct), inv.currency, inv.total_minor,
                                          [Allocation(inv.key, inv.total_minor)])
                continue
            for start in range(0, len(group), 3):
                chunk = group[start:start + 3]
                latest = max(chunk, key=lambda i: (w.accounting_date(i.issued_at), i.key))
                day = self._pay_day(r, latest)
                if day is None:
                    continue
                refs = [Allocation(i.key, i.total_minor) for i in chunk]
                p = self._new_payment(key[0], doc_time(r, day, off, odd_pct), key[1], sum(a.amount_minor for a in refs), refs)
                if len(chunk) > 1:
                    w.distractors.append({"kind": "batch_payment", "invoices": [i.key for i in chunk], "payments": [p.key],
                                          "note": "One payment settles several invoices; every remittance line applied."})

        # Payments without remittance information: legitimately parked in Suspense.
        n_unidentified = r.randint(self.level, 1 + self.level)
        suppliers = [w.suppliers[k] for k in sorted(w.suppliers)]
        for _ in range(n_unidentified):
            s = r.choice(suppliers)
            day = w.period_start + timedelta(days=r.randint(0, (w.period_end - w.period_start).days))
            amount = usd_cents_to_minor(r.randint(5000, 200000), s.currency)
            p = self._new_payment(s.key, doc_time(r, day, off, odd_pct), s.currency, amount, None)
            w.distractors.append({"kind": "unidentified_payment", "payments": [p.key],
                                  "note": "No remittance information; correctly posted to Suspense pending identification."})

    # ------------------------------------------------------------------ document distractors
    def _plant_document_distractors(self, r: DeterministicRng) -> None:
        w = self.world
        period_invoices = [w.invoices[k] for k in sorted(w.invoices) if w.invoices[k].origin == "period"]
        unpaid = [i for i in period_invoices if not self._is_referenced(i.key)]

        # Repeat order: same supplier, same lines and amount, different vendor_ref.
        if self.level >= 1 and period_invoices:
            src = r.choice(period_invoices)
            s = w.suppliers[src.supplier_key]
            day = w.period_start + timedelta(days=r.randint(0, (w.period_end - w.period_start).days))
            twin = self._new_invoice(r, s, business_time(r, day, w.offset_minutes),
                                     [LineItem(l.description, l.quantity, l.unit_price_minor, l.service_period) for l in src.lines], "period")
            w.distractors.append({"kind": "repeat_order_same_amount", "invoices": [src.key, twin.key],
                                  "note": "Same supplier and amount, different vendor_ref and date: two genuine orders."})

        # Same vendor_ref used by two different suppliers.
        by_supplier: dict[str, list[Invoice]] = {}
        for inv in period_invoices:
            by_supplier.setdefault(inv.supplier_key, []).append(inv)
        if self.level >= 1 and len(by_supplier) >= 2:
            a_sup, b_sup = r.sample(sorted(by_supplier), 2)
            a = r.choice(by_supplier[a_sup])
            b = r.choice(by_supplier[b_sup])
            clash = any(i.vendor_ref == a.vendor_ref for i in w.invoices.values() if i.supplier_key == b_sup)
            if not clash:
                b.vendor_ref = a.vendor_ref
                w.distractors.append({"kind": "vendor_ref_collision", "invoices": [a.key, b.key],
                                      "note": "Two different suppliers happen to use the same invoice number."})

        # A duplicate capture that was reversed inside the period (net effect zero).
        n_reversed = 1 if self.level >= 1 else 0
        if self.level >= 2:
            n_reversed += r.randint(0, 1)
        candidates = [i for i in unpaid if w.accounting_date(i.issued_at) <= w.period_end - timedelta(days=2)]
        for src in r.sample(candidates, min(n_reversed, len(candidates))):
            copy = Invoice(key=w.new_invoice_key(), supplier_key=src.supplier_key, vendor_ref=src.vendor_ref,
                           issued_at=src.issued_at, due_at=src.due_at, currency=src.currency,
                           lines=[LineItem(l.description, l.quantity, l.unit_price_minor, l.service_period) for l in src.lines],
                           origin="reversed_copy")
            w.invoices[copy.key] = copy
            first = w.accounting_date(src.issued_at) + timedelta(days=1)
            rev_day = first + timedelta(days=r.randint(0, (w.period_end - first).days))
            w.reversals[copy.key] = business_time(r, rev_day, w.offset_minutes)
            w.distractors.append({"kind": "reversed_duplicate", "invoices": [src.key, copy.key],
                                  "note": "Captured twice, then the second capture was reversed in the same period."})

    # ------------------------------------------------------------------ guaranteed red herrings (D02, D03)
    def _guarantee_split_payment(self, r: DeterministicRng) -> None:
        """D02: at distractor levels normal/high there is always at least one legitimately split invoice."""
        w = self.world
        if self.level < 1 or any(d["kind"] == "split_payment" for d in w.distractors):
            return
        off = w.offset_minutes
        suppliers = [w.suppliers[k] for k in sorted(w.suppliers)]
        s = r.choice([x for x in suppliers if not x.recurring] or suppliers)
        days = (w.period_end - w.period_start).days + 1
        inv_day = w.period_start + timedelta(days=r.randint(0, max(0, days - 3)))
        lines = make_lines(r, self._category(s), s.currency, None)
        if sum(l.amount_minor for l in lines) < 2:
            lines[0] = LineItem(lines[0].description, lines[0].quantity * 2, lines[0].unit_price_minor, lines[0].service_period)
        inv = self._new_invoice(r, s, business_time(r, inv_day, off), lines, "period")
        total = inv.total_minor
        d1 = inv_day + timedelta(days=1)
        d2 = d1 + timedelta(days=r.randint(1, max(1, (w.period_end - d1).days))) if d1 < w.period_end else d1
        a1 = min(max(total * r.randint(30, 70) // 100, 1), total - 1)
        p1 = self._new_payment(s.key, business_time(r, d1, off), s.currency, a1, [Allocation(inv.key, a1)])
        p2 = self._new_payment(s.key, business_time(r, d2, off), s.currency, total - a1, [Allocation(inv.key, total - a1)])
        w.distractors.append({"kind": "split_payment", "invoices": [inv.key], "payments": [p1.key, p2.key],
                              "note": "One invoice settled by two payments; both fully applied."})

    def _plant_refund(self, r: DeterministicRng) -> None:
        """D03: a correct supplier refund (guaranteed at distractor levels normal/high).

        The supplier returns in full a payment we made without remittance information (parked in Suspense).
        The refund is an inbound payment document (``direction = "inbound"``, ``refund_of`` = the original
        payment) posted Dr Bank / Cr Suspense; it is legitimate and must never be reported.
        """
        w = self.world
        if self.level < 1:
            return
        off = w.offset_minutes
        candidates = [p for _, p in sorted(w.payments.items()) if p.refs is None and p.direction == "outbound"
                      and p.origin == "period" and w.accounting_date(p.timestamp) < w.period_end]
        if not candidates:  # plant the item that will be refunded (same kind as the unidentified red herring)
            s = r.choice([w.suppliers[k] for k in sorted(w.suppliers)])
            day = w.period_start + timedelta(days=r.randint(0, max(0, (w.period_end - w.period_start).days - 1)))
            p = self._new_payment(s.key, business_time(r, day, off), s.currency,
                                  usd_cents_to_minor(r.randint(5000, 200000), s.currency), None)
            w.distractors.append({"kind": "unidentified_payment", "payments": [p.key],
                                  "note": "No remittance information; correctly posted to Suspense pending identification."})
            candidates = [p]
        original = r.choice(candidates)
        first = w.accounting_date(original.timestamp) + timedelta(days=1)
        day = first + timedelta(days=r.randint(0, (w.period_end - first).days))
        refund = self._new_payment(original.supplier_key, business_time(r, day, off), original.currency,
                                   original.amount_minor, None)
        refund.direction = "inbound"
        refund.refund_of = original.key
        w.distractors.append({"kind": "correct_refund", "payments": [original.key, refund.key],
                              "note": "The supplier returned an unidentified payment in full; posted Dr Bank / "
                                      "Cr Suspense (difference to FX). Correct treatment, not an error."})

    def _is_referenced(self, invoice_key: str) -> bool:
        for p in self.world.payments.values():
            if p.refs and any(a.invoice_key == invoice_key for a in p.refs):
                return True
        return False


def build_world(rng: DeterministicRng, config: EpisodeConfig) -> World:
    return HistoryBuilder(rng, config).build()


# --------------------------------------------------------------------------- shared document factories
def new_invoice(world: World, r: DeterministicRng, supplier: Supplier, issued_at: datetime,
                lines: list[LineItem], origin: str) -> Invoice:
    supplier.next_ref += r.randint(1, 7)
    inv = Invoice(key=world.new_invoice_key(), supplier_key=supplier.key,
                  vendor_ref=f"{supplier.ref_prefix}{supplier.next_ref}", issued_at=issued_at,
                  due_at=issued_at + timedelta(days=supplier.terms_days), currency=supplier.currency,
                  lines=lines, origin=origin)
    world.invoices[inv.key] = inv
    return inv


def new_payment(world: World, supplier_key: str, moment: datetime, currency: str, amount: int,
                refs: list[Allocation] | None, origin: str = "period") -> Payment:
    pay = Payment(key=world.new_payment_key(), supplier_key=supplier_key, timestamp=moment, currency=currency,
                  amount_minor=amount, refs=refs, origin=origin)
    world.payments[pay.key] = pay
    return pay


def substantial_lines(world: World, r: DeterministicRng, supplier: Supplier, minimum_base_minor: int = 100_000) -> list[LineItem]:
    """Lines whose base-currency value is large enough that a one-day rate move is clearly visible."""
    from ophanim.money import convert_minor

    category = next(c for c in PROFILES[world.profile_name].categories if c.name == supplier.category)
    lines = make_lines(r, category, supplier.currency, None)
    rate = USD_VALUE[supplier.currency] / USD_VALUE[world.base_currency]
    for _ in range(40):
        total = sum(l.amount_minor for l in lines)
        if convert_minor(total, supplier.currency, world.base_currency, normalize_rate(rate)) >= minimum_base_minor:
            break
        lines[0] = LineItem(lines[0].description, lines[0].quantity * 2, lines[0].unit_price_minor, lines[0].service_period)
    return lines


def plant_scenario_carriers(world: World, rng: DeterministicRng, config: EpisodeConfig) -> None:
    """Add CORRECT documents that the interacting scenarios will later corrupt.

    Planted before the clean snapshot, so the pre-mutation books contain them correctly
    posted. Uses its own random stream: the base history is unchanged.
    """
    w = world
    off = w.offset_minutes
    foreign = [w.suppliers[k] for k in sorted(w.suppliers) if w.suppliers[k].currency != w.base_currency]
    if (config.scenarios.fx_partial_payment_boundary or config.scenarios.fx_invoice_unapplied_payment) and not foreign:
        raise GenerationError("interacting scenarios need a foreign-currency supplier")
    days = (w.period_end - w.period_start).days + 1

    # S1: a two-line foreign payment at the period boundary, timed so its UTC date is in the adjacent month.
    for i in range(config.scenarios.fx_partial_payment_boundary):
        r = rng.child(f"s1/{i}")
        s = r.choice(foreign)
        if off > 0:
            pay_time = utc_date_shift_time(r, w.period_start, off)
            inv_days = [w.period_start - timedelta(days=r.randint(5, 20)) for _ in range(2)]
            origin = "prior"
        else:
            pay_time = utc_date_shift_time(r, w.period_end, off)
            inv_days = [w.period_start + timedelta(days=r.randint(0, days - 3)) for _ in range(2)]
            origin = "period"
        invs = [new_invoice(w, r, s, business_time(r, d, off), substantial_lines(w, r, s), origin) for d in inv_days]
        refs = [Allocation(inv.key, inv.total_minor) for inv in invs]
        pay = new_payment(w, s.key, pay_time, s.currency, sum(a.amount_minor for a in refs), refs)
        w.scenario_carriers.append({"scenario": "fx_partial_payment_boundary", "payment": pay.key,
                                    "invoices": [inv.key for inv in invs]})

    # S2: a foreign invoice paid later in the period by a payment that references it.
    for i in range(config.scenarios.fx_invoice_unapplied_payment):
        r = rng.child(f"s2/{i}")
        s = r.choice(foreign)
        inv_day = w.period_start + timedelta(days=r.randint(0, max(0, days - 6)))
        pay_day = inv_day + timedelta(days=r.randint(2, (w.period_end - inv_day).days))
        inv = new_invoice(w, r, s, business_time(r, inv_day, off), substantial_lines(w, r, s), "period")
        pay = new_payment(w, s.key, business_time(r, pay_day, off), s.currency, inv.total_minor,
                          [Allocation(inv.key, inv.total_minor)])
        w.scenario_carriers.append({"scenario": "fx_invoice_unapplied_payment", "payment": pay.key,
                                    "invoices": [inv.key]})

    # Explicit allocation mode (D09-D11): one correct carrier payment per requested allocation error.
    # missing -> a one-line payment (nothing will be applied); partial -> a two-line payment (one line
    # will stay applied, so 0 < applied < amount). "auto" keeps the historical random selection.
    mode = config.allocation_mode
    if mode != "auto":
        suppliers = [w.suppliers[k] for k in sorted(w.suppliers)]
        for i in range(config.errors.payment_allocation):
            r = rng.child(f"allocation/{mode}/{i}")
            s = r.choice(suppliers)
            category = next(c for c in PROFILES[w.profile_name].categories if c.name == s.category)
            n_lines = 1 if mode == "missing" else 2
            inv_days = [w.period_start + timedelta(days=r.randint(0, max(0, days - 4))) for _ in range(n_lines)]
            invs = [new_invoice(w, r, s, business_time(r, d, off), make_lines(r, category, s.currency, None), "period")
                    for d in inv_days]
            first = max(inv_days) + timedelta(days=1)
            pay_day = first + timedelta(days=r.randint(0, max(0, (w.period_end - first).days)))
            refs = [Allocation(inv.key, inv.total_minor) for inv in invs]
            pay = new_payment(w, s.key, business_time(r, pay_day, off), s.currency,
                              sum(a.amount_minor for a in refs), refs)
            w.scenario_carriers.append({"scenario": f"allocation_{mode}", "payment": pay.key,
                                        "invoices": [inv.key for inv in invs]})


def profile_for(world: World) -> Profile:
    return PROFILES[world.profile_name]
