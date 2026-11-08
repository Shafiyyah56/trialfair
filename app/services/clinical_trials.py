"""Agent 1 owns registry ingestion; Agent 3 reuses this same service interface."""

import asyncio
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, field_validator

from app.contracts import (
    AdverseEventRow,
    DataAvailability,
    DemographicRow,
    NctId,
    PKRow,
    SourceLocator,
    SourceRecord,
    TrialBundle,
    TrialSearchHit,
)


@dataclass(frozen=True)
class RetrievedTrial:
    """Raw API v2 response plus retrieval provenance; parsing belongs to Agent 1."""

    payload: dict[str, JsonValue]
    source: SourceRecord


class ClinicalTrialsService(Protocol):
    async def fetch_trial(self, nct_id: str) -> RetrievedTrial: ...

    async def search_related_trials(
        self, query: str, *, page_size: int = 5
    ) -> list[TrialSearchHit]: ...


if TYPE_CHECKING:
    from app.context import RunBudget


class RegistryObject(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)


class RegistryIdentity(RegistryObject):
    nctId: NctId
    briefTitle: str


class RegistryMeasurement(RegistryObject):
    groupId: str
    value: str | None = None
    spread: str | None = None


class RegistryCategory(RegistryObject):
    title: str | None = None
    measurements: list[RegistryMeasurement] = Field(default_factory=list)


class RegistryDenomCount(RegistryObject):
    groupId: str
    value: str


class RegistryDenom(RegistryObject):
    units: str | None = None
    counts: list[RegistryDenomCount] = Field(default_factory=list)


class RegistryClass(RegistryObject):
    title: str | None = None
    denoms: list[RegistryDenom] = Field(default_factory=list)
    categories: list[RegistryCategory] = Field(default_factory=list)


class RegistryMeasure(RegistryObject):
    title: str
    paramType: str | None = None
    unitOfMeasure: str | None = None
    populationDescription: str | None = None
    denoms: list[RegistryDenom] = Field(default_factory=list)
    classes: list[RegistryClass] = Field(default_factory=list)


class RegistryBaseline(RegistryObject):
    populationDescription: str | None = None
    denoms: list[RegistryDenom] = Field(default_factory=list)
    measures: list[RegistryMeasure] = Field(default_factory=list)


class RegistryEventStats(RegistryObject):
    groupId: str
    numEvents: int | None = None
    numAffected: int | None = None
    numAtRisk: int | None = None


class RegistryEvent(RegistryObject):
    term: str
    stats: list[RegistryEventStats] = Field(default_factory=list)


class RegistryGroup(RegistryObject):
    id: str
    title: str | None = None
    description: str | None = None


class RegistryAE(RegistryObject):
    timeFrame: str | None = None
    eventGroups: list[RegistryGroup] = Field(default_factory=list)
    seriousEvents: list[RegistryEvent] = Field(default_factory=list)
    otherEvents: list[RegistryEvent] = Field(default_factory=list)


class RegistryOutcomes(RegistryObject):
    outcomeMeasures: list[RegistryMeasure] = Field(default_factory=list)


class RegistryResults(RegistryObject):
    baselineCharacteristicsModule: RegistryBaseline | None = None
    adverseEventsModule: RegistryAE | None = None
    outcomeMeasuresModule: RegistryOutcomes | None = None


class RegistryProtocol(RegistryObject):
    identificationModule: RegistryIdentity


class RegistryStudy(RegistryObject):
    """Consumed fields checked against official OpenAPI 2.0.5 field types.

    Preserve the raw payload, including fields outside this adapter's scope.
    This intentionally validates the extraction subset, not every registry field.
    """

    protocolSection: dict
    resultsSection: dict | None = None
    hasResults: bool | None = None

    @field_validator("protocolSection")
    @classmethod
    def protocol_shape(cls, value):
        RegistryProtocol.model_validate(value)
        return value

    @field_validator("resultsSection")
    @classmethod
    def results_shape(cls, value):
        if value is not None:
            RegistryResults.model_validate(value)
        return value


