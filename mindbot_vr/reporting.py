from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any


def _base_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _reports_dir() -> Path:
    d = _base_dir() / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def render_pdf_report(payload: dict[str, Any]) -> tuple[bytes, str]:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    x = 18 * mm
    y = height - 18 * mm
    c.setFont("Helvetica-Bold", 16)
    c.drawString(x, y, "MindBot VR — Hospital Triage Report")
    y -= 8 * mm
    c.setFont("Helvetica", 10)
    c.drawString(x, y, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    y -= 5 * mm
    c.drawString(x, y, f"Session: {payload.get('session_id','')}")
    y -= 10 * mm

    risk = payload.get("risk", {}) or {}
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y, "Patient Summary")
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    y = _draw_wrapped(
        c,
        x,
        y,
        width - 2 * x,
        f"Risk Level: {risk.get('risk_level','')}  |  Risk Score: {risk.get('risk_score','')}",
    )
    y -= 2 * mm
    y = _draw_wrapped(c, x, y, width - 2 * x, f"Recommendation: {risk.get('recommendation','')}")
    y -= 8 * mm

    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y, "Vital Readings (latest 20)")
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    for r in payload.get("vitals", []) or []:
        line = (
            f"{r.get('created_at','')}  |  Pulse {r.get('pulse_bpm','')} BPM  |  Temp {r.get('temperature_c','')} °C  |  "
            f"O₂ {r.get('oxygen_percent','')}%  |  Air {r.get('air_quality_ppm','')} ppm"
        )
        y = _draw_wrapped(c, x, y, width - 2 * x, line)
        y -= 2 * mm
        if y < 40 * mm:
            c.showPage()
            y = height - 18 * mm
            c.setFont("Helvetica", 10)

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y, "Symptom History (latest 20)")
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    for s in payload.get("symptoms", []) or []:
        line = (
            f"{s.get('created_at','')}  |  Score {s.get('risk_score','')} ({s.get('risk_level','')})  |  "
            f"Symptoms: {s.get('matched_symptoms','')}"
        )
        y = _draw_wrapped(c, x, y, width - 2 * x, line)
        y -= 2 * mm
        if y < 40 * mm:
            c.showPage()
            y = height - 18 * mm
            c.setFont("Helvetica", 10)

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y, "Emergency Actions")
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    sos_events = payload.get("sos_events", []) or []
    if not sos_events:
        y = _draw_wrapped(c, x, y, width - 2 * x, "No SOS activations recorded.")
    else:
        for e in sos_events:
            line = (
                f"{e.get('created_at','')}  |  Trigger: {e.get('trigger','')}  |  "
                f"{e.get('hospital_name','')}  |  {e.get('distance_km','')} km  |  ETA {e.get('eta_minutes','')} min"
            )
            y = _draw_wrapped(c, x, y, width - 2 * x, line)
            y -= 2 * mm
            if y < 40 * mm:
                c.showPage()
                y = height - 18 * mm
                c.setFont("Helvetica", 10)

    y -= 6 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y, "AI Analysis (latest 10)")
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    for m in payload.get("analysis", []) or []:
        line = f"[{m.get('created_at','')}] {m.get('content','')}"
        y = _draw_wrapped(c, x, y, width - 2 * x, line)
        y -= 2 * mm
        if y < 35 * mm:
            c.showPage()
            y = height - 18 * mm
            c.setFont("Helvetica", 10)

    y -= 6 * mm
    c.setFont("Helvetica", 9)
    y = _draw_wrapped(
        c,
        x,
        y,
        width - 2 * x,
        "Medical disclaimer: This system provides triage guidance and risk stratification only. "
        "It is not a diagnosis. Clinical judgment and local protocols must be followed.",
    )

    c.save()
    buf.seek(0)
    pdf_bytes = buf.read()

    session_id = str(payload.get("session_id") or "session")
    filename = f"mindbot_vr_hospital_report_{session_id}.pdf"
    try:
        (_reports_dir() / filename).write_bytes(pdf_bytes)
    except Exception:
        pass
    return pdf_bytes, filename


def _draw_wrapped(c: Any, x: float, y: float, max_width: float, text: str) -> float:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    words = str(text).replace("\n", " ").split(" ")
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

