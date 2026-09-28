from datetime import date as DateType, datetime
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

class Paper(Base):
    __tablename__ = "papers"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    authors: Mapped[str] = mapped_column(Text, default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filename: Mapped[str] = mapped_column(String(500))
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

class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    target: Mapped[str] = mapped_column(String(300))
    date: Mapped[DateType | None] = mapped_column(Date, nullable=True)
    operator: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30))
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    steps: Mapped[list["ProcessStep"]] = relationship(back_populates="experiment", cascade="all, delete-orphan", order_by="ProcessStep.order_index")
    results: Mapped[list["ExperimentResult"]] = relationship(back_populates="experiment", cascade="all, delete-orphan")
    observations: Mapped[list["FailureObservation"]] = relationship(back_populates="experiment", cascade="all, delete-orphan")

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
