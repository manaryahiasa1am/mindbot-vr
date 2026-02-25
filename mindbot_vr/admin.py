from __future__ import annotations

import csv
import os
from io import StringIO
from typing import Any

from flask import Blueprint, Response, jsonify, request

from .db import get_db


admin_bp = Blueprint("admin", __name__)


def _require_admin() -> bool:
    token = os.environ.get("ADMIN_TOKEN", "").strip()
    if not token:
        return False
    provided = request.headers.get("X-Admin-Token", "").strip()
    return provided == token


@admin_bp.get("/api/admin/stats")
def stats() -> Any:
    if not _require_admin():
        return jsonify({"error": "unauthorized"}), 401

    db = get_db()
    total_users = db.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"]
    emergencies = db.execute("SELECT COUNT(*) AS c FROM sos_events").fetchone()["c"]
    avg_score_row = db.execute("SELECT AVG(risk_score) AS avg_score FROM symptom_events").fetchone()
    avg_score = float(avg_score_row["avg_score"] or 0.0)
    return jsonify(
        {
            "total_users": int(total_users),
            "emergencies": int(emergencies),
            "average_risk_score": round(avg_score, 2),
        }
    )


@admin_bp.get("/api/admin/export")
def export_data() -> Any:
    if not _require_admin():
        return jsonify({"error": "unauthorized"}), 401

    db = get_db()
    rows = db.execute(
        """
        SELECT session_id, raw_message, matched_symptoms_json, risk_score, risk_level, hospital_needed, emergency_mode, created_at
        FROM symptom_events
        ORDER BY id DESC
        LIMIT 500
        """
    ).fetchall()

    out = StringIO()
    w = csv.writer(out)
    w.writerow(
        [
            "session_id",
            "raw_message",
            "matched_symptoms_json",
            "risk_score",
            "risk_level",
            "hospital_needed",
            "emergency_mode",
            "created_at",
        ]
    )
    for r in rows:
        w.writerow(
            [
                r["session_id"],
                r["raw_message"],
                r["matched_symptoms_json"],
                r["risk_score"],
                r["risk_level"],
                r["hospital_needed"],
                r["emergency_mode"],
                r["created_at"],
            ]
        )

    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=mindbot_vr_export.csv"},
    )

