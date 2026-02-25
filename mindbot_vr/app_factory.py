from __future__ import annotations

import json
import os
import random
import time
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

from flask import Flask, Response, jsonify, render_template, request, send_file

from .admin import admin_bp
from .db import close_db, get_db, init_db
from .geo import BENI_SUEF_CENTER, nearest_hospital
from .hospitals import HOSPITALS_BENI_SUEF
from .llm import try_llm_guidance
from .reporting import render_pdf_report
from .security import apply_security_headers, sanitize_user_text
from .triage import round_vitals, smooth_step, triage_assess, vitals_alerts


_SESSION_VITALS_STATE: dict[str, dict[str, float]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_session(session_id: str | None) -> str:
    sid = (session_id or "").strip()
    if not sid:
        sid = uuid.uuid4().hex

    db = get_db()
    row = db.execute("SELECT id FROM sessions WHERE id = ?", (sid,)).fetchone()
    if row is None:
        db.execute("INSERT INTO sessions (id, created_at) VALUES (?, ?)", (sid, _now_iso()))
        db.commit()
    return sid


def _insert_message(session_id: str, role: str, content: str) -> int:
    db = get_db()
    cur = db.execute(
        "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (session_id, role, content, _now_iso()),
    )
    db.commit()
    return int(cur.lastrowid)


def _insert_vitals(session_id: str, vitals: dict[str, float]) -> None:
    db = get_db()
    db.execute(
        """
        INSERT INTO vitals (session_id, pulse_bpm, temperature_c, oxygen_percent, air_quality_ppm, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            vitals["pulse_bpm"],
            vitals["temperature_c"],
            vitals["oxygen_percent"],
            vitals["air_quality_ppm"],
            _now_iso(),
        ),
    )
    db.commit()


def _insert_symptom_event(
    session_id: str,
    raw_message: str,
    matched_symptoms: list[str],
    risk_score: int,
    risk_level: str,
    recommendation: str,
    hospital_needed: bool,
    emergency_mode: bool,
) -> None:
    db = get_db()
    db.execute(
        """
        INSERT INTO symptom_events
          (session_id, raw_message, matched_symptoms_json, risk_score, risk_level, recommendation, hospital_needed, emergency_mode, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            raw_message,
            json.dumps(matched_symptoms, ensure_ascii=False),
            int(risk_score),
            risk_level,
            recommendation,
            1 if hospital_needed else 0,
            1 if emergency_mode else 0,
            _now_iso(),
        ),
    )
    db.commit()


def _insert_sos_event(
    session_id: str,
    trigger: str,
    lat: float,
    lng: float,
    hospital: dict[str, Any],
) -> None:
    db = get_db()
    db.execute(
        """
        INSERT INTO sos_events
          (session_id, trigger, lat, lng, hospital_id, hospital_name, hospital_phone, distance_km, eta_minutes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            trigger,
            float(lat),
            float(lng),
            str(hospital.get("id", "")),
            str(hospital.get("name", "")),
            str(hospital.get("phone", "")),
            float(hospital.get("distance_km", 0.0)),
            int(hospital.get("eta_minutes", 1)),
            _now_iso(),
        ),
    )
    db.commit()


def _generate_vitals(session_id: str) -> dict[str, float]:
    state = _SESSION_VITALS_STATE.get(session_id)
    if state is None:
        state = {
            "pulse_bpm": random.uniform(72, 88),
            "temperature_c": random.uniform(36.4, 36.9),
            "oxygen_percent": random.uniform(96.0, 99.0),
            "air_quality_ppm": random.uniform(450, 850),
        }
        _SESSION_VITALS_STATE[session_id] = state

    pulse_target = random.uniform(68, 96)
    temp_target = random.uniform(36.4, 37.2)
    if random.random() < 0.02:
        pulse_target = random.uniform(118, 140)
    if random.random() < 0.01:
        temp_target = random.uniform(38.2, 39.6)

    state["pulse_bpm"] = smooth_step(state["pulse_bpm"], pulse_target, alpha=0.15) + random.uniform(-1.2, 1.6)
    state["temperature_c"] = smooth_step(state["temperature_c"], temp_target, alpha=0.12) + random.uniform(-0.03, 0.05)
    state["oxygen_percent"] = smooth_step(state["oxygen_percent"], random.uniform(95.5, 99.2), alpha=0.15) + random.uniform(-0.2, 0.18)
    state["air_quality_ppm"] = smooth_step(state["air_quality_ppm"], random.uniform(420, 980), alpha=0.10) + random.uniform(-18, 25)

    vitals = round_vitals(state)
    _insert_vitals(session_id, vitals)
    return vitals


def create_app() -> Flask:
    init_db()
    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    app.teardown_appcontext(close_db)
    app.register_blueprint(admin_bp)

    google_maps_api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    maps_enabled = bool(google_maps_api_key)

    @app.after_request
    def _security(resp: Response) -> Response:
        return apply_security_headers(resp, maps_enabled=maps_enabled)

    @app.get("/")
    def home() -> Any:
        return render_template(
            "index.html",
            app_name="MindBot VR",
            maps_api_key=google_maps_api_key,
            beni_suef_center=BENI_SUEF_CENTER,
        )

    @app.get("/admin")
    def admin_page() -> Any:
        return render_template("admin.html", app_name="MindBot VR")

    @app.get("/api/hospitals")
    def api_hospitals() -> Any:
        return jsonify({"hospitals": HOSPITALS_BENI_SUEF})

    @app.get("/api/vitals")
    def api_vitals() -> Any:
        session_id = _ensure_session(request.args.get("session_id"))
        vitals = _generate_vitals(session_id)
        alerts = vitals_alerts(vitals["pulse_bpm"], vitals["temperature_c"])
        triage = triage_assess("", vitals)
        return jsonify(
            {
                "session_id": session_id,
                "vitals": vitals,
                "alerts": alerts,
                "risk": {
                    "risk_level": triage.risk_level,
                    "risk_score": triage.risk_score,
                    "hospital_needed": triage.hospital_needed,
                    "recommendation": triage.recommendation,
                    "emergency_mode": triage.emergency_mode,
                },
                "ts": time.time(),
            }
        )

    @app.post("/api/ask_ai")
    def api_ask_ai() -> Any:
        payload = request.get_json(silent=True) or {}
        message = sanitize_user_text(str(payload.get("message", "")))
        session_id = _ensure_session(payload.get("session_id"))

        lat = payload.get("lat")
        lng = payload.get("lng")
        try:
            lat_f = float(lat) if lat is not None else float(BENI_SUEF_CENTER["lat"])
            lng_f = float(lng) if lng is not None else float(BENI_SUEF_CENTER["lng"])
        except (TypeError, ValueError):
            lat_f = float(BENI_SUEF_CENTER["lat"])
            lng_f = float(BENI_SUEF_CENTER["lng"])

        if not message:
            vitals = _generate_vitals(session_id)
            triage = triage_assess("", vitals)
            return jsonify(
                {
                    "session_id": session_id,
                    "reply": "Describe symptoms (example: fever + cough + fatigue) and duration.",
                    "risk": {
                        "risk_level": triage.risk_level,
                        "risk_score": triage.risk_score,
                        "recommendation": triage.recommendation,
                        "hospital_needed": triage.hospital_needed,
                        "emergency_mode": triage.emergency_mode,
                    },
                }
            )

        _insert_message(session_id, "user", message)
        vitals = _generate_vitals(session_id)
        triage = triage_assess(message, vitals)

        _insert_symptom_event(
            session_id=session_id,
            raw_message=message,
            matched_symptoms=sorted(triage.matched_symptoms),
            risk_score=triage.risk_score,
            risk_level=triage.risk_level,
            recommendation=triage.recommendation,
            hospital_needed=triage.hospital_needed,
            emergency_mode=triage.emergency_mode,
        )

        lines: list[str] = []
        lines.append(f"Risk level: {triage.risk_level} (score {triage.risk_score})")
        if triage.matched_symptoms:
            lines.append(f"Detected symptoms: {', '.join(sorted(triage.matched_symptoms))}")
        if triage.red_flags:
            lines.append("Clinical red flags:")
            lines.extend([f"- {rf}" for rf in triage.red_flags])
        lines.append(triage.recommendation)
        lines.append("")
        lines.append("Medical disclaimer: This is triage guidance, not a diagnosis. Follow local protocols.")

        llm_extra = try_llm_guidance(message)
        if llm_extra:
            lines.append("")
            lines.append("Additional AI guidance:")
            lines.append(llm_extra)

        nearest = None
        if triage.emergency_mode:
            nearest = nearest_hospital(lat_f, lng_f)
            _insert_sos_event(session_id=session_id, trigger="auto", lat=lat_f, lng=lng_f, hospital=nearest)

        reply = "\n".join(lines)
        _insert_message(session_id, "assistant", reply)

        return jsonify(
            {
                "session_id": session_id,
                "reply": reply,
                "vitals": vitals,
                "alerts": vitals_alerts(vitals["pulse_bpm"], vitals["temperature_c"]),
                "risk": {
                    "risk_level": triage.risk_level,
                    "risk_score": triage.risk_score,
                    "recommendation": triage.recommendation,
                    "hospital_needed": triage.hospital_needed,
                    "emergency_mode": triage.emergency_mode,
                },
                "triage": triage.to_public_dict(),
                "auto_emergency": {"enabled": triage.emergency_mode, "nearest_hospital": nearest},
            }
        )

    @app.post("/ask_ai")
    def ask_ai() -> Any:
        return api_ask_ai()

    @app.post("/api/sos")
    def api_sos() -> Any:
        payload = request.get_json(silent=True) or {}
        session_id = _ensure_session(payload.get("session_id"))
        try:
            lat = float(payload.get("lat", BENI_SUEF_CENTER["lat"]))
            lng = float(payload.get("lng", BENI_SUEF_CENTER["lng"]))
        except (TypeError, ValueError):
            lat = float(BENI_SUEF_CENTER["lat"])
            lng = float(BENI_SUEF_CENTER["lng"])
        hospital = nearest_hospital(lat, lng)
        _insert_sos_event(session_id=session_id, trigger="manual", lat=lat, lng=lng, hospital=hospital)
        return jsonify({"session_id": session_id, "nearest_hospital": hospital, "input_location": {"lat": lat, "lng": lng}})

    @app.post("/sos")
    def sos() -> Any:
        return api_sos()

    @app.get("/api/report")
    def api_report() -> Any:
        session_id = _ensure_session(request.args.get("session_id"))
        db = get_db()
        vitals_rows = db.execute(
            """
            SELECT pulse_bpm, temperature_c, oxygen_percent, air_quality_ppm, created_at
            FROM vitals
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT 20
            """,
            (session_id,),
        ).fetchall()
        symptom_rows = db.execute(
            """
            SELECT matched_symptoms_json, risk_score, risk_level, created_at
            FROM symptom_events
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT 20
            """,
            (session_id,),
        ).fetchall()
        sos_rows = db.execute(
            """
            SELECT trigger, hospital_name, distance_km, eta_minutes, created_at
            FROM sos_events
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT 20
            """,
            (session_id,),
        ).fetchall()
        analysis_rows = db.execute(
            """
            SELECT content, created_at
            FROM messages
            WHERE session_id = ? AND role = 'assistant'
            ORDER BY id DESC
            LIMIT 10
            """,
            (session_id,),
        ).fetchall()
        last_symptom = db.execute(
            """
            SELECT risk_score, risk_level, recommendation
            FROM symptom_events
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        risk = {
            "risk_score": int(last_symptom["risk_score"]) if last_symptom else 0,
            "risk_level": str(last_symptom["risk_level"]) if last_symptom else "Low",
            "recommendation": str(last_symptom["recommendation"]) if last_symptom else "",
        }

        payload = {
            "session_id": session_id,
            "risk": risk,
            "vitals": [dict(r) for r in vitals_rows],
            "symptoms": [
                {
                    "matched_symptoms": (json.loads(r["matched_symptoms_json"]) if r["matched_symptoms_json"] else []),
                    "risk_score": int(r["risk_score"]),
                    "risk_level": str(r["risk_level"]),
                    "created_at": str(r["created_at"]),
                }
                for r in symptom_rows
            ],
            "sos_events": [dict(r) for r in sos_rows],
            "analysis": [dict(r) for r in analysis_rows],
        }

        pdf_bytes, filename = render_pdf_report(payload)
        return send_file(BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True, download_name=filename)

    return app
