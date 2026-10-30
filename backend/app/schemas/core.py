from datetime import date as DateType
from enum import Enum
import json
import re
from typing import Any, Literal
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, model_validator

class EvidenceStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    INFERRED = "INFERRED"
    MODEL_KNOWLEDGE = "MODEL_KNOWLEDGE"
    LAB_RECORD = "LAB_RECORD"
    UNKNOWN = "UNKNOWN"

class Claim(BaseModel):
    claim: str
    status: EvidenceStatus
    evidence_ids: list[int] = Field(default_factory=list)
    experiment_refs: list[int] = Field(default_factory=list)
    @model_validator(mode="after")
    def require_evidence(self):
        if self.status in (EvidenceStatus.SUPPORTED, EvidenceStatus.INFERRED) and not self.evidence_ids:
            raise ValueError(f"{self.status.value} claims require evidence_ids")
        if self.status == EvidenceStatus.MODEL_KNOWLEDGE and self.evidence_ids:
            raise ValueError("MODEL_KNOWLEDGE claims cannot cite paper evidence")
        if self.status == EvidenceStatus.LAB_RECORD and not self.experiment_refs:
            raise ValueError("LAB_RECORD claims require experiment_refs")
        if self.status != EvidenceStatus.LAB_RECORD and self.experiment_refs:
            raise ValueError("Only LAB_RECORD claims can cite experiment records")
        return self

class VariableIn(BaseModel):
    name: str
    value: Any
    unit: str | None = None
    material: str | None = None
    source_type: str = "lab"
    source_id: str | None = None

class StepIn(BaseModel):
    name: str
    step_type: str = "process"
    order_index: int = 0
    description: str = ""
    variables: list[VariableIn] = Field(default_factory=list)

class ProcessVariableUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=2000)
    unit: str | None = Field(default=None, max_length=80)

class ResultIn(BaseModel):
    key: str
    value: Any
    unit: str | None = None

class ExperimentMaterialIn(BaseModel):
    name: str
    amount: Any = ""
    unit: str | None = None
    role: str = ""
    lot_number: str = ""
    supplier: str = ""
    source_material_id: int | None = Field(default=None, ge=1)

class ObservationIn(BaseModel):
    category: str
    description: str
    severity: str | None = None

class EnvironmentRecordIn(BaseModel):
    step_index: int = Field(ge=0)
    phase: Literal["before", "during", "after"]
    temperature_c: float | None = None
    relative_humidity_percent: float | None = Field(default=None, ge=0, le=100)
    pressure_kpa: float | None = Field(default=None, gt=0)
    notes: str = ""
    measured_at: datetime | None = None

class StepLogIn(BaseModel):
    kind: Literal["measurement", "observation", "result"] = "measurement"
    label: str = Field(min_length=1, max_length=200)
    value: str = Field(default="", max_length=2000)
    unit: str | None = Field(default=None, max_length=80)
    notes: str = Field(default="", max_length=4000)
    occurred_at: datetime | None = None

class StageValueIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    value: str = Field(default="", max_length=2000)
    unit: str | None = Field(default=None, max_length=80)

class StageExperimentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    performed_at: datetime | None = None
    status: Literal["recorded", "success", "failed", "inconclusive"] = "recorded"
    conditions: list[StageValueIn] = Field(default_factory=list, max_length=100)
    results: list[StageValueIn] = Field(default_factory=list, max_length=100)
    notes: str = Field(default="", max_length=4000)

class ExperimentIn(BaseModel):
    code: str | None = None
    name: str
    target: str
    date: DateType | None = None
    duration_minutes: int | None = Field(default=None, ge=0, le=525600)
    operator: str | None = None
    notes: str = ""
    status: str = "planned"
    demo: bool = False
    topic_id: int | None = None
    method_version_id: int | None = None
    steps: list[StepIn] = Field(default_factory=list)
    materials: list[ExperimentMaterialIn] = Field(default_factory=list)
    results: list[ResultIn] = Field(default_factory=list)
    observations: list[ObservationIn] = Field(default_factory=list)
    environment_records: list[EnvironmentRecordIn] = Field(default_factory=list)

class ResearchTopicIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""

class ResearchMaterialIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str = ""
    unit: str = ""
    supplier: str = ""
    catalog_number: str = ""
    notes: str = ""

class MethodIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    category: str = "custom"
    process_map: list[dict[str, Any]] = Field(default_factory=list)
    condition_definitions: list[dict[str, Any]] = Field(default_factory=list)
    material_definitions: list[dict[str, Any]] = Field(default_factory=list)
    parent_version_id: int | None = None

class PaperOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int; title: str; authors: str; year: int | None; filename: str

class DesignRequest(BaseModel):
    target: str
    constraints: dict[str, Any] = Field(default_factory=dict)

class PHReagentDose(BaseModel):
    species: str = Field(min_length=1, max_length=32)
    amount_mmol: float | None = Field(default=None, ge=0)
    mass_g: float | None = Field(default=None, ge=0)
    concentration_mol_l: float | None = Field(default=None, ge=0)
    volume_ml: float | None = Field(default=None, ge=0)

class PHEstimateRequest(BaseModel):
    water_volume_ml: float = Field(gt=0, le=1000000)
    reagents: list[PHReagentDose] = Field(min_length=1, max_length=30)

class AqueousEquilibriumRequest(BaseModel):
    temperature_c: float = Field(ge=-20, le=150)
    pH: float = Field(ge=-2, le=16)
    totals_molal: dict[str, float] = Field(min_length=1, max_length=24)
    phases: list[str] = Field(default_factory=list, max_length=15)

class AqueousSweepRequest(AqueousEquilibriumRequest):
    pH_min: float = Field(ge=-2, le=16)
    pH_max: float = Field(ge=-2, le=16)
    points: int = Field(default=17, ge=3, le=31)

class ToolExecutionRequest(BaseModel):
    experiment_id: int
    tool_id: str = Field(min_length=3, max_length=120)
    inputs: dict = Field(default_factory=dict)
    analysis_run_id: int | None = None
    process_step_id: int | None = Field(default=None, ge=1)
    approval_confirmed: bool = False
    retry_failed: bool = False

class OpenFOAMRunRequest(BaseModel):
    approval_confirmed: bool = False
    retry_failed: bool = False

class StirredReactionPathRequest(AqueousEquilibriumRequest):
    titrant: Literal["HCl", "NaOH"]
    total_titrant_mmol: float = Field(gt=0, le=10000)
    duration_min: float = Field(gt=0, le=10000)
    points: int = Field(default=13, ge=3, le=31)
    tracked_element: str = Field(min_length=1, max_length=12)
    equilibrium_phase: str | None = None

class ProcessChange(BaseModel):
    experiment_id: int
    variable_name: str
    new_value: Any
    new_unit: str | None = None

