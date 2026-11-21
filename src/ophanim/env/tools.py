"""Read-only investigation tools over the PUBLIC dataset only.

The toolbox is constructed from a PublicEpisode. It has no reference to the
truth, the provenance, the seed, the generator or the judge, so no tool call -
valid or malicious - can reach evaluator data. Every record returned is a
fresh deep copy; the agent cannot mutate environment state.

Errors use fixed codes and fixed messages; agent input is never echoed back.
"""

from __future__ import annotations

import base64
import copy
import re

from ophanim.env.calculator import CalculatorError, evaluate

TABLES = ("ledger", "invoices", "payments", "fx")
MAX_PAGE = 50
TABLE_KEYS = {"ledger": "row_id", "invoices": "invoice_id", "payments": "payment_id", "fx": "date:source_currency:target_currency"}

ERROR_MESSAGES = {
    "invalid_action": "Action must be a JSON object with a known 'action' and valid parameters.",
    "unknown_table": "Unknown table. Tables: ledger, invoices, payments, fx.",
    "invalid_cursor": "Cursor is not valid for this table.",
    "invalid_limit": "limit must be an integer between 1 and 50.",
    "unknown_id": "No record with that id in this table.",
    "unknown_document": "No document with that doc_id.",
    "invalid_expression": "Only numbers, + - * / and parentheses are allowed.",
    "number_too_long": "A number has too many digits (max 30).",
    "expression_too_long": "Expression is too long (max 256 characters).",
    "expression_too_complex": "Expression is too complex.",
    "division_by_zero": "Division by zero.",
    "result_out_of_range": "Result is out of the supported range.",
    "invalid_submission": "Findings failed schema validation; the episode is terminated.",
    "episode_finished": "The episode has ended; call reset().",
    "time_limit": "The time budget for this episode is exhausted.",
}

_CURSOR_RE = re.compile(r"^c1_[A-Za-z0-9_-]{1,64}$")


class ToolError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = ERROR_MESSAGES[code]


def _norm(value: str) -> str:
    return value.strip().upper()


def _fx_key(row: dict) -> str:
    return f"{row['date']}:{row['source_currency']}:{row['target_currency']}"


def encode_cursor(table: str, offset: int) -> str:
    raw = f"{table}:{offset}".encode("ascii")
    return "c1_" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str, table: str, total: int) -> int:
    if not isinstance(cursor, str) or not _CURSOR_RE.match(cursor):
        raise ToolError("invalid_cursor")
    body = cursor[3:]
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        raise ToolError("invalid_cursor") from None
    name, sep, offset_text = raw.partition(":")
    if sep != ":" or name != table or not offset_text.isdigit() or len(offset_text) > 9:
        raise ToolError("invalid_cursor")
    offset = int(offset_text)
    if offset > total:
        raise ToolError("invalid_cursor")
    return offset


class Toolbox:
    def __init__(self, tables: dict[str, list[dict]]) -> None:
        # Private copies: later mutation of the caller's objects cannot affect us.
        self._tables = {name: copy.deepcopy(tables[name]) for name in TABLES}
        self._index = {
            "ledger": {_norm(r["row_id"]): r for r in self._tables["ledger"]},
            "invoices": {_norm(r["invoice_id"]): r for r in self._tables["invoices"]},
            "payments": {_norm(r["payment_id"]): r for r in self._tables["payments"]},
            "fx": {_norm(_fx_key(r)): r for r in self._tables["fx"]},
        }
        self._documents: dict[str, tuple[str, dict]] = {}
        for d in self._tables["invoices"]:
            self._documents[_norm(d["doc_id"])] = ("invoice", d)
        for d in self._tables["payments"]:
            self._documents[_norm(d["doc_id"])] = ("payment", d)

    def list_records(self, table: str, cursor: str | None, limit: int) -> dict:
        if table not in TABLES:
            raise ToolError("unknown_table")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PAGE:
            raise ToolError("invalid_limit")
        rows = self._tables[table]
        offset = 0 if cursor is None else decode_cursor(cursor, table, len(rows))
        page = rows[offset:offset + limit]
        end = offset + len(page)
        return {
            "table": table,
            "records": copy.deepcopy(page),
            "next_cursor": encode_cursor(table, end) if end < len(rows) else None,
            "total": len(rows),
        }

    def get_record(self, table: str, record_id: str) -> dict:
        if table not in TABLES:
            raise ToolError("unknown_table")
        if not isinstance(record_id, str):
            raise ToolError("unknown_id")
        rec = self._index[table].get(_norm(record_id))
        if rec is None:
            raise ToolError("unknown_id")
        return {"table": table, "record": copy.deepcopy(rec)}

    def get_document(self, doc_id: str) -> dict:
        if not isinstance(doc_id, str):
            raise ToolError("unknown_document")
        hit = self._documents.get(_norm(doc_id))
        if hit is None:
            raise ToolError("unknown_document")
        kind, doc = hit
        return {"doc_type": kind, "document": copy.deepcopy(doc)}

    def calculator(self, expression: str) -> dict:
        try:
            return {"result": evaluate(expression)}
        except CalculatorError as exc:
            raise ToolError(exc.code) from None
