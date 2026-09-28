from datetime import date as DateType
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator

class EvidenceStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"

class Claim(BaseModel):
    claim: str
    status: EvidenceStatus
    evidence_ids: list[int] = Field(default_factory=list)
    @model_validator(mode="after")
    def require_evidence(self):
        if self.status in (EvidenceStatus.SUPPORTED, EvidenceStatus.INFERRED) and not self.evidence_ids:
            raise ValueError(f"{self.status.value} claims require evidence_ids")
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

class ResultIn(BaseModel):
    key: str
    value: Any
    unit: str | None = None

class ObservationIn(BaseModel):
    category: str
    description: str
    severity: str | None = None

class ExperimentIn(BaseModel):
    code: str | None = None
    name: str
    target: str
    date: DateType | None = None
    operator: str | None = None
    notes: str = ""
    status: str = "planned"
    demo: bool = False
    steps: list[StepIn] = Field(default_factory=list)
    results: list[ResultIn] = Field(default_factory=list)
    observations: list[ObservationIn] = Field(default_factory=list)

class PaperOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int; title: str; authors: str; year: int | None; filename: str

class DesignRequest(BaseModel):
    target: str
    constraints: dict[str, Any] = Field(default_factory=dict)

class ProcessChange(BaseModel):
    experiment_id: int
    variable_name: str
    new_value: Any
    new_unit: str | None = None