def _count(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        return int(value)
    return None


class ClinicalTrialsClient:
    """One injected HTTP client and run budget; no network work at construction.

    Caller owns client lifetime. Cache stores exact response bytes and provenance;
    cache hits retain original retrieval time. replay=True prohibits HTTP calls.
    """

    base_url = "https://clinicaltrials.gov/api/v2"

    def __init__(
        self,
        client: httpx.AsyncClient,
        budget: "RunBudget",
        *,
        cache_dir: Path | None = None,
        replay: bool = False,
    ):
        self.client, self.budget = client, budget
        self.cache_dir, self.replay = cache_dir, replay
        self.cache_hits: list[str] = []
        self._memory: dict[str, RetrievedTrial] = {}
        self._searches: dict[tuple[str, int], list[TrialSearchHit]] = {}

    async def _get(self, path, params=None):
        self.budget.consume("external_request")
        async with asyncio.timeout(self.budget.remaining_seconds()):
            response = await self.client.get(
                self.base_url + path,
                params=params,
                timeout=min(20, self.budget.remaining_seconds()),
                follow_redirects=False,
            )
        response.raise_for_status()
        return response

    async def fetch_trial(self, nct_id: str) -> RetrievedTrial:
        nct_id = TypeAdapter(NctId).validate_python(nct_id)
        self.budget.remaining_seconds()
        if nct_id in self._memory:
            self.cache_hits.append(nct_id)
            return self._memory[nct_id]
        path = self.cache_dir / f"{nct_id}.json" if self.cache_dir else None
        if path and path.exists():
            cached = json.loads(path.read_text())
            raw = cached["raw_utf8"].encode("utf-8")
            source = SourceRecord.model_validate(cached["source"])
            if hashlib.sha256(raw).hexdigest() != source.content_hash:
                raise ValueError("Registry cache hash mismatch")
            self.cache_hits.append(nct_id)
            payload = json.loads(raw)
        else:
            if self.replay:
                raise ValueError("No captured registry response for replay")
            response = await self._get(f"/studies/{nct_id}")
            raw, payload = response.content, response.json()
            study = RegistryStudy.model_validate(payload)
            title = study.protocolSection.get("identificationModule", {}).get("briefTitle", nct_id)
            digest = hashlib.sha256(raw).hexdigest()
            source = SourceRecord(
                source_id=f"ctgov-{nct_id}-{digest[:12]}",
                source_type="trial_registry",
                title=title,
                url=f"https://clinicaltrials.gov/study/{nct_id}",
                external_id=nct_id,
                retrieved_at=datetime.now(UTC),
                content_hash=digest,
                access_level="full_text",
                is_synthetic=False,
            )
        study = RegistryStudy.model_validate(payload)
        actual = study.protocolSection.get("identificationModule", {}).get("nctId")
        if actual != nct_id or source.external_id != nct_id or source.is_synthetic:
            raise ValueError("Registry identity or source mismatch")
        if path and not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {"raw_utf8": raw.decode("utf-8"), "source": source.model_dump(mode="json")}
                )
            )
        retrieved = RetrievedTrial(payload=payload, source=source)
        self._memory[nct_id] = retrieved
        return retrieved

    async def search_related_trials(
        self, query: str, *, page_size: int = 5
    ) -> list[TrialSearchHit]:
        if not query.strip() or len(query) > 2000 or not 1 <= page_size <= 20:
            raise ValueError("Provide a bounded query and page_size between 1 and 20")
        key = (query, page_size)
        if key in self._searches:
            return list(self._searches[key])
        if self.replay:
            raise ValueError("No captured related-trial search configured")
        response = await self._get(
            "/studies", {"query.term": query, "pageSize": page_size, "format": "json"}
        )
        payload = response.json()
        if not isinstance(payload.get("studies"), list):
            raise ValueError("Malformed registry search response")
        hits = []
        for item in payload["studies"]:
            study = RegistryStudy.model_validate(item)
            identity = study.protocolSection["identificationModule"]
            hits.append(TrialSearchHit(nct_id=identity["nctId"], title=identity["briefTitle"]))
        self._searches[key] = hits
        return list(hits)


