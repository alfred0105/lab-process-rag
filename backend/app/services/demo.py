from datetime import date, datetime, timedelta
import math
from pathlib import Path

from sqlalchemy.orm import Session
from app.db.database import ROOT
from app.services.material_analysis.service import analyze as analyze_measurement, sha256 as sha256_bytes

from app.db.models import (
    Experiment,
    ExperimentEnvironmentRecord,
    ExperimentMaterial,
    ExperimentMethod,
    ExperimentResult,
    FailureObservation,
    MethodVersion,
    ProcessStep,
    ProcessStepLog,
    ProcessVariable,
    MaterialAnalysisRun,
    ProcessStageExperiment,
)


# Synthetic examples for demonstrating the workflow. These values are not literature evidence.
DATA = [
    ("Baseline growth", "success", 50, 70, 90, 60, 3, "Uniform coverage across the substrate; no visible precipitate.", {"nanowire_formed": ("true", None), "diameter_nm": ("75", "nm"), "length_um": ("1.2", "µm")}),
    ("Reduced seed cycles", "failure", 50, 70, 90, 60, 2, "Sparse growth; large areas of the substrate remained uncovered.", {"nanowire_formed": ("false", None), "coverage_percent": ("12", "%")}),
    ("Higher temperature", "success", 50, 70, 95, 60, 3, "Dense growth with a broader diameter distribution than baseline.", {"nanowire_formed": ("true", None), "diameter_nm": ("92", "nm"), "length_um": ("1.5", "µm")}),
    ("Short growth", "success", 50, 70, 90, 45, 3, "Nanowires formed, but median length was lower than baseline.", {"nanowire_formed": ("true", None), "diameter_nm": ("68", "nm"), "length_um": ("0.8", "µm")}),
    ("Low precursor", "failure", 25, 70, 90, 60, 3, "Solution became cloudy; only scattered short structures were observed.", {"nanowire_formed": ("false", None), "coverage_percent": ("8", "%")}),
    ("Extended growth", "partial_success", 50, 70, 90, 90, 3, "Long structures formed, with visible bundling and uneven coverage.", {"nanowire_formed": ("true", None), "diameter_nm": ("105", "nm"), "length_um": ("1.8", "µm")}),
]

STEPS = [
    ("Substrate and seed preparation", "Clean the substrate and apply the seed layer.", "preparation"),
    ("Hydrothermal growth", "React the seeded substrate in a sealed vessel.", "growth"),
    ("Washing and drying", "Rinse the sample and dry it before inspection.", "workup"),
    ("Microscopy review", "Record the synthetic demo morphology readout.", "characterization"),
]


