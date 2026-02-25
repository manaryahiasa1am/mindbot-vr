from __future__ import annotations

import re

from flask import Response


def sanitize_user_text(text: str, max_len: int = 2000) -> str:
    text = (text or "").strip()
    if len(text) > max_len:
        text = text[:max_len]
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


def apply_security_headers(resp: Response, maps_enabled: bool) -> Response:
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    resp.headers["Permissions-Policy"] = "geolocation=(self)"

    script_src = ["'self'", "https://cdn.jsdelivr.net"]
    img_src = ["'self'", "data:", "https://maps.gstatic.com", "https://maps.googleapis.com", "https://www.google.com"]
    frame_src = ["https://www.google.com", "https://maps.google.com", "https://www.google.com/maps"]
    if maps_enabled:
        script_src += ["https://maps.googleapis.com"]

    csp = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'self'; "
        f"script-src {' '.join(script_src)}; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        f"img-src {' '.join(img_src)}; "
        "connect-src 'self'; "
        f"frame-src {' '.join(frame_src)};"
    )
    resp.headers["Content-Security-Policy"] = csp
    return resp
