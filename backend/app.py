import json
import os
import math
import random
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file

try:
    from .db import close_db, get_db, init_db
    from .hospitals import HOSPITALS_BENI_SUEF
    from .medical_logic import MedicalAssessment, assess_symptoms, sanitize_user_text, vitals_alerts
except ImportError:
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from backend.db import close_db, get_db, init_db
    from backend.hospitals import HOSPITALS_BENI_SUEF
    from backend.medical_logic import MedicalAssessment, assess_symptoms, sanitize_user_text, vitals_alerts


BENI_SUEF_CENTER = {"lat": 29.0661, "lng": 31.0994}

_SESSION_VITALS_STATE: dict[str, dict[str, float]] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (math.sin(dphi / 2) ** 2) + math.cos(phi1) * math.cos(phi2) * (math.sin(dlambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def ensure_session(session_id: str | None) -> str:
    sid = (session_id or "").strip()
    if not sid:
        sid = uuid.uuid4().hex

    db = get_db()
    row = db.execute("SELECT id FROM sessions WHERE id = ?", (sid,)).fetchone()
    if row is None:
        db.execute("INSERT INTO sessions (id, created_at) VALUES (?, ?)", (sid, now_iso()))
        db.commit()
    return sid


def insert_message(session_id: str, role: str, content: str) -> None:
    db = get_db()
    db.execute(
        "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (session_id, role, content, now_iso()),
    )
    db.commit()


def insert_vitals(session_id: str, vitals: dict[str, float]) -> None:
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
            now_iso(),
        ),
    )
    db.commit()


def generate_vitals(session_id: str) -> dict[str, float]:
    state = _SESSION_VITALS_STATE.get(session_id)
    if state is None:
        state = {
            "pulse_bpm": random.uniform(72, 88),
            "temperature_c": random.uniform(36.4, 36.9),
            "oxygen_percent": random.uniform(96.0, 99.0),
            "air_quality_ppm": random.uniform(450, 850),
        }
        _SESSION_VITALS_STATE[session_id] = state

    state["pulse_bpm"] = float(min(150, max(45, state["pulse_bpm"] + random.uniform(-2.2, 2.6))))
    state["temperature_c"] = float(min(40.5, max(35.5, state["temperature_c"] + random.uniform(-0.05, 0.08))))
    state["oxygen_percent"] = float(min(100.0, max(88.0, state["oxygen_percent"] + random.uniform(-0.3, 0.25))))
    state["air_quality_ppm"] = float(min(2000, max(350, state["air_quality_ppm"] + random.uniform(-30, 45))))

    vitals = {
        "pulse_bpm": round(state["pulse_bpm"], 1),
        "temperature_c": round(state["temperature_c"], 1),
        "oxygen_percent": round(state["oxygen_percent"], 1),
        "air_quality_ppm": round(state["air_quality_ppm"], 0),
    }
    insert_vitals(session_id, vitals)
    return vitals


def nearest_hospital(lat: float, lng: float) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    best_dist = 10**9
    for h in HOSPITALS_BENI_SUEF:
        d = haversine_km(lat, lng, float(h["lat"]), float(h["lng"]))
        if d < best_dist:
            best_dist = d
            best = dict(h)
            best["distance_km"] = round(d, 2)
    return best or dict(HOSPITALS_BENI_SUEF[0])


def build_medical_reply(assessment: MedicalAssessment, alerts: list[str]) -> str:
    lines: list[str] = []
    if alerts:
        lines.append("Vitals alerts:")
        for a in alerts:
            lines.append(f"- {a}")
        lines.append("")
    if assessment.matched_symptoms:
        symptoms = ", ".join(sorted(assessment.matched_symptoms))
        lines.append(f"Matched symptoms: {symptoms}")
    if assessment.probable_condition:
        lines.append(f"Possible pattern: {assessment.probable_condition} (confidence {int(assessment.confidence * 100)}%)")
    lines.append(assessment.guidance)
    if assessment.red_flags:
        lines.append("")
        lines.append("Red flags:")
        for r in assessment.red_flags:
            lines.append(f"- {r}")
    lines.append("")
    lines.append("This is not a medical diagnosis. If symptoms are severe or worsening, seek professional care.")
    return "\n".join([l for l in lines if l is not None])


def try_llm_guidance(user_message: str) -> str | None:
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if not provider:
        return None
    if provider == "ollama":
        return _ollama_chat(user_message)
    if provider == "openai":
        return _openai_chat(user_message)
    return None


