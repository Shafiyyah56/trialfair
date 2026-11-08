"""Versioned contracts shared by all agents; coordinate changes before editing.

These schemas preserve source wording, denominators, uncertainty and provenance.
They describe data exchange, not evidence of scientific validity. Cross-record ID
validation is provided separately and must run before publishing a run result.
"""

from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    JsonValue,
    StringConstraints,
    model_validator,
)

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
NctId = Annotated[str, StringConstraints(pattern=r"^NCT\d{8}$")]
Count = Annotated[int, Field(strict=True, ge=0)]
ToolName = Literal[
    "summarise_representation",
    "audit_subgroup_availability",
    "compare_adverse_event_rates",
    "summarise_pk_by_sex",
]
CompletionStatus = Literal["completed", "partial", "unavailable"]


class Contract(BaseModel):
    """Reject unknown fields and non-finite numbers rather than silently losing data."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal["1.0"] = "1.0"


class SourceRecord(Contract):
    source_id: Identifier
    source_type: Literal["trial_registry", "publication", "uploaded_data", "synthetic"]
    title: str
    url: HttpUrl | None = None
    external_id: str | None = None
    retrieved_at: AwareDatetime
    content_hash: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    licence_name: str | None = None
    licence_url: HttpUrl | None = None
    licence_status: Literal["verified", "unknown", "restricted"] = "unknown"
    access_level: Literal["metadata", "abstract", "full_text", "uploaded"]
    is_synthetic: bool

    @model_validator(mode="after")
    def synthetic_source_is_labelled(self) -> "SourceRecord":
        if self.source_type == "synthetic" and not self.is_synthetic:
            raise ValueError("Synthetic sources must be explicitly labelled")
        return self


class SourceLocator(Contract):
    source_id: Identifier
    location: Identifier
    excerpt: str | None = None


class NarrativeEntry(Contract):
    entry_id: Identifier
    text: Annotated[str, StringConstraints(min_length=1, max_length=20000)]
    locator: SourceLocator


class TrialInput(Contract):
    nct_id: NctId | None = None
    narrative_entries: list[NarrativeEntry] = Field(default_factory=list, max_length=100)
    dataset_refs: list[Identifier] = Field(default_factory=list, max_length=20)
    mode: Literal["live", "replay"] = "live"

    @model_validator(mode="after")
    def has_input(self) -> "TrialInput":
        if not (self.nct_id or self.narrative_entries or self.dataset_refs):
            raise ValueError("Provide a trial identifier, narrative or validated dataset reference")
        return self


class DemographicRow(Contract):
    row_id: Identifier
    category: str
    reported_label: str
    group_id: Identifier
    analysis_population: str | None = None
    count: Count | None = None
    denominator: Count | None = None
    source_locator: SourceLocator
    is_synthetic: bool

    @model_validator(mode="after")
    def check_count(self) -> "DemographicRow":
        if self.count is not None and self.denominator is not None:
            if self.count > self.denominator:
                raise ValueError("Demographic count exceeds denominator")
        return self


class AdverseEventRow(Contract):
    row_id: Identifier
    source_term: str
    normalised_term: str | None = None
    group_id: Identifier
    intervention: str | None = None
    reported_sex_category: str | None = None
    analysis_population: str | None = None
    participants_affected: Count | None = None
    participants_at_risk: Count | None = None
    event_occurrences: Count | None = None
    event_seriousness: Literal["serious", "non_serious", "unspecified"] = "unspecified"
    reporting_window: str | None = None
    source_locator: SourceLocator
    is_synthetic: bool

    @model_validator(mode="after")
    def check_participants(self) -> "AdverseEventRow":
        if self.participants_affected is not None and self.participants_at_risk is not None:
            if self.participants_affected > self.participants_at_risk:
                raise ValueError("Affected participants exceed participants at risk")
        return self


class PKRow(Contract):
    row_id: Identifier
    parameter: str
    value: float
    unit: str
    summary_statistic: str
    reported_sex_category: str | None = None
    group_id: Identifier
    dose: str | None = None
    formulation: str | None = None
    sample_size: Count | None = None
    variability: str | None = None
    source_locator: SourceLocator
    is_synthetic: bool


class DataAvailability(Contract):
    representation: Literal["available", "missing", "not_applicable", "not_assessed"]
    sex_stratified_ae: Literal["available", "missing", "not_applicable", "not_assessed"]
    sex_stratified_pk: Literal["available", "missing", "not_applicable", "not_assessed"]
    participant_level: Literal["available", "missing", "not_applicable", "not_assessed"]
    notes: list[str] = Field(default_factory=list)


class TrialBundle(Contract):
    trial_id: Identifier
    title: str
    condition_names: list[str] = Field(default_factory=list)
    interventions: list[str] = Field(default_factory=list)
    phase: str | None = None
    study_status: str | None = None
    sources: list[SourceRecord]
    demographic_rows: list[DemographicRow] = Field(default_factory=list)
    adverse_event_rows: list[AdverseEventRow] = Field(default_factory=list)
    pk_rows: list[PKRow] = Field(default_factory=list)
    narrative_entries: list[NarrativeEntry] = Field(default_factory=list)
    availability: DataAvailability
    limitations: list[str] = Field(default_factory=list)
    is_synthetic: bool


class SymptomMapping(Contract):
    mapping_id: Identifier
    original_text: str
    normalised_term: str | None = None
    terminology_system: str | None = None
    terminology_code: str | None = None
    assertion: Literal["present", "absent", "uncertain"]
    temporality: Literal["pre_existing", "treatment_emergent", "unknown"]
    severity: str | None = None
    attribution_text: str | None = None
    needs_review: bool
    explanation: str
    source_locator: SourceLocator

    @model_validator(mode="after")
    def code_requires_system(self) -> "SymptomMapping":
        if self.terminology_code and not self.terminology_system:
            raise ValueError("Terminology codes require an identified terminology system")
        return self


class AnalysisRequest(Contract):
    request_id: Identifier
    requested_by: Literal["interpreter", "safety", "evidence"]
    tool_name: ToolName
    dataset_ref: Identifier
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    rationale: str
    related_finding_ids: list[Identifier] = Field(default_factory=list)


class AnalysisResult(Contract):
    analysis_id: Identifier
    request_id: str | None = None
    status: Literal["completed", "unavailable", "invalid"]
    method: str
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    results: dict[str, JsonValue] = Field(default_factory=dict)
    sample_sizes: dict[str, Count] = Field(default_factory=dict)
    source_locators: list[SourceLocator]
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    is_synthetic: bool


class Finding(Contract):
    finding_id: Identifier
    finding_type: Literal["potential_signal", "evidence_gap", "data_quality"]
    title: str
    description: str
    endpoint: str | None = None
    priority: Literal["high", "medium", "low"]
    priority_rationale: str
    analysis_ids: list[Identifier] = Field(default_factory=list)
    source_ids: list[Identifier]
    limitations: list[str] = Field(default_factory=list)
    is_synthetic: bool


class ScreeningOutput(Contract):
    trial_bundle: TrialBundle
    symptom_mappings: list[SymptomMapping] = Field(default_factory=list)
    analyses: list[AnalysisResult] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


class EvidenceRequest(Contract):
    request_id: Identifier
    trial_id: Identifier
    finding_ids: list[Identifier]
    question: str
    drug_names: list[str] = Field(default_factory=list)
    symptom_terms: list[str] = Field(default_factory=list)
    population: str | None = None
    hypotheses_to_challenge: list[str] = Field(default_factory=list)


class EvidenceItem(Contract):
    evidence_id: Identifier
    source_id: Identifier
    finding_ids: list[Identifier]
    claim: str
    relation: Literal["supports", "contradicts", "inconclusive", "background"]
    source_locator: SourceLocator
    study_design: str | None = None
    population: str | None = None
    intervention: str | None = None
    endpoint: str | None = None
    relevance: str
    limitations: list[str] = Field(default_factory=list)


class SearchRecord(Contract):
    service: Literal["europe_pmc", "clinical_trials"]
    query: str
    searched_at: AwareDatetime
    result_source_ids: list[Identifier] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class EvidenceReport(Contract):
    request_id: Identifier
    searches: list[SearchRecord] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    suggested_analysis_requests: list[AnalysisRequest] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    status: CompletionStatus


class Hypothesis(Contract):
    hypothesis_id: Identifier
    statement: str
    finding_ids: list[Identifier]
    supporting_evidence_ids: list[Identifier] = Field(default_factory=list)
    contradicting_evidence_ids: list[Identifier] = Field(default_factory=list)
    status: Literal["proposed", "supported", "weakened", "unresolved"]


class FindingAssessment(Contract):
    finding_id: Identifier
    conclusion: str
    priority: Literal["high", "medium", "low"]
    rationale: str
    analysis_ids: list[Identifier] = Field(default_factory=list)
    evidence_ids: list[Identifier] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class InvestigationReport(Contract):
    trial_id: Identifier
    assessed_findings: list[FindingAssessment] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    completed_analysis_ids: list[Identifier] = Field(default_factory=list)
    evidence_ids: list[Identifier] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    status: CompletionStatus


class AgentEvent(Contract):
    event_id: Identifier
    run_id: Identifier
    timestamp: AwareDatetime
    agent: Literal["interpreter", "safety", "evidence", "orchestrator"]
    event_type: Literal["decision", "tool_call", "tool_result", "revision", "stop", "error"]
    summary: str
    related_ids: list[Identifier] = Field(default_factory=list)
    duration_ms: Annotated[float, Field(ge=0)] | None = None


class PlannerInput(Contract):
    screening: ScreeningOutput
    investigation: InvestigationReport
    evidence_reports: list[EvidenceReport]


class RunResult(Contract):
    run_id: Identifier
    mode: Literal["live", "replay"]
    model_id: str | None = None
    status: Literal["completed", "partial", "failed"]
    screening: ScreeningOutput | None = None
    investigation: InvestigationReport | None = None
    evidence_reports: list[EvidenceReport] = Field(default_factory=list)
    planner_input: PlannerInput | None = None
    events: list[AgentEvent] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    duration_ms: Annotated[float, Field(ge=0)]


class PublicationRecord(Contract):
    """Literature service response. No inference about article contents is implied."""

    source: SourceRecord
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    abstract: str | None = None
    full_text_available: bool = False


class TrialSearchHit(Contract):
    nct_id: NctId
    title: str


class TerminologyCandidate(Contract):
    term: str
    system: str | None = None
    code: str | None = None
    source_locator: SourceLocator | None = None


class HealthResponse(Contract):
    status: Literal["scaffold"] = "scaffold"
    agents_implemented: bool = False
