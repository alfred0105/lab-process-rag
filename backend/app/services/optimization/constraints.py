"""Structured, deterministic continuous-constraint validation for GP/BO."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.optimize import linprog

from app.services.optimization.gpbo import OptimizationInputError
from app.services.scientific_data import _UNITS


def _as_base_unit(value: float, unit: str | None):
    try:
        quantity = _UNITS.Quantity(float(value), unit or "dimensionless")
        return float(quantity.to_base_units().magnitude), quantity.to_base_units().units
    except Exception as exc:
        raise OptimizationInputError("INCOMPATIBLE_UNITS: constraint contains an invalid unit") from exc


def _coefficient_to_constraint_unit(coefficient: float, coefficient_unit: str, feature_unit: str, constraint_unit: str) -> float:
    try:
        term = float(coefficient) * _UNITS.Unit(coefficient_unit) * _UNITS.Unit(feature_unit or "dimensionless")
        return float((1.0 * term).to(constraint_unit or "dimensionless").magnitude)
    except Exception as exc:
        raise OptimizationInputError("INCOMPATIBLE_UNITS: linear constraint terms do not share a unit") from exc


def compile_constraints(constraints: list[dict[str, Any]], feature_ids: list[str], feature_units: list[str | None]):
    """Normalize accepted constraints to A_ub/A_eq on model's base-unit X."""
    index = {identifier: i for i, identifier in enumerate(feature_ids)}
    n = len(feature_ids)
    inequalities: list[tuple[list[float], float, str]] = []
    equalities: list[tuple[list[float], float, str]] = []
    projection_equalities: list[tuple[list[float], float, str]] = []
    normalized: list[dict[str, Any]] = []
    for ordinal, item in enumerate(constraints):
        if not isinstance(item, dict):
            raise OptimizationInputError("UNSUPPORTED_CONSTRAINT: constraint must be an object")
        kind = item.get("type")
        constraint_id = str(item.get("constraint_id") or f"constraint-{ordinal + 1}")
        if kind in {"linear_inequality", "linear_equality"}:
            ids = item.get("parameter_ids")
            coefficients = item.get("coefficients")
            if not isinstance(ids, list) or not ids or not isinstance(coefficients, list) or len(ids) != len(coefficients):
                raise OptimizationInputError("UNSUPPORTED_CONSTRAINT: linear constraints need matching parameter_ids and coefficients")
            if len(set(ids)) != len(ids) or any(identifier not in index for identifier in ids):
                raise OptimizationInputError("UNSUPPORTED_CONSTRAINT: constraint references an unknown or repeated parameter")
            coefficient_units = item.get("coefficient_units")
            threshold_unit = item.get("unit") or "dimensionless"
            if coefficient_units is None:
                dims = []
                for identifier in ids:
                    _, dims_unit = _as_base_unit(1.0, feature_units[index[identifier]])
                    dims.append(str(dims_unit.dimensionality))
                if len(set(dims)) != 1:
                    raise OptimizationInputError("INCOMPATIBLE_UNITS: coefficient_units are required for mixed-dimension features")
                coefficient_units = ["dimensionless"] * len(ids)
            if len(coefficient_units) != len(ids):
                raise OptimizationInputError("UNSUPPORTED_CONSTRAINT: coefficient_units must match parameter_ids")
            row = [0.0] * n
            try:
                for identifier, coefficient, coefficient_unit in zip(ids, coefficients, coefficient_units):
                    if not math.isfinite(float(coefficient)):
                        raise ValueError
                    row[index[identifier]] = _coefficient_to_constraint_unit(
                        float(coefficient), coefficient_unit, feature_units[index[identifier]] or "dimensionless", threshold_unit)
                threshold = float(item["threshold"])
                tolerance = float(item.get("tolerance", 0.0))
                if kind == "linear_equality" and (not math.isfinite(tolerance) or tolerance < 0):
                    raise ValueError
                tolerance_base = tolerance
            except OptimizationInputError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise OptimizationInputError("UNSUPPORTED_CONSTRAINT: invalid coefficient, threshold, or tolerance") from exc
            if kind == "linear_inequality":
                sense = item.get("sense", "le")
                if sense not in {"le", "ge"}:
                    raise OptimizationInputError("UNSUPPORTED_CONSTRAINT: linear inequality sense must be le or ge")
                if sense == "ge":
                    row = [-value for value in row]; threshold = -threshold
                inequalities.append((row, threshold, constraint_id))
                normalized.append({**item, "constraint_id": constraint_id, "status": "COMPILED"})
            else:
                if tolerance_base:
                    inequalities.extend([(row, threshold + tolerance_base, constraint_id),
                                         ([-value for value in row], -threshold + tolerance_base, constraint_id)])
                    projection_equalities.append((row,threshold,constraint_id))
                else:
                    equalities.append((row, threshold, constraint_id))
                normalized.append({**item, "constraint_id": constraint_id, "status": "COMPILED"})
        elif kind == "variable_relation":
            left = item.get("left_parameter_id"); right = item.get("right_parameter_id")
            relation = item.get("relation", "ge")
            if left not in index or right not in index or left == right or relation not in {"ge", "le"}:
                raise OptimizationInputError("UNSUPPORTED_CONSTRAINT: invalid variable relation")
            _, left_unit = _as_base_unit(1.0, feature_units[index[left]])
            _, right_unit = _as_base_unit(1.0, feature_units[index[right]])
            if left_unit.dimensionality != right_unit.dimensionality:
                raise OptimizationInputError("INCOMPATIBLE_UNITS: related variables must have compatible dimensions")
            row = [0.0] * n
            row[index[left]] = 1.0; row[index[right]] = -1.0
            if relation == "ge": row = [-value for value in row]
            inequalities.append((row, 0.0, constraint_id))
            normalized.append({**item, "constraint_id": constraint_id, "status": "COMPILED"})
        else:
            raise OptimizationInputError("UNSUPPORTED_CONSTRAINT: supported types are linear_inequality, linear_equality, and variable_relation")
    # Deduplicate the exact equality branch above and check the polytope once.
    unique_equalities = []
    seen_eq = set()
    for row, threshold, identifier in equalities:
        key = (tuple(row), threshold, identifier)
        if key not in seen_eq:
            unique_equalities.append((row, threshold, identifier)); seen_eq.add(key)
    return normalized, inequalities, unique_equalities, projection_equalities