class AssistantAsk(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    allow_general_knowledge: bool = True
    experiment_id: int | None = None
    topic_id: int | None = None
    context_scope: Literal["topic", "method", "step"] = "topic"
    context_step_name: str | None = Field(default=None, max_length=200)
    language: Literal["ko", "en"] = "ko"

class SimulationInputReviewRequest(BaseModel):
    experiment_id: int = Field(gt=0)
    language: Literal["ko", "en"] = "ko"

class AnalysisExplanation(BaseModel):
    summary: str = Field(min_length=1, max_length=1000)
    review_notes: list[str] = Field(default_factory=list, max_length=4)
    @model_validator(mode="after")
    def no_numeric_measurements(self):
        texts = [self.summary, *self.review_notes]
        spelled_counts = re.compile(r"\b(?:one|single|double|triple|first|second|third)\b|단일|한\s*개|하나|두\s*개|세\s*개|첫\s*번째|둘째|셋째", re.IGNORECASE)
        if any(any(character.isdigit() for character in text) or spelled_counts.search(text) for text in texts):
            raise ValueError("Gemma explanations must not restate or invent numeric measurements")
        if any(len(note) > 240 for note in self.review_notes):
            raise ValueError("Review notes must be concise")
        return self

class IntegratedAnalysisRequest(BaseModel):
    analysis_run_ids: list[int] = Field(default_factory=list, max_length=100)
    simulation_run_ids: list[int] = Field(default_factory=list, max_length=100)
    experiment_ids: list[int] = Field(default_factory=list, max_length=200)
    experiment_id: int | None = None
    goal: str = Field(min_length=3, max_length=1000)
    allow_general_knowledge: bool = True
    language: Literal["ko", "en"] = "ko"

class IntegratedAnalysisClaim(BaseModel):
    claim: str
    status: Literal["SUPPORTED", "INFERRED", "LAB_RECORD", "ANALYSIS_OUTPUT", "SIMULATION_OUTPUT", "MODEL_KNOWLEDGE", "UNKNOWN"]
    evidence_ids: list[int] = Field(default_factory=list)
    experiment_refs: list[int] = Field(default_factory=list)
    analysis_run_refs: list[int] = Field(default_factory=list)
    simulation_run_refs: list[int] = Field(default_factory=list)
    @model_validator(mode="after")
    def require_source(self):
        if self.status in {"SUPPORTED", "INFERRED"} and not self.evidence_ids:
            raise ValueError(f"{self.status} claims require paper evidence IDs")
        if self.status == "LAB_RECORD" and not self.experiment_refs:
            raise ValueError("LAB_RECORD claims require experiment references")
        if self.status == "ANALYSIS_OUTPUT" and not self.analysis_run_refs:
            raise ValueError("ANALYSIS_OUTPUT claims require measurement run references")
        if self.status == "SIMULATION_OUTPUT" and not self.simulation_run_refs:
            raise ValueError("SIMULATION_OUTPUT claims require simulation run references")
        if self.status == "MODEL_KNOWLEDGE" and (self.evidence_ids or self.experiment_refs or self.analysis_run_refs or self.simulation_run_refs):
            raise ValueError("MODEL_KNOWLEDGE claims cannot carry source references")
        if self.status in {"SUPPORTED", "INFERRED"} and (self.experiment_refs or self.analysis_run_refs):
            raise ValueError(f"{self.status} claims can cite paper evidence only")
        if self.status == "ANALYSIS_OUTPUT" and (self.evidence_ids or self.experiment_refs):
            raise ValueError("ANALYSIS_OUTPUT claims can cite measurement runs only")
        if self.status != "ANALYSIS_OUTPUT" and self.analysis_run_refs:
            raise ValueError("Only ANALYSIS_OUTPUT claims can reference measurement runs")
        if self.status != "SIMULATION_OUTPUT" and self.simulation_run_refs:
            raise ValueError("Only SIMULATION_OUTPUT claims can reference simulation runs")
        if self.status != "LAB_RECORD" and self.experiment_refs:
            raise ValueError("Only LAB_RECORD claims can reference experiment records")
        return self

class DecisionOption(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    change: str = Field(min_length=1, max_length=500)
    basis: Literal["PAPER_EVIDENCE", "LAB_PATTERN", "DATA_GAP"]
    rationale: str = Field(min_length=1, max_length=800)
    evidence_ids: list[int] = Field(default_factory=list, max_length=20)
    experiment_refs: list[int] = Field(default_factory=list, max_length=30)
    measure_next: str = Field(min_length=1, max_length=500)
    risk: str = Field(min_length=1, max_length=500)
    confidence: Literal["high", "medium", "low", "insufficient"]

    @model_validator(mode="after")
    def require_basis_reference(self):
        if self.basis == "PAPER_EVIDENCE" and not self.evidence_ids:
            raise ValueError("PAPER_EVIDENCE options require paper evidence IDs")
        if self.basis == "LAB_PATTERN" and not self.experiment_refs:
            raise ValueError("LAB_PATTERN options require experiment references")
        if self.basis == "DATA_GAP" and (self.evidence_ids or self.experiment_refs):
            raise ValueError("DATA_GAP options must not invent source references")
        return self

class DecisionBrief(BaseModel):
    summary: str = Field(min_length=1, max_length=1200)
    options: list[DecisionOption] = Field(default_factory=list, max_length=3)
    decision_note: str = Field(min_length=1, max_length=800)

class DecisionChoiceCandidate(BaseModel):
    id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    label: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=600)

class DecisionChoiceRequest(BaseModel):
    state: str | dict | list
    question: str = Field(min_length=3, max_length=800)
    options: list[DecisionChoiceCandidate] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def validate_choice(self):
        ids = [item.id for item in self.options]
        if len(set(ids)) != len(ids):
            raise ValueError("Decision option IDs must be unique")
        if len(json.dumps(self.state, ensure_ascii=False)) > 12000:
            raise ValueError("Decision state is too large; send a compact relevant state")
        return self

class MeasurementReviewRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    review_status: Literal["REVIEWED", "ACCEPTED", "REJECTED"]
    opinion: str = Field(default="", max_length=4000)
    reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def require_reasons_for_decisions(self):
        if self.review_status in {"ACCEPTED", "REJECTED"} and not self.reason.strip():
            raise ValueError("A reason is required when accepting or rejecting a measurement")
        return self
