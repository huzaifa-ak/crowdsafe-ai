"""Comparisons.

    POST /api/comparisons        compare two stored runs and save the result
    GET  /api/comparisons/<id>   fetch a saved comparison
    GET  /api/comparisons        list saved comparisons

A comparison stores its own summary rather than recomputing on read. The runs
it points at carry their own venue snapshots, so a saved comparison keeps
meaning the two layouts it was made from even after both have been edited.
"""

import json

from flask import Blueprint, jsonify, request, url_for

from ..analysis.comparison import compare
from ..db import repository
from .errors import NotFoundError, ValidationError
from .simulations import load_run

bp = Blueprint("comparisons", __name__, url_prefix="/api/comparisons")


def _simulation_id(body: dict, field: str) -> int:
    value = body.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(
            "Two simulation ids are required.",
            [{"field": field, "message": f"{field} must be the id of a stored run"}],
        )
    return value


@bp.post("")
def create_comparison():
    body = request.get_json(silent=True)
    if body is None:
        raise ValidationError(
            "Expected a JSON body.",
            [{"field": "body", "message": "send JSON with Content-Type: application/json"}],
        )

    baseline_id = _simulation_id(body, "baseline_simulation_id")
    variant_id = _simulation_id(body, "variant_simulation_id")
    if baseline_id == variant_id:
        raise ValidationError(
            "A run cannot be compared with itself.",
            [{"field": "variant_simulation_id",
              "message": "choose two different runs"}],
        )

    baseline = load_run(baseline_id, with_trace=False)
    variant = load_run(variant_id, with_trace=False)

    summary = compare(baseline, variant)
    comparison_id = repository.create_comparison(
        name=body.get("name"),
        baseline_result_id=repository.result_id_for_simulation(baseline_id),
        variant_result_id=repository.result_id_for_simulation(variant_id),
        summary_json=json.dumps(summary),
    )

    response = jsonify(_payload(comparison_id, body.get("name"), baseline_id,
                                variant_id, summary))
    response.status_code = 201
    response.headers["Location"] = url_for("comparisons.get_comparison",
                                           comparison_id=comparison_id)
    return response


@bp.get("/<int:comparison_id>")
def get_comparison(comparison_id: int):
    row = repository.get_comparison(comparison_id)
    if row is None:
        raise NotFoundError(f"No comparison with id {comparison_id}.")

    return jsonify(_payload(
        row["id"],
        row["name"],
        repository.simulation_id_for_result(row["baseline_result_id"]),
        repository.simulation_id_for_result(row["variant_result_id"]),
        json.loads(row["summary_json"]),
        created_at=row["created_at"],
    ))


@bp.get("")
def list_comparisons():
    return jsonify(repository.list_comparisons())


def _payload(comparison_id, name, baseline_id, variant_id, summary, created_at=None):
    payload = {
        "id": comparison_id,
        "name": name,
        "baseline_simulation_id": baseline_id,
        "variant_simulation_id": variant_id,
        "summary": summary,
    }
    if created_at:
        payload["created_at"] = created_at
    return payload
