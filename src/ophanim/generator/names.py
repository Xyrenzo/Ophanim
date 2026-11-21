"""Fictional company names built from syllables (no real organisations)."""

from __future__ import annotations

from ophanim.rng import DeterministicRng

_START = ("Bar", "Cel", "Dor", "Eld", "Fen", "Gal", "Hel", "Ist", "Jor", "Kal", "Lum", "Mer", "Nor", "Orv", "Pell", "Quin", "Ros", "Sel", "Tor", "Ul", "Ver", "Wyn", "Zan", "Ast", "Bri")
_MID = ("a", "e", "i", "o", "u", "ae", "io", "ar", "en", "or")
_END = ("dex", "mar", "vale", "ton", "rix", "lan", "via", "nor", "sta", "wen", "dar", "lis", "mont", "rath", "quill")
_SUPPLIER_SUFFIX = ("Logistics", "Supply", "Trading", "Systems", "Services", "Industries", "Partners", "Works", "Labs", "Holdings")
_LEGAL = ("LLP", "Ltd", "GmbH", "S.A.", "Inc.", "B.V.", "AG", "Co.")


def _word(rng: DeterministicRng) -> str:
    return rng.choice(_START) + rng.choice(_MID) + rng.choice(_END)


def company_name(rng: DeterministicRng) -> str:
    return f"{_word(rng)} {rng.choice(('Group', 'Holdings', 'Trading House', 'Retail', 'Digital'))} {rng.choice(_LEGAL)}"


def supplier_name(rng: DeterministicRng) -> str:
    return f"{_word(rng)} {rng.choice(_SUPPLIER_SUFFIX)} {rng.choice(_LEGAL)}"