def seed_demo(db: Session, topic_id: int):
    existing = db.query(Experiment).filter(Experiment.demo.is_(True), Experiment.topic_id == topic_id).order_by(Experiment.id).all()
    if existing:
        # Expand V0.1's original one-step demo records in place so users who
        # already seeded the demo can explore the richer timeline as well.
        _enrich_legacy_demo(db, existing)
        _seed_demo_partial_experiments(db, topic_id)
        _seed_demo_measurements(db, topic_id)
        return 0

    method = ExperimentMethod(
        topic_id=topic_id,
        name="Hydrothermal ZnO nanowire growth · demo",
        description="Synthetic workflow example with preparation, growth, workup, and microscopy records. All values are illustrative demo data, not paper evidence.",
        category="synthesis",
    )
    db.add(method)
    db.flush()
    condition_definitions = [
        {"step_name": step, "name": name, "unit": unit, "value_type": "number", "required": False}
        for step, fields in [
            (STEPS[0][0], [("Substrate cleaning", "min"), ("Seed coating cycles", "cycles"), ("Seed bake temperature", "°C")]),
            (STEPS[1][0], [("Zn concentration", "mM"), ("HMTA concentration", "mM"), ("Growth temperature", "°C"), ("Growth time", "min"), ("Seed cycles", "cycles")]),
            (STEPS[2][0], [("Rinse count", "cycles"), ("Drying temperature", "°C"), ("Drying time", "min")]),
            (STEPS[3][0], [("Microscope magnification", "×"), ("Fields inspected", "fields")]),
        ]
        for name, unit in fields
    ]
    version = MethodVersion(
        method_id=method.id,
        version_number=1,
        process_map=[{"name": name, "description": description, "step_type": kind} for name, description, kind in STEPS],
        condition_definitions=condition_definitions,
        material_definitions=[
            {"name": "Zinc nitrate", "role": "Zn precursor", "unit": "mmol"},
            {"name": "HMTA", "role": "mineralizer", "unit": "mmol"},
            {"name": "DI water", "role": "reaction solvent", "unit": "mL"},
            {"name": "Seeded glass substrate", "role": "growth surface", "unit": "piece"},
        ],
    )
    db.add(version)
    db.flush()

    for index, (name, status, zn, hmta, temp, growth_time, cycles, observation, results) in enumerate(DATA, 1):
        start = datetime(2026, 9, 28, 9, 0) + timedelta(days=index - 1)
        experiment = Experiment(
            code=f"DEMO-T{topic_id}-{index:03d}",
            name=name,
            target="ZnO nanowire morphology",
            date=date(2026, 9, 28) + timedelta(days=index - 1),
            duration_minutes=[165, 155, 175, 145, 180, 215][index - 1],
            operator="Demo researcher",
            status=status,
            demo=True,
            topic_id=topic_id,
            method_version_id=version.id,
            method_run_number=index,
            notes="DEMO DATA — synthetic illustrative records, not paper evidence or real measurements.",
        )
        db.add(experiment)
        db.flush()

        steps = []
        for order, (step_name, description, kind) in enumerate(STEPS):
            step = ProcessStep(experiment_id=experiment.id, name=step_name, step_type=kind, order_index=order, description=description)
            db.add(step)
            db.flush()
            steps.append(step)

        values_by_step = [
            [("substrate_cleaning", 10, "min"), ("seed_coating_cycles", cycles, "cycles"), ("seed_bake_temperature", 120, "°C")],
            [("zn_concentration", zn, "mM"), ("hmta_concentration", hmta, "mM"), ("growth_temperature", temp, "°C"), ("growth_time", growth_time, "min"), ("seed_cycles", cycles, "cycles")],
            [("rinse_count", 3, "cycles"), ("drying_temperature", 60, "°C"), ("drying_time", 30, "min")],
            [("microscope_magnification", 50000, "×"), ("fields_inspected", 5, "fields")],
        ]
        for step, variables in zip(steps, values_by_step):
            for key, value, unit in variables:
                db.add(ProcessVariable(process_step_id=step.id, name=key, value=str(value), unit=unit, source_type="demo"))

        for material_name, amount, unit, role in [
            ("Zinc nitrate", f"{zn * 0.003:.3f}", "mmol", "Zn precursor"),
            ("HMTA", f"{hmta * 0.003:.3f}", "mmol", "mineralizer"),
            ("DI water", "30", "mL", "reaction solvent"),
            ("Seeded glass substrate", "1", "piece", "growth surface"),
        ]:
            db.add(ExperimentMaterial(experiment_id=experiment.id, name=material_name, amount=amount, unit=unit, role=role, lot_number=f"DEMO-{index:02d}", supplier="Synthetic demo"))

        for key, (value, unit) in results.items():
            db.add(ExperimentResult(experiment_id=experiment.id, key=key, value=value, unit=unit))
        db.add(FailureObservation(experiment_id=experiment.id, category="demo_observation", description=observation, severity="informational" if status == "success" else "moderate"))

        # Stage-by-stage notes and ambient readings make the timeline demonstrable.
        notes = [
            ("Substrate cleaned and seed layer applied.", "No visible residue after rinse."),
            ("Precursor solution loaded into the reactor; sealed reaction started.", observation),
            ("Sample rinsed three times and dried at 60 °C.", "No sample loss during transfer."),
            ("Five fields inspected at 50,000×; synthetic morphology values recorded.", f"Demo readout: {', '.join(f'{key}={value[0]} {value[1] or ""}'.strip() for key, value in results.items())}"),
        ]
        for step_index, (first_note, second_note) in enumerate(notes):
            step = steps[step_index]
            db.add(ProcessStepLog(experiment_id=experiment.id, process_step_id=step.id, kind="observation", label="Process note", value=first_note, notes="Synthetic demo record", occurred_at=start + timedelta(minutes=step_index * 30)))
            if step_index in (1, 3):
                db.add(ProcessStepLog(experiment_id=experiment.id, process_step_id=step.id, kind="result" if step_index == 3 else "measurement", label="Intermediate observation" if step_index == 1 else "Morphology review", value=second_note, notes="Illustrative only; not an instrument file", occurred_at=start + timedelta(minutes=step_index * 30 + 10)))
            for phase, offset, temperature, humidity in [("before", -5, 22.0, 42.0), ("during", 10, 23.0, 40.0), ("after", 25, 22.5, 41.0)]:
                db.add(ExperimentEnvironmentRecord(experiment_id=experiment.id, process_step_id=step.id, phase=phase, temperature_c=temperature, relative_humidity_percent=humidity, notes="Synthetic room-condition demo value", measured_at=start + timedelta(minutes=step_index * 30 + offset)))

    db.commit()
    _seed_demo_partial_experiments(db, topic_id)
    _seed_demo_measurements(db, topic_id)
    return len(DATA)


