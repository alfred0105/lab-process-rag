from datetime import date as DateType, datetime
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

class Paper(Base):
    __tablename__ = "papers"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    authors: Mapped[str] = mapped_column(Text, default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filename: Mapped[str] = mapped_column(String(500))
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("research_topics.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    chunks: Mapped[list["EvidenceChunk"]] = relationship(back_populates="paper", cascade="all, delete-orphan")

class EvidenceChunk(Base):
    __tablename__ = "evidence_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(300), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column(Integer)
    paper: Mapped[Paper] = relationship(back_populates="chunks")

class PaperSummary(Base):
    __tablename__ = "paper_summaries"
    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), unique=True, index=True)
    summary: Mapped[str] = mapped_column(Text)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    source_chunk_ids: Mapped[list] = mapped_column(JSON, default=list)
    method: Mapped[str] = mapped_column(String(40), default="extractive")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    paper: Mapped[Paper] = relationship()

class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    target: Mapped[str] = mapped_column(String(300))
    date: Mapped[DateType | None] = mapped_column(Date, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operator: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30))
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("research_topics.id"), nullable=True, index=True)
    method_version_id: Mapped[int | None] = mapped_column(ForeignKey("method_versions.id"), nullable=True, index=True)
    method_run_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    steps: Mapped[list["ProcessStep"]] = relationship(back_populates="experiment", cascade="all, delete-orphan", order_by="ProcessStep.order_index")
    materials: Mapped[list["ExperimentMaterial"]] = relationship(back_populates="experiment", cascade="all, delete-orphan")
    results: Mapped[list["ExperimentResult"]] = relationship(back_populates="experiment", cascade="all, delete-orphan")
    observations: Mapped[list["FailureObservation"]] = relationship(back_populates="experiment", cascade="all, delete-orphan")
    environment_records: Mapped[list["ExperimentEnvironmentRecord"]] = relationship(back_populates="experiment", cascade="all, delete-orphan", order_by="ExperimentEnvironmentRecord.measured_at")
    step_logs: Mapped[list["ProcessStepLog"]] = relationship(back_populates="experiment", cascade="all, delete-orphan", order_by="ProcessStepLog.occurred_at")
    attachments: Mapped[list["ExperimentAttachment"]] = relationship(back_populates="experiment", cascade="all, delete-orphan", order_by="ExperimentAttachment.created_at")
    stage_experiments: Mapped[list["ProcessStageExperiment"]] = relationship(back_populates="experiment", cascade="all, delete-orphan", order_by="ProcessStageExperiment.performed_at")
    topic: Mapped["ResearchTopic | None"] = relationship()
    method_version: Mapped["MethodVersion | None"] = relationship()

class ResearchTopic(Base):
    __tablename__ = "research_topics"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ResearchMaterial(Base):
    __tablename__ = "research_materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("research_topics.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    role: Mapped[str] = mapped_column(String(200), default="")
    unit: Mapped[str] = mapped_column(String(80), default="")
    supplier: Mapped[str] = mapped_column(String(200), default="")
    catalog_number: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    topic: Mapped[ResearchTopic] = relationship()

class ExperimentMethod(Base):
    __tablename__ = "experiment_methods"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("research_topics.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="custom")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    topic: Mapped[ResearchTopic] = relationship()
    versions: Mapped[list["MethodVersion"]] = relationship(back_populates="method", cascade="all, delete-orphan", order_by="MethodVersion.version_number")

class MethodVersion(Base):
    __tablename__ = "method_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    method_id: Mapped[int] = mapped_column(ForeignKey("experiment_methods.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    version_label: Mapped[str] = mapped_column(String(40), default="1")
    parent_version_id: Mapped[int | None] = mapped_column(ForeignKey("method_versions.id"), nullable=True)
    process_map: Mapped[list] = mapped_column(JSON, default=list)
    condition_definitions: Mapped[list] = mapped_column(JSON, default=list)
    material_definitions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    method: Mapped[ExperimentMethod] = relationship(back_populates="versions")

class ProcessStep(Base):
    __tablename__ = "process_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    step_type: Mapped[str] = mapped_column(String(100), default="process")
    order_index: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text, default="")
    experiment: Mapped[Experiment] = relationship(back_populates="steps")
    variables: Mapped[list["ProcessVariable"]] = relationship(back_populates="step", cascade="all, delete-orphan")
    environment_records: Mapped[list["ExperimentEnvironmentRecord"]] = relationship(back_populates="step", cascade="all, delete-orphan")
    logs: Mapped[list["ProcessStepLog"]] = relationship(back_populates="step", cascade="all, delete-orphan")
    attachments: Mapped[list["ExperimentAttachment"]] = relationship(back_populates="step", cascade="all, delete-orphan")
    stage_experiments: Mapped[list["ProcessStageExperiment"]] = relationship(back_populates="step", cascade="all, delete-orphan", order_by="ProcessStageExperiment.performed_at")

