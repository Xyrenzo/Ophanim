"""Public schemas (Pydantic v2, strict).

Every model forbids unknown fields and uses strict typing: ``"50"`` is not an
int, ``true`` is not an int, ``1.0`` is not an int. Strictness is deliberate:
a lenient parser is an attack surface for specification gaming (e.g. sneaking
a float amount past a tolerance check).

JSON Schema for each public model can be exported with
``python -m ophanim schemas`` (see docs/data_model.md).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ophanim.version import CONFIG_VERSION

ERROR_TYPES: tuple[str, ...] = (
    "duplicate_invoice",
    "payment_allocation",
    "fx_rate",
    "period_attribution",
)
ErrorType = Literal["duplicate_invoice", "payment_allocation", "fx_rate", "period_attribution"]

MAX_TOTAL_ISSUES = 12
MAX_FINDINGS = 30
MAX_EVIDENCE_IDS = 10
MAX_EXPLANATION_CHARS = 1000  # Unicode code points (Python len), not UTF-8 bytes
MAX_ID_CHARS = 64  # limit for *tool arguments* only (lookups); findings ids are not length-limited

IdStr = Annotated[str, StringConstraints(min_length=1, max_length=MAX_ID_CHARS)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=False)


# --------------------------------------------------------------------------- config
class ErrorCounts(StrictModel):
    """How many independent errors of each mandatory type to inject (0-12 total)."""

    duplicate_invoice: int = Field(0, ge=0, le=MAX_TOTAL_ISSUES)
    payment_allocation: int = Field(0, ge=0, le=MAX_TOTAL_ISSUES)
    fx_rate: int = Field(0, ge=0, le=MAX_TOTAL_ISSUES)
    period_attribution: int = Field(0, ge=0, le=MAX_TOTAL_ISSUES)


class ScenarioCounts(StrictModel):
    """Interacting-error scenarios. Each one produces exactly two linked issues."""

    # S1: foreign payment near the period boundary - rate taken from the UTC date
    #     (fx_rate on the payment) AND one remittance line parked in Suspense
    #     (payment_allocation). The allocation amount must be valued at the
    #     invoice's policy rate, not at the (wrong) rate in the ledger.
    fx_partial_payment_boundary: int = Field(0, ge=0, le=3)
    # S2: foreign invoice booked at a wrong-date rate (fx_rate on the invoice)
    #     AND its payment's remittance line for it left unapplied
    #     (payment_allocation). The allocation amount must use the invoice's
    #     correct policy rate, not the booked (wrong) carrying amount.
    fx_invoice_unapplied_payment: int = Field(0, ge=0, le=3)


class Presentation(StrictModel):
    """Harmless presentation knobs used for metamorphic testing.

    Changing these never changes the underlying accounting: same economics,
    different identifiers / names / record order.
    """

    id_salt: str = Field("default", min_length=1, max_length=64)
    name_salt: str = Field("default", min_length=1, max_length=64)
    order: Literal["natural", "shuffled"] = "natural"
    # How ledger and payment timestamps are written: in UTC (default) or in the company's
    # offset. Same instants either way - only the textual representation changes.
    timestamp_offset: Literal["utc", "company"] = "utc"


ProfileName = Literal["auto", "retail", "trading", "software", "manufacturing", "logistics", "consulting"]


class EpisodeConfig(StrictModel):
    config_version: Literal["1.0"] = CONFIG_VERSION  # type: ignore[assignment]
    profile: ProfileName = "auto"
    size: Literal["small", "medium", "large"] = "medium"
    errors: ErrorCounts = Field(default_factory=ErrorCounts)
    scenarios: ScenarioCounts = Field(default_factory=ScenarioCounts)
    distractors: Literal["low", "normal", "high"] = "normal"
    presentation: Presentation = Field(default_factory=Presentation)
    # Shape of the injected payment_allocation errors (official D09-D11):
    #   "missing" - a one-line payment whose only line is not applied (applied = 0);
    #   "partial" - a two-line payment with one line not applied (0 < applied < payment amount);
    #   "auto"    - historical behaviour: a random payment with remittance is chosen.
    allocation_mode: Literal["auto", "missing", "partial"] = "auto"

    @model_validator(mode="after")
    def _check_total(self) -> "EpisodeConfig":
        total = self.total_issues()
        if total > MAX_TOTAL_ISSUES:
            raise ValueError(f"an episode may contain at most {MAX_TOTAL_ISSUES} issues (configured {total})")
        return self

    def total_issues(self) -> int:
        e, s = self.errors, self.scenarios
        singles = e.duplicate_invoice + e.payment_allocation + e.fx_rate + e.period_attribution
        return singles + 2 * (s.fx_partial_payment_boundary + s.fx_invoice_unapplied_payment)


# --------------------------------------------------------------------------- findings
class Finding(StrictModel):
    """STRUCTURE of one finding (official matcher conventions, fintech-checks.txt).

    Structure errors (whole submission -> reward -1) are only: missing required fields, wrong JSON value
    types (e.g. a bool/string/float amount, a number where an id string is expected), unknown fields, and
    the published limits (30 findings, 10 evidence ids, 1000 code points of explanation), checked on the
    raw lists before any set conversion. Everything else - an unknown type string, a currency differing
    in case or whitespace, a negative amount, an empty or unknown id list - is structurally valid and is
    judged by the matcher (it simply cannot match, i.e. a false positive).
    """

    type: str
    affected_ids: list[str]
    claimed_amount_minor: int
    currency: str
    evidence_ids: list[str] = Field(max_length=MAX_EVIDENCE_IDS)
    explanation: str = Field(max_length=MAX_EXPLANATION_CHARS)


class FindingsSubmission(StrictModel):
    episode_id: str
    findings: list[Finding] = Field(max_length=MAX_FINDINGS)


# --------------------------------------------------------------------------- actions
class ListRecordsAction(StrictModel):
    action: Literal["list_records"]
    table: str = Field(max_length=32)
    cursor: str | None = Field(None, max_length=128)
    limit: int = 50


class GetRecordAction(StrictModel):
    action: Literal["get_record"]
    table: str = Field(max_length=32)
    id: str = Field(max_length=MAX_ID_CHARS)


class GetDocumentAction(StrictModel):
    action: Literal["get_document"]
    doc_id: str = Field(max_length=MAX_ID_CHARS)


class CalculatorAction(StrictModel):
    action: Literal["calculator"]
    expression: str = Field(max_length=512)


class SubmitAction(StrictModel):
    """``findings`` is validated separately against FindingsSubmission.

    An invalid submission is not an "invalid action": it terminates the episode
    with reward -1 as required by the official case.
    """

    action: Literal["submit"]
    findings: Any = None


InvestigationAction = ListRecordsAction | GetRecordAction | GetDocumentAction | CalculatorAction
ACTION_NAMES: tuple[str, ...] = ("list_records", "get_record", "get_document", "calculator", "submit")


# --------------------------------------------------------------------------- truth (evaluator only)
class TruthIssue(StrictModel):
    issue_id: str
    type: ErrorType
    affected_ids: list[str]
    expected_amount_minor: int = Field(ge=0)
    currency: str
    allowed_evidence_sets: list[list[str]] = Field(min_length=1)
    # "single" or the interacting-scenario name. Optional so that a minimal truth file containing only
    # the officially listed fields (jury fixtures) still loads.
    scenario: str = "single"


class TruthFile(StrictModel):
    schema_version: str
    episode_id: str
    base_currency: str
    # Amount tolerance tau in minor units: exact (0) unless a fixed non-negative integer is published
    # for the episode. Never inferred; negative or non-integer values are rejected.
    tolerance_minor: int = Field(0, ge=0)
    issues: list[TruthIssue]