def _seed_demo_partial_experiments(db: Session, topic_id: int) -> None:
    if db.query(ProcessStageExperiment).join(Experiment).filter(Experiment.topic_id == topic_id, ProcessStageExperiment.notes == "Synthetic demo partial experiment; illustrative only.").first():
        return
    experiments = db.query(Experiment).filter(Experiment.demo.is_(True), Experiment.topic_id == topic_id).order_by(Experiment.id).all()
    definitions = [
        (0, "Hydrothermal growth", "Growth temperature check A", "recorded", [("Growth temperature", "90", "°C"), ("Growth time", "60", "min")], [("Coverage", "uniform", None)], "A focused sub-experiment within the recorded growth stage."),
        (2, "Hydrothermal growth", "Growth temperature check B", "success", [("Growth temperature", "95", "°C"), ("Growth time", "60", "min")], [("Median diameter", "92", "nm"), ("Median length", "1.5", "µm")], "Illustrative comparison row; values mirror the linked synthetic run."),
        (3, "Washing and drying", "Drying-time check", "recorded", [("Drying temperature", "60", "°C"), ("Drying time", "30", "min")], [("Sample transfer loss", "none", None)], "A smaller check recorded within the workup stage."),
    ]
    for run_index, step_name, name, status, conditions, results, note in definitions:
        if run_index >= len(experiments):
            continue
        experiment = experiments[run_index]
        step = next((item for item in experiment.steps if item.name == step_name), None)
        if step:
            day = experiment.date or date.today()
            db.add(ProcessStageExperiment(experiment_id=experiment.id, process_step_id=step.id, name=name,
                performed_at=datetime.combine(day, datetime.min.time()).replace(hour=13), status=status,
                conditions=[{"name": key, "value": value, "unit": unit} for key, value, unit in conditions],
                results=[{"name": key, "value": value, "unit": unit} for key, value, unit in results],
                notes=f"{note} Synthetic demo partial experiment; illustrative only."))
    db.commit()


