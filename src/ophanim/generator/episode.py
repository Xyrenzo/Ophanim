"""Episode generation pipeline.

    1. profile + consistent hidden history          (history.py)
    2. correct double-entry postings                (posting.py)
    3. accounting self-check of the clean books     (posting.validate_world)
    4. causal error injection -> truth + provenance (injectors.py)
    5. presentation: random ids, names, order       (presentation.py)
    6. public dataset  +  sealed evaluator bundle

Random streams (all derived from one root, see rng.py):
    root.child("content")      economic history (independent of errors and presentation)
    root.child("errors")       which documents receive errors
    root.child("presentation") ids / names / order, further keyed by the config hash and salts

Consequences: the same seed with and without errors describes the same company;
two configs that differ only in ``presentation`` describe the same accounting
with different ids/names/order (metamorphic variants).
"""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ophanim.generator.history import build_world, plant_scenario_carriers
from ophanim.generator.injectors import ErrorInjector, InjectedIssue
from ophanim.generator.model import GenerationError, World
from ophanim.generator.posting import post_world, validate_world
from ophanim.generator.presentation import (
    FX_COLUMNS,
    LEDGER_COLUMNS,
    TOLERANCE_MINOR,
    IdMap,
    build_id_map,
    build_manifest,
    build_names,
    build_policy,
    render_tables,
)
from ophanim.rng import DeterministicRng
from ophanim.schemas import EpisodeConfig, TruthFile, TruthIssue
from ophanim.version import ENV_VERSION, SCHEMA_VERSION


# --------------------------------------------------------------------------- containers
@dataclass(frozen=True)
class PublicEpisode:
    """Everything the agent is allowed to see (through the tools)."""

    manifest: dict
    policy: dict
    tables: dict[str, list[dict]]

    @property
    def episode_id(self) -> str:
        return self.manifest["episode_id"]

    def evidence_universe(self) -> frozenset[str]:
        """Every existing id the tools can return, i.e. every id that may be cited as evidence:
        row_id, doc_id, invoice_id, payment_id and FX keys (exact strings). entity_id is not retrievable
        through any tool and is therefore not accessible evidence."""
        ids = {r["row_id"] for r in self.tables["ledger"]}
        for table, key in (("invoices", "invoice_id"), ("payments", "payment_id")):
            ids.update(d["doc_id"] for d in self.tables[table])
            ids.update(d[key] for d in self.tables[table])
        ids.update(fx_key(r) for r in self.tables["fx"])
        return frozenset(ids)

    def write(self, directory: Path) -> None:
        write_public_files(directory, self.manifest, self.policy, self.tables)


@dataclass(frozen=True)
class SealedEpisode:
    """Evaluator-only material. Never handed to the agent-facing environment surface."""

    truth: TruthFile
    provenance: dict
    evidence_universe: frozenset[str]

    def write(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        _write_text(directory / "truth.json", json.dumps(self.truth.model_dump(), indent=2) + "\n")
        _write_text(directory / "provenance.json", json.dumps(self.provenance, indent=2) + "\n")


@dataclass(frozen=True)
class GeneratedEpisode:
    public: PublicEpisode
    sealed: SealedEpisode

    def write(self, directory: Path) -> None:
        """Layout: <dir>/public/* (agent-visible) and <dir>/evaluator/* (evaluator only)."""
        self.public.write(directory / "public")
        self.sealed.write(directory / "evaluator")


def fx_key(row: dict) -> str:
    return f"{row['date']}:{row['source_currency']}:{row['target_currency']}"


# --------------------------------------------------------------------------- serialisation
def _write_text(path: Path, text: str) -> None:
    # newline="\n" -> byte-identical files on Windows and Linux.
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _csv_cell(value: Any) -> str:
    return "null" if value is None else str(value)


def ledger_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(LEDGER_COLUMNS)
    for r in rows:
        writer.writerow([_csv_cell(r[c]) for c in LEDGER_COLUMNS])
    return buf.getvalue()


def fx_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(FX_COLUMNS)
    for r in rows:
        writer.writerow([r[c] for c in FX_COLUMNS])
    return buf.getvalue()


def jsonl(rows: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=True) + "\n" for r in rows)


