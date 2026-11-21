"""Load the public dataset from files or from in-memory tables (stdlib only)."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

LEDGER_COLUMNS = ("row_id", "timestamp", "account", "debit_minor", "credit_minor", "currency", "entity_id", "invoice_id", "payment_id")
FX_COLUMNS = ("date", "source_currency", "target_currency", "rate")
_LEDGER_INT = ("debit_minor", "credit_minor")
_LEDGER_NULLABLE = ("entity_id", "invoice_id", "payment_id")


class DatasetError(ValueError):
    pass


@dataclass
class PublicDataset:
    manifest: dict
    policy: dict
    ledger: list[dict]
    invoices: list[dict]
    payments: list[dict]
    fx: list[dict]

    # ------------------------------------------------------------------ constructors
    @classmethod
    def from_tables(cls, manifest: dict, policy: dict, tables: dict[str, list[dict]]) -> "PublicDataset":
        return cls(manifest=manifest, policy=policy, ledger=list(tables["ledger"]), invoices=list(tables["invoices"]),
                   payments=list(tables["payments"]), fx=list(tables["fx"]))

    @classmethod
    def from_directory(cls, directory: str | Path) -> "PublicDataset":
        d = Path(directory)
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        policy = json.loads((d / "policy.json").read_text(encoding="utf-8"))
        ledger = _read_ledger(d / "ledger.csv")
        invoices = _read_jsonl(d / "invoices.jsonl")
        payments = _read_jsonl(d / "payments.jsonl")
        fx = _read_fx(d / "fx.csv")
        return cls(manifest=manifest, policy=policy, ledger=ledger, invoices=invoices, payments=payments, fx=fx)

    # ------------------------------------------------------------------ indexes
    def fx_key(self, row: dict) -> str:
        return f"{row['date']}:{row['source_currency']}:{row['target_currency']}"

    def records_by_evidence_id(self) -> dict[str, tuple[str, dict]]:
        """Map every citable id (row_id, doc_id, FX key) to (kind, record)."""
        out: dict[str, tuple[str, dict]] = {}
        for r in self.ledger:
            out[r["row_id"]] = ("ledger", r)
        for d in self.invoices:
            out[d["doc_id"]] = ("invoice", d)
        for d in self.payments:
            out[d["doc_id"]] = ("payment", d)
        for r in self.fx:
            out[self.fx_key(r)] = ("fx", r)
        return out


def _read_ledger(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = tuple(next(reader))
        if header != LEDGER_COLUMNS:
            raise DatasetError(f"ledger.csv header {header} != {LEDGER_COLUMNS}")
        rows = []
        for raw in reader:
            row = dict(zip(header, raw))
            for c in _LEDGER_INT:
                row[c] = int(row[c])
            for c in _LEDGER_NULLABLE:
                if row[c] == "null":
                    row[c] = None
            rows.append(row)
        return rows


def _read_fx(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = tuple(next(reader))
        if header != FX_COLUMNS:
            raise DatasetError(f"fx.csv header {header} != {FX_COLUMNS}")
        return [dict(zip(header, raw)) for raw in reader]


def _read_jsonl(path: Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