def feasible_mask(points, constraints, feature_ids, feature_units, bounds):
    normalized, inequalities, equalities, projection_equalities = compile_constraints(constraints, feature_ids, feature_units)
    x = np.asarray(points, dtype=float)
    lo = np.asarray(bounds, dtype=float)[:, 0]; hi = np.asarray(bounds, dtype=float)[:, 1]
    mask = np.all((x >= lo - 1e-10) & (x <= hi + 1e-10), axis=1)
    for row, threshold, _ in inequalities:
        mask &= np.asarray(x @ np.asarray(row) <= threshold + 1e-9)
    for row, threshold, _ in equalities:
        mask &= np.asarray(np.abs(x @ np.asarray(row) - threshold) <= 1e-8)
    return mask, normalized, inequalities, equalities, projection_equalities


def project_candidates_to_equalities(points, projection_equalities):
    x=np.asarray(points,dtype=float)
    if not projection_equalities:
        return x
    matrix=np.asarray([row for row,_,_ in projection_equalities],dtype=float)
    target=np.asarray([value for _,value,_ in projection_equalities],dtype=float)
    # Orthogonal projection toward the equality manifold. The API keeps the
    # original proposals too, because bounds may clip the useful direction.
    correction=(target[None,:]-x@matrix.T)@np.linalg.pinv(matrix@matrix.T)@matrix
    return x+correction


def constraints_feasible(bounds, inequalities, equalities):
    n = len(bounds)
    result = linprog(np.zeros(n), A_ub=[row for row, _, _ in inequalities] or None,
        b_ub=[value for _, value, _ in inequalities] or None,
        A_eq=[row for row, _, _ in equalities] or None,
        b_eq=[value for _, value, _ in equalities] or None,
        bounds=[tuple(pair) for pair in bounds], method="highs")
    return bool(result.success)