def parse_trial(retrieved: RetrievedTrial) -> TrialBundle:
    """Conservative API v2 parsing, never derive sex strata from arm names.

    All outcomes remain available in the raw response. Uncertain PK extraction is
    flagged, not guessed from arbitrary outcome titles or free-text groups.
    """
    study = RegistryStudy.model_validate(retrieved.payload)
    protocol = study.protocolSection
    identity = protocol["identificationModule"]
    TypeAdapter(NctId).validate_python(identity["nctId"])
    results = study.resultsSection or {}
    baseline = results.get("baselineCharacteristicsModule", {})
    ae = results.get("adverseEventsModule", {})
    sid = retrieved.source.source_id
    limitations = [
        "Registry groups are not assumed to be sex strata; baseline and AE groups are not joined.",
        "Outcome summaries are retained in the raw record; PK extraction requires review.",
    ]

    def locator(path, excerpt=None):
        return SourceLocator(source_id=sid, location=path, excerpt=excerpt)

    demographics = []
    for mi, measure in enumerate(baseline.get("measures", [])):
        if measure.get("paramType") != "COUNT_OF_PARTICIPANTS":
            continue
        for ci, cls in enumerate(measure.get("classes", [])):
            for ki, category in enumerate(cls.get("categories", [])):
                for vi, value in enumerate(category.get("measurements", [])):
                    group = value["groupId"]
                    denoms = cls.get("denoms", measure.get("denoms", baseline.get("denoms", [])))
                    counts = [
                        c.get("value")
                        for d in denoms
                        if d.get("units", "").casefold() == "participants"
                        for c in d.get("counts", [])
                        if c.get("groupId") == group
                    ]
                    denominator = _count(counts[0]) if len(counts) == 1 else None
                    path = (
                        f"$.resultsSection.baselineCharacteristicsModule.measures[{mi}]"
                        f".classes[{ci}].categories[{ki}].measurements[{vi}]"
                    )
                    count = _count(value.get("value"))
                    if count is not None and denominator is not None and count > denominator:
                        limitations.append(
                            f"Inconsistent demographic denominator at {path}; denominator withheld."
                        )
                        denominator = None
                    demographics.append(
                        DemographicRow(
                            row_id=f"baseline-{mi}-{ci}-{ki}-{vi}",
                            category=measure.get("title", ""),
                            reported_label=category.get("title", cls.get("title", "")),
                            group_id=group,
                            analysis_population=measure.get(
                                "populationDescription", baseline.get("populationDescription")
                            ),
                            count=count,
                            denominator=denominator,
                            source_locator=locator(path),
                            is_synthetic=retrieved.source.is_synthetic,
                        )
                    )
    groups = {g["id"]: g for g in ae.get("eventGroups", [])}
    adverse = []
    for key, seriousness in (("seriousEvents", "serious"), ("otherEvents", "non_serious")):
        for ei, event in enumerate(ae.get(key, [])):
            for si, stat in enumerate(event.get("stats", [])):
                path = f"$.resultsSection.adverseEventsModule.{key}[{ei}].stats[{si}]"
                group = stat["groupId"]
                # Group descriptions retain dose details verbatim. No arm/sex inference.
                description = groups.get(group, {}).get("description")
                affected, at_risk = _count(stat.get("numAffected")), _count(stat.get("numAtRisk"))
                if affected is not None and at_risk is not None and affected > at_risk:
                    limitations.append(
                        f"Affected count exceeds denominator at {path}; row withheld."
                    )
                    continue
                adverse.append(
                    AdverseEventRow(
                        row_id=f"{key}-{ei}-{si}",
                        source_term=event["term"],
                        group_id=group,
                        intervention=description,
                        participants_affected=affected,
                        participants_at_risk=at_risk,
                        event_occurrences=_count(stat.get("numEvents")),
                        event_seriousness=seriousness,
                        reporting_window=ae.get("timeFrame"),
                        source_locator=locator(path, event["term"]),
                        is_synthetic=retrieved.source.is_synthetic,
                    )
                )
    pk_rows = []
    outcomes = results.get("outcomeMeasuresModule", {}).get("outcomeMeasures", [])
    for oi, outcome in enumerate(outcomes):
        title = outcome.get("title", "")
        # Narrow recognition: named concentration/exposure parameters with explicit units.
        known = re.search(r"\b(Cmax|Tmax|AUC(?:0[-_a-z0-9]*)?)\b", title, re.IGNORECASE)
        if not known or not outcome.get("unitOfMeasure") or not outcome.get("paramType"):
            continue
        if not re.search(
            r"pharmacokinetic|plasma|serum|concentration|exposure", title, re.IGNORECASE
        ):
            limitations.append(f"Possible PK outcome requires review: outcomeMeasures[{oi}].")
            continue
        for ci, cls in enumerate(outcome.get("classes", [])):
            for ki, category in enumerate(cls.get("categories", [])):
                for vi, value in enumerate(category.get("measurements", [])):
                    try:
                        number = float(value["value"])
                    except (KeyError, TypeError, ValueError):
                        limitations.append(
                            f"Non-numeric PK summary requires review: outcomeMeasures[{oi}]."
                        )
                        continue

                    if not math.isfinite(number):
                        continue
                    group = value["groupId"]
                    sex = (
                        category.get("title")
                        if cls.get("title", "").casefold() in {"sex", "gender"}
                        else None
                    )
                    denoms = cls.get("denoms", outcome.get("denoms", []))
                    sizes = [
                        _count(c.get("value"))
                        for d in denoms
                        if d.get("units", "").casefold() == "participants"
                        for c in d.get("counts", [])
                        if c.get("groupId") == group
                    ]
                    pk_rows.append(
                        PKRow(
                            row_id=f"pk-{oi}-{ci}-{ki}-{vi}",
                            parameter=title,
                            value=number,
                            unit=outcome["unitOfMeasure"],
                            summary_statistic=outcome["paramType"],
                            reported_sex_category=sex,
                            group_id=group,
                            sample_size=sizes[0] if len(sizes) == 1 else None,
                            variability=value.get("spread"),
                            source_locator=locator(
                                f"$.resultsSection.outcomeMeasuresModule.outcomeMeasures[{oi}]"
                                f".classes[{ci}].categories[{ki}].measurements[{vi}]"
                            ),
                            is_synthetic=retrieved.source.is_synthetic,
                        )
                    )
    if not results:
        limitations.append("No posted results in the retrieved record.")
    if study.hasResults and not results:
        limitations.append(
            "Registry indicates results but resultsSection is absent; review source."
        )
    return TrialBundle(
        trial_id=identity["nctId"],
        title=identity.get("briefTitle", identity["nctId"]),
        condition_names=protocol.get("conditionsModule", {}).get("conditions", []),
        interventions=[
            i["name"] for i in protocol.get("armsInterventionsModule", {}).get("interventions", [])
        ],
        phase=", ".join(protocol.get("designModule", {}).get("phases", [])) or None,
        study_status=protocol.get("statusModule", {}).get("overallStatus"),
        sources=[retrieved.source],
        demographic_rows=demographics,
        adverse_event_rows=adverse,
        pk_rows=pk_rows,
        availability=DataAvailability(
            representation="available" if demographics else "missing",
            sex_stratified_ae="not_assessed" if adverse else "missing",
            sex_stratified_pk="not_assessed" if results else "missing",
            participant_level="missing",
            notes=["Explicit sex-stratified extraction requires source review."],
        ),
        limitations=limitations,
        is_synthetic=retrieved.source.is_synthetic,
    )