class ProcessStageExperiment(Base):
    """A focused/partial experiment performed within one process stage of a run."""
    __tablename__ = "process_stage_experiments"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    process_step_id: Mapped[int] = mapped_column(ForeignKey("process_steps.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    performed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    status: Mapped[str] = mapped_column(String(30), default="recorded")
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    results: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    experiment: Mapped[Experiment] = relationship(back_populates="stage_experiments")
    step: Mapped[ProcessStep] = relationship(back_populates="stage_experiments")

class ProcessVariable(Base):
    __tablename__ = "process_variables"
    id: Mapped[int] = mapped_column(primary_key=True)
    process_step_id: Mapped[int] = mapped_column(ForeignKey("process_steps.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    value: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    material: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), default="lab")
    source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    step: Mapped[ProcessStep] = relationship(back_populates="variables")

class ExperimentMaterial(Base):
    __tablename__ = "experiment_materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    amount: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    role: Mapped[str] = mapped_column(String(200), default="")
    lot_number: Mapped[str] = mapped_column(String(200), default="")
    supplier: Mapped[str] = mapped_column(String(200), default="")
    source_material_id: Mapped[int | None] = mapped_column(ForeignKey("research_materials.id", ondelete="SET NULL"), nullable=True, index=True)
    experiment: Mapped[Experiment] = relationship(back_populates="materials")
    source_material: Mapped["ResearchMaterial | None"] = relationship()

class ExperimentResult(Base):
    __tablename__ = "experiment_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"), index=True)
    key: Mapped[str] = mapped_column(String(200))
    value: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    experiment: Mapped[Experiment] = relationship(back_populates="results")

class FailureObservation(Base):
    __tablename__ = "failure_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"), index=True)
    category: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    experiment: Mapped[Experiment] = relationship(back_populates="observations")

class ExperimentEnvironmentRecord(Base):
    __tablename__ = "experiment_environment_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    process_step_id: Mapped[int] = mapped_column(ForeignKey("process_steps.id", ondelete="CASCADE"), index=True)
    phase: Mapped[str] = mapped_column(String(20))
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_humidity_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    pressure_kpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    measured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    experiment: Mapped[Experiment] = relationship(back_populates="environment_records")
    step: Mapped[ProcessStep] = relationship(back_populates="environment_records")

class ProcessStepLog(Base):
    __tablename__ = "process_step_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    process_step_id: Mapped[int] = mapped_column(ForeignKey("process_steps.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="measurement")
    label: Mapped[str] = mapped_column(String(200), default="")
    value: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    experiment: Mapped[Experiment] = relationship(back_populates="step_logs")
    step: Mapped[ProcessStep] = relationship(back_populates="logs")

class ExperimentAttachment(Base):
    __tablename__ = "experiment_attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    process_step_id: Mapped[int] = mapped_column(ForeignKey("process_steps.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100))
    stored_path: Mapped[str] = mapped_column(String(1000))
    caption: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    experiment: Mapped[Experiment] = relationship(back_populates="attachments")
    step: Mapped[ProcessStep] = relationship(back_populates="attachments")

