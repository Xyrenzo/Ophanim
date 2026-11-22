"""Financial DNA: company profiles.

A profile changes the *shape* of the business (volumes, currencies, invoice
sizes, recurring spend, payment habits). Profiles never add error types; the
mandatory error types are configured only through EpisodeConfig.errors.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    name: str
    expense_account: str
    descriptions: tuple[str, ...]
    unit_price_usd_cents: tuple[int, int]
    quantity: tuple[int, int]


@dataclass(frozen=True)
class Profile:
    name: str
    label: str
    base_currencies: tuple[str, ...]
    foreign_currencies: tuple[str, ...]
    foreign_supplier_pct: int
    offsets_minutes: tuple[int, ...]
    categories: tuple[Category, ...]
    recurring_pct: int
    terms_days: tuple[int, ...]


_OFFSETS = (300, 330, 360, 540, 180, 60, -300, -180)  # +05:00 +05:30 +06:00 +09:00 +03:00 +01:00 -05:00 -03:00

PROFILES: dict[str, Profile] = {
    "retail": Profile(
        name="retail",
        label="Small retail company",
        base_currencies=("KZT", "USD", "EUR"),
        foreign_currencies=("USD", "EUR", "CNY"),
        foreign_supplier_pct=25,
        offsets_minutes=_OFFSETS,
        categories=(
            Category("goods", "5100", ("Assorted merchandise", "Seasonal stock", "Packaging materials", "Shelf goods"), (200, 6000), (5, 60)),
            Category("utilities", "6300", ("Electricity", "Water and heating", "Waste collection"), (5000, 60000), (1, 1)),
            Category("rent", "6400", ("Store rent",), (150000, 600000), (1, 1)),
            Category("services", "6500", ("Cleaning services", "Security services", "POS maintenance"), (3000, 40000), (1, 4)),
        ),
        recurring_pct=30,
        terms_days=(14, 30),
    ),
    "trading": Profile(
        name="trading",
        label="International trading company",
        base_currencies=("USD", "EUR", "KWD"),
        foreign_currencies=("EUR", "USD", "CNY", "JPY", "GBP", "AED"),
        foreign_supplier_pct=60,
        offsets_minutes=_OFFSETS,
        categories=(
            Category("goods", "5100", ("Container of electronics", "Bulk textiles", "Industrial fasteners", "Spare parts lot"), (5000, 300000), (1, 40)),
            Category("freight", "6200", ("Ocean freight", "Air freight", "Customs brokerage", "Port handling"), (20000, 400000), (1, 3)),
            Category("insurance", "6600", ("Cargo insurance",), (10000, 150000), (1, 1)),
            Category("services", "6500", ("Inspection services", "Trade finance fees"), (5000, 90000), (1, 2)),
        ),
        recurring_pct=15,
        terms_days=(30, 45, 60),
    ),
    "software": Profile(
        name="software",
        label="Software services company",
        base_currencies=("USD", "GBP", "JPY"),
        foreign_currencies=("USD", "EUR", "GBP", "SGD", "JPY"),
        foreign_supplier_pct=40,
        offsets_minutes=_OFFSETS,
        categories=(
            Category("cloud", "6100", ("Cloud compute", "Managed database", "Object storage", "CDN traffic"), (2000, 500000), (1, 10)),
            Category("subscriptions", "6110", ("Team licenses", "Monitoring subscription", "Design tool seats"), (1000, 9000), (3, 50)),
            Category("contractors", "6300", ("Contract development", "Security audit", "QA services"), (4000, 15000), (8, 160)),
            Category("rent", "6400", ("Office rent", "Coworking desks"), (80000, 400000), (1, 1)),
        ),
        recurring_pct=45,
        terms_days=(14, 30),
    ),
    "manufacturing": Profile(
        name="manufacturing",
        label="Manufacturing company",
        base_currencies=("EUR", "KZT", "CHF"),
        foreign_currencies=("EUR", "USD", "CNY", "CHF", "JPY"),
        foreign_supplier_pct=45,
        offsets_minutes=_OFFSETS,
        categories=(
            Category("materials", "5100", ("Steel coil", "Aluminium billets", "Polymer granules", "Copper wire"), (3000, 90000), (10, 200)),
            Category("components", "5200", ("Bearings", "Control boards", "Hydraulic valves", "Fasteners kit"), (500, 25000), (20, 400)),
            Category("maintenance", "6700", ("Machine maintenance", "Calibration service", "Spare tooling"), (20000, 300000), (1, 3)),
            Category("utilities", "6300", ("Industrial electricity", "Gas supply", "Water treatment"), (50000, 500000), (1, 1)),
        ),
        recurring_pct=20,
        terms_days=(30, 45, 60),
    ),
    "logistics": Profile(
        name="logistics",
        label="Logistics company",
        base_currencies=("USD", "AED", "SGD"),
        foreign_currencies=("USD", "EUR", "AED", "SGD", "CNY"),
        foreign_supplier_pct=50,
        offsets_minutes=_OFFSETS,
        categories=(
            Category("fuel", "5300", ("Diesel fuel", "Jet fuel surcharge", "Fleet fuel cards"), (5000, 200000), (1, 20)),
            Category("subcontract", "5400", ("Line-haul subcontract", "Last-mile delivery", "Warehouse handling"), (10000, 250000), (1, 12)),
            Category("tolls", "6800", ("Road tolls", "Port dues", "Terminal fees"), (1000, 60000), (1, 30)),
            Category("leasing", "6400", ("Truck lease", "Warehouse lease"), (100000, 900000), (1, 1)),
        ),
        recurring_pct=25,
        terms_days=(14, 30, 45),
    ),
    "consulting": Profile(
        name="consulting",
        label="Consulting company",
        base_currencies=("GBP", "EUR", "USD"),
        foreign_currencies=("USD", "EUR", "GBP", "CHF", "SGD"),
        foreign_supplier_pct=35,
        offsets_minutes=_OFFSETS,
        categories=(
            Category("subcontractors", "6300", ("Associate consultant days", "Expert interviews", "Translation services"), (40000, 150000), (1, 20)),
            Category("travel", "6900", ("Flights", "Hotel stay", "Ground transport"), (5000, 120000), (1, 6)),
            Category("software", "6110", ("Analytics licenses", "Survey platform", "Research database"), (2000, 50000), (1, 25)),
            Category("rent", "6400", ("Office rent",), (200000, 800000), (1, 1)),
        ),
        recurring_pct=35,
        terms_days=(14, 30),
    ),
}

# Tuned to the lower end of the suggested ranges (about 200-2,000 ledger rows,
# 20-200 documents) so that a full scan still fits comfortably in 100 steps.
# Published small episodes have slightly fewer than 200 rows and the largest
# slightly more than 200 documents (measured sizes: docs/data_model.md).
SIZE_RANGES: dict[str, dict[str, tuple[int, int]]] = {
    "small": {"suppliers": (6, 9), "period_invoices": (34, 42), "prior_invoices": (6, 9)},
    "medium": {"suppliers": (9, 14), "period_invoices": (55, 72), "prior_invoices": (10, 14)},
    "large": {"suppliers": (13, 20), "period_invoices": (80, 98), "prior_invoices": (14, 18)},
}