def _seed_demo_measurements(db: Session, topic_id: int) -> None:
    """Create reproducible sample instrument files and run them through the real pilot analyzers."""
    if db.query(MaterialAnalysisRun).filter(MaterialAnalysisRun.topic_id == topic_id, MaterialAnalysisRun.result_key.in_(["DEMO XRD · Baseline pattern", "DEMO AFM · Surface topography"])).first():
        return
    experiments = db.query(Experiment).filter(Experiment.demo.is_(True), Experiment.topic_id == topic_id).order_by(Experiment.id).all()
    if not experiments:
        return
    originals = ROOT / "data" / "material-analysis" / "originals"
    originals.mkdir(parents=True, exist_ok=True)
    # Synthetic peak pattern approximating a useful file shape; it is not instrument data or phase evidence.
    xrd_lines = ["two_theta,intensity"]
    for i in range(401):
        angle = 20.0 + i * 0.1
        intensity = 35 + 0.04 * i + sum(height * math.exp(-0.5 * ((angle - center) / width) ** 2) for center, height, width in [(31.8, 300, 0.22), (34.4, 520, 0.25), (36.2, 430, 0.24), (47.5, 170, 0.3), (56.6, 130, 0.32)])
        xrd_lines.append(f"{angle:.1f},{intensity:.4f}")
    xrd_bytes = ("\n".join(xrd_lines) + "\n").encode()
    # Deterministic tilted surface with a small bump pattern; the analyzer levels the plane before reporting roughness.
    afm_rows = []
    for row in range(32):
        values = []
        for col in range(32):
            bump = 5.0 * math.exp(-((col - 9) ** 2 + (row - 12) ** 2) / 22) + 3.5 * math.exp(-((col - 23) ** 2 + (row - 22) ** 2) / 18)
            texture = 0.35 * math.sin(col * 0.8) * math.cos(row * 0.6)
            values.append(f"{(0.08 * col + 0.04 * row + bump + texture):.4f}")
        afm_rows.append(",".join(values))
    afm_bytes = ("\n".join(afm_rows) + "\n").encode()
    samples = [
        (experiments[0], "Microscopy review", "xrd", "DEMO_XRD_baseline.csv", "DEMO XRD · Baseline pattern", xrd_bytes, "2theta_deg", 1.0),
        (experiments[min(2, len(experiments) - 1)], "Microscopy review", "afm", "DEMO_AFM_surface.csv", "DEMO AFM · Surface topography", afm_bytes, "nm", 1.0),
    ]
    for experiment, step_name, modality, filename, result_key, content, unit, _ in samples:
        step = next((item for item in experiment.steps if item.name == step_name), None)
        output = analyze_measurement(modality, content, filename, xrd_x_unit=unit, afm_height_unit=unit)
        stored = originals / f"demo-topic-{topic_id}-{modality}-{experiment.id}.csv"
        stored.write_bytes(content)
        result = {**output.result, "demo_data": True, "demo_notice": "Synthetic demonstration data generated by the app. Not a real instrument export, material measurement, or literature evidence."}
        db.add(MaterialAnalysisRun(experiment_id=experiment.id, topic_id=topic_id, process_step_id=step.id if step else None,
            modality=modality, tool_id=output.tool_id, filename=filename, sha256=sha256_bytes(content), original_path=str(stored),
            result_json=result, analysis_status="completed", result_key=result_key))
    db.commit()