def _ollama_chat(user_message: str) -> str | None:
    base = os.environ.get("OLLAMA_URL", "http://localhost:11434").strip()
    model = os.environ.get("OLLAMA_MODEL", "llama3.1").strip()
    if not base or not model:
        return None
    url = f"{base.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a careful medical triage assistant. Provide brief, safe, non-diagnostic guidance. "
                    "Do not claim certainty. Encourage urgent care for red flags."
                ),
            },
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    try:
        import urllib.request

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = ((data or {}).get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    except Exception:
        return None
    return None


def _openai_chat(user_message: str) -> str | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
    if not api_key or not model:
        return None
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a careful medical triage assistant. Provide brief, safe, non-diagnostic guidance. "
                    "Do not claim certainty. Encourage urgent care for red flags."
                ),
            },
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
    }
    try:
        import urllib.request

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = (((data or {}).get("choices") or [{}])[0].get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    except Exception:
        return None
    return None


def create_app() -> Flask:
    init_db()
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.teardown_appcontext(close_db)

    google_maps_api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()

    @app.after_request
    def set_security_headers(resp: Any) -> Any:
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["X-Frame-Options"] = "SAMEORIGIN"
        resp.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        resp.headers["Permissions-Policy"] = "geolocation=(self)"

        csp = (
            "default-src 'self'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "frame-ancestors 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net https://maps.googleapis.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: https://maps.gstatic.com https://maps.googleapis.com https://www.google.com; "
            "connect-src 'self'; "
            "frame-src https://www.google.com https://maps.google.com https://www.google.com/maps;"
        )
        resp.headers["Content-Security-Policy"] = csp
        return resp

    @app.get("/")
    def home() -> Any:
        return render_template(
            "index.html",
            app_name="MindBot VR",
            maps_api_key=google_maps_api_key,
            beni_suef_center=BENI_SUEF_CENTER,
        )

    @app.get("/api/hospitals")
    def api_hospitals() -> Any:
        return jsonify({"hospitals": HOSPITALS_BENI_SUEF})

    @app.get("/api/vitals")
    def api_vitals() -> Any:
        session_id = ensure_session(request.args.get("session_id"))
        vitals = generate_vitals(session_id)
        alerts = vitals_alerts(vitals["pulse_bpm"], vitals["temperature_c"])
        return jsonify({"session_id": session_id, "vitals": vitals, "alerts": alerts, "ts": time.time()})

    @app.post("/api/ask_ai")
    def api_ask_ai() -> Any:
        payload = request.get_json(silent=True) or {}
        message = sanitize_user_text(str(payload.get("message", "")))
        session_id = ensure_session(payload.get("session_id"))

        if not message:
            return jsonify(
                {
                    "session_id": session_id,
                    "reply": "Type your symptoms (for example: fever + headache) and I will guide you.",
                    "assessment": None,
                }
            )

        insert_message(session_id, "user", message)
        vitals = generate_vitals(session_id)
        alerts = vitals_alerts(vitals["pulse_bpm"], vitals["temperature_c"])
        assessment = assess_symptoms(message)
        reply = build_medical_reply(assessment, alerts)
        llm_extra = try_llm_guidance(message)
        if llm_extra:
            reply = f"{reply}\n\nAdditional AI guidance:\n{llm_extra}"
        insert_message(session_id, "assistant", reply)

        return jsonify(
            {
                "session_id": session_id,
                "reply": reply,
                "assessment": asdict(assessment),
                "vitals": vitals,
                "alerts": alerts,
            }
        )

    @app.post("/ask_ai")
    def ask_ai() -> Any:
        return api_ask_ai()

    @app.post("/api/sos")
    def api_sos() -> Any:
        payload = request.get_json(silent=True) or {}
        try:
            lat = float(payload.get("lat", BENI_SUEF_CENTER["lat"]))
            lng = float(payload.get("lng", BENI_SUEF_CENTER["lng"]))
        except (TypeError, ValueError):
            lat = BENI_SUEF_CENTER["lat"]
            lng = BENI_SUEF_CENTER["lng"]
        hospital = nearest_hospital(lat, lng)
        return jsonify({"nearest_hospital": hospital, "input_location": {"lat": lat, "lng": lng}})

    @app.post("/sos")
    def sos() -> Any:
        return api_sos()

    @app.get("/api/report")
    def api_report() -> Any:
        session_id = ensure_session(request.args.get("session_id"))
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
        message_rows = db.execute(
            """
            SELECT role, content, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY id ASC
            LIMIT 30
            """,
            (session_id,),
        ).fetchall()

        buf = BytesIO()
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas

        c = canvas.Canvas(buf, pagesize=A4)
        width, height = A4

        x = 18 * mm
        y = height - 18 * mm
        c.setFont("Helvetica-Bold", 16)
        c.drawString(x, y, "MindBot VR — Medical Report")
        y -= 8 * mm
        c.setFont("Helvetica", 10)
        c.drawString(x, y, f"Session: {session_id}")
        y -= 5 * mm
        c.drawString(x, y, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        y -= 10 * mm

        c.setFont("Helvetica-Bold", 12)
        c.drawString(x, y, "Recent Vitals (latest 20)")
        y -= 6 * mm
        c.setFont("Helvetica", 10)
        for r in vitals_rows:
            line = (
                f"{r['created_at']}  |  Pulse {r['pulse_bpm']} BPM  |  Temp {r['temperature_c']} °C  |  "
                f"O₂ {r['oxygen_percent']}%  |  Air {r['air_quality_ppm']} ppm"
            )
            y = _pdf_draw_wrapped(c, x, y, width - 2 * x, line)
            y -= 2 * mm
            if y < 40 * mm:
                c.showPage()
                y = height - 18 * mm
                c.setFont("Helvetica", 10)

        y -= 6 * mm
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x, y, "Chat Summary (latest 30 messages)")
        y -= 6 * mm
        c.setFont("Helvetica", 10)
        for r in message_rows:
            role = "You" if r["role"] == "user" else "MindBot"
            line = f"[{r['created_at']}] {role}: {r['content']}"
            y = _pdf_draw_wrapped(c, x, y, width - 2 * x, line)
            y -= 2 * mm
            if y < 35 * mm:
                c.showPage()
                y = height - 18 * mm
                c.setFont("Helvetica", 10)

        c.save()
        buf.seek(0)

        filename = f"mindbot_vr_report_{session_id}.pdf"
        return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=filename)

    return app


def _pdf_draw_wrapped(c: Any, x: float, y: float, max_width: float, text: str) -> float:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    words = text.replace("\n", " ").split(" ")
    line = ""
    c.setFont(c._fontname, c._fontsize)
    for w in words:
        proposed = (line + " " + w).strip()
        if stringWidth(proposed, c._fontname, c._fontsize) <= max_width:
            line = proposed
            continue
        c.drawString(x, y, line)
        y -= 12
        line = w
    if line:
        c.drawString(x, y, line)
        y -= 12
    return y


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "").strip() == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