def write_public_files(directory: Path, manifest: dict, policy: dict, tables: dict[str, list[dict]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    _write_text(directory / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    _write_text(directory / "policy.json", json.dumps(policy, indent=2) + "\n")
    _write_text(directory / "ledger.csv", ledger_csv(tables["ledger"]))
    _write_text(directory / "invoices.jsonl", jsonl(tables["invoices"]))
    _write_text(directory / "payments.jsonl", jsonl(tables["payments"]))
    _write_text(directory / "fx.csv", fx_csv(tables["fx"]))


# --------------------------------------------------------------------------- pipeline
def _config_digest(cfg: EpisodeConfig) -> str:
    return hashlib.sha256(json.dumps(cfg.model_dump(), sort_keys=True).encode("utf-8")).hexdigest()


def _public_evidence(item: tuple, ids: IdMap, base: str) -> str:
    kind = item[0]
    if kind == "doc":
        return ids.doc[item[1]]
    if kind == "row":
        return ids.row[item[1]]
    if kind == "fx":
        return f"{item[1]}:{item[2]}:{base}"
    raise GenerationError(f"unknown evidence kind {kind!r}")


def _public_affected(key: str, ids: IdMap) -> str:
    if key in ids.invoice:
        return ids.invoice[key]
    return ids.payment[key]


def generate_episode(seed: int, config: EpisodeConfig | dict | None = None, *, secret: bytes | None = None) -> GeneratedEpisode:
    """Generate one episode. Deterministic in (seed, config, secret, ENV_VERSION)."""
    cfg = config if isinstance(config, EpisodeConfig) else EpisodeConfig.model_validate(config or {})
    root = DeterministicRng.from_seed(seed, secret=secret)

    world = build_world(root.child("content"), cfg)
    plant_scenario_carriers(world, root.child("carriers"), cfg)
    post_world(world)
    problems = validate_world(world)
    if problems:  # the clean books must satisfy every accounting equality
        raise GenerationError("clean history failed validation: " + "; ".join(problems[:5]))
    clean: World = copy.deepcopy(world)

    injector = ErrorInjector(world, root.child("errors"))
    issues: list[InjectedIssue] = injector.run(cfg)

    pres = root.child("presentation").child(_config_digest(cfg))
    ids = build_id_map([clean, world], pres.child("ids").child(cfg.presentation.id_salt))
    nm = build_names(world, pres.child("names").child(cfg.presentation.name_salt))
    order_rng = pres.child("order").child(cfg.presentation.id_salt) if cfg.presentation.order == "shuffled" else None
    episode_id = "EP-" + pres.child("ids").child(cfg.presentation.id_salt).fingerprint("episode")[:12].upper()

    ts_offset = world.offset_minutes if cfg.presentation.timestamp_offset == "company" else 0
    tables = render_tables(world, ids, nm, order_rng, ts_offset)
    public = PublicEpisode(manifest=build_manifest(world, tables, episode_id, nm), policy=build_policy(world), tables=tables)

    clean_tables = render_tables(clean, ids, nm, order_rng, ts_offset)
    issue_rng = pres.child("issues")
    base = world.base_currency
    truth_issues: list[TruthIssue] = []
    injections: list[dict] = []
    for issue in issues:
        issue_id = "ISS-" + issue_rng.token(10)
        truth_issues.append(TruthIssue(
            issue_id=issue_id,
            type=issue.type,
            affected_ids=sorted(_public_affected(k, ids) for k in issue.affected),
            expected_amount_minor=issue.amount_minor,
            currency=base,
            allowed_evidence_sets=[sorted(_public_evidence(i, ids, base) for i in s) for s in issue.evidence_sets],
            scenario=issue.scenario,
        ))
        injections.append({"issue_id": issue_id, "type": issue.type, "scenario": issue.scenario,
                           "cause": issue.cause, "details": issue.details})
    truth_issues.sort(key=lambda t: t.issue_id)
    truth = TruthFile(schema_version=SCHEMA_VERSION, episode_id=episode_id, base_currency=base,
                      tolerance_minor=TOLERANCE_MINOR, issues=truth_issues)

    provenance = {
        "schema_version": SCHEMA_VERSION,
        "env_version": ENV_VERSION,
        "episode_id": episode_id,
        "generation": {"seed": seed, "secret_used": bool(secret), "config": cfg.model_dump()},
        "company": {"profile": world.profile_name, "base_currency": base, "offset_minutes": world.offset_minutes,
                    "period": [world.period_start.isoformat(), world.period_end.isoformat()]},
        "id_map": ids.flat(),
        "distractors": world.distractors,
        "scenario_carriers": world.scenario_carriers,
        "injections": injections,
        "pre_mutation": {
            "validation_problems": problems,
            "tables": clean_tables,
        },
    }
    sealed = SealedEpisode(truth=truth, provenance=provenance, evidence_universe=public.evidence_universe())
    return GeneratedEpisode(public=public, sealed=sealed)