def _enrich_legacy_demo(db: Session, experiments: list[Experiment]) -> None:
    for index, experiment in enumerate(experiments, 1):
        if not experiment.demo or experiment.notes.startswith("DEMO DATA — synthetic illustrative"):
            continue
        data = DATA[min(index, len(DATA)) - 1]
        _, status, zn, hmta, temp, growth_time, cycles, observation, results = data
        experiment.date = experiment.date or (date(2026, 9, 28) + timedelta(days=index - 1))
        experiment.duration_minutes = experiment.duration_minutes or [165, 155, 175, 145, 180, 215][min(index, 6) - 1]
        experiment.operator = experiment.operator or "Demo researcher"
        experiment.notes = "DEMO DATA — synthetic illustrative records, not paper evidence or real measurements."
        method_version = experiment.method_version
        if method_version:
            method_version.process_map = [{"name": name, "description": description, "step_type": kind} for name, description, kind in STEPS]
            method_version.condition_definitions = [
                {"step_name": step, "name": name, "unit": unit, "value_type": "number", "required": False}
                for step, fields in [
                    (STEPS[0][0], [("Substrate cleaning", "min"), ("Seed coating cycles", "cycles"), ("Seed bake temperature", "°C")]),
                    (STEPS[1][0], [("Zn concentration", "mM"), ("HMTA concentration", "mM"), ("Growth temperature", "°C"), ("Growth time", "min"), ("Seed cycles", "cycles")]),
                    (STEPS[2][0], [("Rinse count", "cycles"), ("Drying temperature", "°C"), ("Drying time", "min")]),
                    (STEPS[3][0], [("Microscope magnification", "×"), ("Fields inspected", "fields")]),
                ] for name, unit in fields
            ]
        step_by_name = {step.name: step for step in experiment.steps}
        for order, (name, description, kind) in enumerate(STEPS):
            step = step_by_name.get(name)
            if step is None:
                step = ProcessStep(experiment_id=experiment.id, name=name, step_type=kind, order_index=order, description=description)
                db.add(step)
                db.flush()
                step_by_name[name] = step
            else:
                step.order_index = order
                step.description = description
        variables_by_step = [
            [("substrate_cleaning", 10, "min"), ("seed_coating_cycles", cycles, "cycles"), ("seed_bake_temperature", 120, "°C")],
            [("zn_concentration", zn, "mM"), ("hmta_concentration", hmta, "mM"), ("growth_temperature", temp, "°C"), ("growth_time", growth_time, "min"), ("seed_cycles", cycles, "cycles")],
            [("rinse_count", 3, "cycles"), ("drying_temperature", 60, "°C"), ("drying_time", 30, "min")],
            [("microscope_magnification", 50000, "×"), ("fields_inspected", 5, "fields")],
        ]
        for (step_name, _, _), variables in zip(STEPS, variables_by_step):
            step = step_by_name[step_name]
            present = {variable.name for variable in step.variables}
            for key, value, unit in variables:
                if key not in present:
                    db.add(ProcessVariable(process_step_id=step.id, name=key, value=str(value), unit=unit, source_type="demo"))
        if not experiment.materials:
            for material_name, amount, unit, role in [("Zinc nitrate", f"{zn * .003:.3f}", "mmol", "Zn precursor"), ("HMTA", f"{hmta * .003:.3f}", "mmol", "mineralizer"), ("DI water", "30", "mL", "reaction solvent"), ("Seeded glass substrate", "1", "piece", "growth surface")]:
                db.add(ExperimentMaterial(experiment_id=experiment.id, name=material_name, amount=amount, unit=unit, role=role, lot_number=f"DEMO-{index:02d}", supplier="Synthetic demo"))
        for result in experiment.results:
            if result.key in results:
                result.unit = results[result.key][1]
        if not experiment.step_logs and not experiment.environment_records:
            start = datetime(2026, 9, 28, 9, 0) + timedelta(days=index - 1)
            for step_index, (step_name, _, _) in enumerate(STEPS):
                step = step_by_name[step_name]
                note = observation if step_index == 1 else ("Five synthetic microscopy fields inspected." if step_index == 3 else "Synthetic demo workflow stage recorded.")
                db.add(ProcessStepLog(experiment_id=experiment.id, process_step_id=step.id, kind="observation", label="Process note", value=note, notes="Synthetic demo record", occurred_at=start + timedelta(minutes=step_index * 30)))
                for phase, offset, temperature, humidity in [("before", -5, 22.0, 42.0), ("during", 10, 23.0, 40.0), ("after", 25, 22.5, 41.0)]:
                    db.add(ExperimentEnvironmentRecord(experiment_id=experiment.id, process_step_id=step.id, phase=phase, temperature_c=temperature, relative_humidity_percent=humidity, notes="Synthetic room-condition demo value", measured_at=start + timedelta(minutes=step_index * 30 + offset)))
    db.commit()