class AssistantInteraction(Base):
    __tablename__ = "assistant_interactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("research_topics.id", ondelete="SET NULL"), nullable=True, index=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id", ondelete="SET NULL"), nullable=True, index=True)
    query: Mapped[str] = mapped_column(Text)
    allow_general_knowledge: Mapped[bool] = mapped_column(Boolean, default=True)
    context_scope: Mapped[str] = mapped_column(String(30), default="topic")
    context_label: Mapped[str] = mapped_column(String(300), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    response_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class MaterialAnalysisRun(Base):
    __tablename__ = "material_analysis_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id"), nullable=True, index=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("research_topics.id", ondelete="SET NULL"), nullable=True, index=True)
    modality: Mapped[str] = mapped_column(String(20), index=True)
    tool_id: Mapped[str] = mapped_column(String(100))
    filename: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    original_path: Mapped[str] = mapped_column(String(500))
    artifact_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result_json: Mapped[dict] = mapped_column(JSON)
    analysis_status: Mapped[str] = mapped_column(String(30), default="completed")
    result_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    process_step_id: Mapped[int | None] = mapped_column(ForeignKey("process_steps.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    review_events: Mapped[list["MeasurementReviewEvent"]] = relationship(back_populates="analysis_run", cascade="all, delete-orphan", order_by="MeasurementReviewEvent.id")

class IntegratedAnalysisSession(Base):
    __tablename__ = "integrated_analysis_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("research_topics.id", ondelete="CASCADE"), index=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id", ondelete="SET NULL"), nullable=True, index=True)
    goal: Mapped[str] = mapped_column(Text)
    allow_general_knowledge: Mapped[bool] = mapped_column(Boolean, default=True)
    model: Mapped[str] = mapped_column(String(200), default="")
    analysis_run_ids: Mapped[list] = mapped_column(JSON)
    simulation_run_ids: Mapped[list] = mapped_column(JSON, default=list)
    result_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class SimulationRun(Base):
    """Immutable-input record for a numerical simulation, separate from lab measurements."""
    __tablename__ = "simulation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_simulation_run_idempotency_key"),)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    error_code: Mapped[str] = mapped_column(String(100), default="")
    lease_generation: Mapped[int] = mapped_column(Integer, default=0)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    process_step_id: Mapped[int | None] = mapped_column(ForeignKey("process_steps.id", ondelete="SET NULL"), nullable=True, index=True)
    model_id: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    input_json: Mapped[dict] = mapped_column(JSON)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    log_text: Mapped[str] = mapped_column(Text, default="")
    error_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class WorkflowRun(Base):
    """Durable, topic-scoped scientific analysis workflow."""
    __tablename__ = "workflow_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("research_topics.id", ondelete="CASCADE"), index=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), index=True)
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    graph_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_text: Mapped[str] = mapped_column(Text, default="")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class WorkflowNode(Base):
    """A typed DAG node that is also independently claimable by a worker."""
    __tablename__ = "workflow_nodes"
    __table_args__ = (UniqueConstraint("workflow_id", "node_key", name="uq_workflow_node_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    node_key: Mapped[str] = mapped_column(String(100))
    tool_id: Mapped[str] = mapped_column(String(120))
    dependency_keys: Mapped[list] = mapped_column(JSON, default=list)
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_type: Mapped[str] = mapped_column(String(40), default="")
    result_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approval_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_generation: Mapped[int] = mapped_column(Integer, default=0)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    error_code: Mapped[str] = mapped_column(String(100), default="")
    error_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class ScientificObservation(Base):
    """Append-only normalized view of an original lab, literature, or model value."""
    __tablename__ = "scientific_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("research_topics.id", ondelete="SET NULL"), nullable=True, index=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), nullable=True, index=True)
    method_version_id: Mapped[int | None] = mapped_column(ForeignKey("method_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    process_step_id: Mapped[int | None] = mapped_column(ForeignKey("process_steps.id", ondelete="SET NULL"), nullable=True, index=True)
    parameter_id: Mapped[str] = mapped_column(String(300), index=True)
    material_id: Mapped[int | None] = mapped_column(ForeignKey("research_materials.id", ondelete="SET NULL"), nullable=True, index=True)
    original_value: Mapped[str] = mapped_column(Text)
    original_unit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    normalized_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalized_unit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    value_type: Mapped[str] = mapped_column(String(30), default="text")
    measurement_uncertainty: Mapped[float | None] = mapped_column(Float, nullable=True)
    replicate_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), index=True)
    source_id: Mapped[str] = mapped_column(String(200), index=True)
    analysis_run_id: Mapped[int | None] = mapped_column(ForeignKey("material_analysis_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    review_status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    normalization_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    review_events: Mapped[list["MeasurementReviewEvent"]] = relationship(back_populates="observation", cascade="all, delete-orphan", order_by="MeasurementReviewEvent.id")

class ScientificDataAuditEvent(Base):
    """Append-only audit for provenance/data corrections without deleting source rows."""
    __tablename__ = "scientific_data_audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    field_name: Mapped[str] = mapped_column(String(100))
    old_value: Mapped[dict] = mapped_column(JSON)
    new_value: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class MeasurementReviewEvent(Base):
    """Immutable review history; current status is the latest event for a run."""
    __tablename__ = "measurement_review_events"
    __table_args__ = (CheckConstraint("(analysis_run_id IS NOT NULL) != (observation_id IS NOT NULL)", name="ck_review_exactly_one_target"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_run_id: Mapped[int | None] = mapped_column(ForeignKey("material_analysis_runs.id", ondelete="CASCADE"), nullable=True, index=True)
    observation_id: Mapped[int | None] = mapped_column(ForeignKey("scientific_observations.id", ondelete="CASCADE"), nullable=True, index=True)
    review_status: Mapped[str] = mapped_column(String(30), index=True)
    reviewer: Mapped[str] = mapped_column(String(200))
    opinion: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    tool_id: Mapped[str] = mapped_column(String(100))
    tool_version: Mapped[str] = mapped_column(String(100), default="unknown")
    original_file_hash: Mapped[str] = mapped_column(String(64))
    settings_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    analysis_run: Mapped[MaterialAnalysisRun] = relationship(back_populates="review_events")
    observation: Mapped[ScientificObservation] = relationship(back_populates="review_events")

class OptimizationModelRun(Base):
    """Reproducible GP model run; JSON payload avoids executable serialization."""
    __tablename__ = "optimization_model_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("research_topics.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True, default="COMPLETED")
    dataset_hash: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(80))
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    model_json: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class OptimizationRecommendationRun(Base):
    """Immutable candidate recommendation record linked to a trained model."""
    __tablename__ = "optimization_recommendation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    model_run_id: Mapped[int] = mapped_column(ForeignKey("optimization_model_runs.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("research_topics.id", ondelete="CASCADE"), index=True)
    acquisition: Mapped[str] = mapped_column(String(20))
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    candidates_json: Mapped[list] = mapped_column(JSON, default=list)
    approval_status: Mapped[str] = mapped_column(String(30), default="PENDING_RESEARCHER_REVIEW")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class DecisionCase(Base):
    """Versioned decision example; synthetic labels are never represented as lab truth."""
    __tablename__ = "decision_cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("research_topics.id", ondelete="CASCADE"), index=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id", ondelete="SET NULL"), nullable=True, index=True)
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("decision_snapshots.id", ondelete="SET NULL"), nullable=True, index=True)
    feedback_id: Mapped[int | None] = mapped_column(ForeignKey("decision_feedback.id", ondelete="SET NULL"), nullable=True, index=True)
    case_group_id: Mapped[str] = mapped_column(String(200), index=True)
    state_json: Mapped[dict] = mapped_column(JSON, default=dict)
    features_json: Mapped[dict] = mapped_column(JSON, default=dict)
    feature_schema_version: Mapped[str] = mapped_column(String(40))
    candidate_actions_json: Mapped[list] = mapped_column(JSON, default=list)
    selected_action: Mapped[str] = mapped_column(String(40), index=True)
    label_source: Mapped[str] = mapped_column(String(40), index=True)
    reviewer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    review_status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    provenance_json: Mapped[dict] = mapped_column(JSON, default=dict)
    dataset_version: Mapped[str] = mapped_column(String(40), default="decision-dataset-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class DecisionModelRun(Base):
    """Serializable learned decision head and evaluation record."""
    __tablename__ = "decision_model_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("research_topics.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(30), default="COMPLETED", index=True)
    dataset_hash: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(80))
    feature_schema_version: Mapped[str] = mapped_column(String(40))
    dataset_version: Mapped[str] = mapped_column(String(40))
    model_json: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class DecisionSnapshot(Base):
    """Immutable state/features exactly as presented for one decision."""
    __tablename__ = "decision_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("research_topics.id", ondelete="CASCADE"), index=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id", ondelete="SET NULL"), nullable=True, index=True)
    method_version_id: Mapped[int | None] = mapped_column(ForeignKey("method_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    model_run_id: Mapped[int | None] = mapped_column(ForeignKey("decision_model_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    decision_timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    snapshot_timestamp: Mapped[datetime] = mapped_column(DateTime)
    data_availability_timestamp: Mapped[datetime] = mapped_column(DateTime)
    state_json: Mapped[dict] = mapped_column(JSON)
    feature_vector_json: Mapped[list] = mapped_column(JSON)
    suggested_action: Mapped[str] = mapped_column(String(40))
    # Added in 0011. NULL identifies historical snapshots whose action semantics
    # cannot be reconstructed without rewriting immutable records.
    raw_predicted_action: Mapped[str | None] = mapped_column(String(40), nullable=True)
    probabilities_json: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibration_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ood_status: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    ood_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    abstention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    safety_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    safety_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_contract_version: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    feature_schema_version: Mapped[str] = mapped_column(String(40))
    source_observation_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    source_analysis_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    source_simulation_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    source_optimization_model_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    provenance_json: Mapped[dict] = mapped_column(JSON, default=dict)
    snapshot_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class DecisionFeedback(Base):
    """Append-only researcher response to one model recommendation."""
    __tablename__ = "decision_feedback"
    __table_args__ = (UniqueConstraint("snapshot_id", "model_run_id", "revision", name="uq_decision_feedback_revision"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("research_topics.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("decision_snapshots.id", ondelete="CASCADE"), index=True)
    model_run_id: Mapped[int] = mapped_column(ForeignKey("decision_model_runs.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    feedback_type: Mapped[str] = mapped_column(String(20), index=True)
    suggested_action: Mapped[str] = mapped_column(String(40))
    final_reviewed_action: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reviewer: Mapped[str] = mapped_column(String(200))
    reviewer_identity_status: Mapped[str] = mapped_column(String(40), default="SELF_REPORTED_NOT_AUTHENTICATED")
    review_reason: Mapped[str] = mapped_column(Text, default="")
    review_status: Mapped[str] = mapped_column(String(30), default="RESEARCHER_REVIEWED", index=True)
    label_source: Mapped[str] = mapped_column(String(50))
    model_version: Mapped[str] = mapped_column(String(80))
    original_probabilities_json: Mapped[dict] = mapped_column(JSON, default=dict)
    ood_status: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    dataset_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    supersedes_feedback_id: Mapped[int | None] = mapped_column(ForeignKey("decision_feedback.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class DecisionDatasetVersion(Base):
    """Immutable, provenance-carrying training/evaluation dataset snapshot."""
    __tablename__ = "decision_dataset_versions"
    __table_args__ = (UniqueConstraint("topic_id", "mode", "dataset_version", name="uq_decision_dataset_topic_mode_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("research_topics.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    dataset_version: Mapped[str] = mapped_column(String(80))
    dataset_hash: Mapped[str] = mapped_column(String(64), index=True)
    feature_schema_version: Mapped[str] = mapped_column(String(40))
    label_mapping_version: Mapped[str] = mapped_column(String(40), default="decision-actions-v1")
    case_count: Mapped[int] = mapped_column(Integer)
    group_count: Mapped[int] = mapped_column(Integer)
    action_distribution_json: Mapped[dict] = mapped_column(JSON, default=dict)
    missingness_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    manifest_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class DecisionModelComparison(Base):
    """Evaluation report comparing two frozen models on the same held-out cases."""
    __tablename__ = "decision_model_comparisons"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("research_topics.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    champion_model_id: Mapped[int] = mapped_column(ForeignKey("decision_model_runs.id", ondelete="CASCADE"), index=True)
    challenger_model_id: Mapped[int] = mapped_column(ForeignKey("decision_model_runs.id", ondelete="CASCADE"), index=True)
    evaluation_hash: Mapped[str] = mapped_column(String(64), index=True)
    comparison_status: Mapped[str] = mapped_column(String(30), index=True)
    report_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class DecisionActiveShadowModel(Base):
    """One explicitly selected shadow model per topic and data mode."""
    __tablename__ = "decision_active_shadow_models"
    __table_args__ = (UniqueConstraint("topic_id", "mode", name="uq_decision_active_shadow_topic_mode"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("research_topics.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    model_run_id: Mapped[int] = mapped_column(ForeignKey("decision_model_runs.id", ondelete="RESTRICT"), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class DecisionModelActivationEvent(Base):
    """Append-only shadow activation and rollback audit trail."""
    __tablename__ = "decision_model_activation_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("research_topics.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    previous_model_id: Mapped[int | None] = mapped_column(ForeignKey("decision_model_runs.id", ondelete="SET NULL"), nullable=True)
    new_model_id: Mapped[int] = mapped_column(ForeignKey("decision_model_runs.id", ondelete="RESTRICT"), index=True)
    comparison_id: Mapped[int | None] = mapped_column(ForeignKey("decision_model_comparisons.id", ondelete="SET NULL"), nullable=True)
    reviewer: Mapped[str] = mapped_column(String(200))
    reviewer_identity_status: Mapped[str] = mapped_column(String(40), default="SELF_REPORTED_NOT_AUTHENTICATED")
    action: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
