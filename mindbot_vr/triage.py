from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher


def _normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _token_set(text: str) -> set[str]:
    n = _normalize_text(text)
    return set(n.split()) if n else set()


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _fuzzy_any(tokens: set[str], target: str, threshold: float = 0.84) -> bool:
    return any(_similarity(t, target) >= threshold for t in tokens)


def _contains_phrase(tokens: set[str], phrase: str) -> bool:
    words = phrase.split()
    if len(words) == 1:
        return words[0] in tokens or _fuzzy_any(tokens, words[0])
    return all(w in tokens or _fuzzy_any(tokens, w) for w in words)


SYMPTOM_SYNONYMS: dict[str, set[str]] = {
    "fever": {"fever", "temperature", "hot", "chills"},
    "cough": {"cough", "coughing"},
    "fatigue": {"fatigue", "tired", "exhausted", "weak"},
    "headache": {"headache", "migraine"},
    "breathing_difficulty": {"breathless", "wheeze", "wheezing", "dyspnea", "dyspnoea"},
    "chest_pain": {"chestpain", "angina", "tightness"},
}


def extract_symptoms(message: str) -> set[str]:
    tokens = _token_set(message)
    matched: set[str] = set()
    for canonical, variants in SYMPTOM_SYNONYMS.items():
        if any(v in tokens for v in variants):
            matched.add(canonical)
            continue
        if any(_fuzzy_any(tokens, v) for v in variants):
            matched.add(canonical)

    if _contains_phrase(tokens, "shortness of breath") or _contains_phrase(tokens, "trouble breathing"):
        matched.add("breathing_difficulty")
    if _contains_phrase(tokens, "chest pain") or _contains_phrase(tokens, "chest tightness"):
        matched.add("chest_pain")
    if "fever" not in matched and ("fever" in tokens or ("high" in tokens and "temperature" in tokens)):
        matched.add("fever")
    return matched


def _risk_level(score: int) -> str:
    if score >= 6:
        return "Critical"
    if score >= 3:
        return "Medium"
    return "Low"


@dataclass(frozen=True)
class TriageResult:
    matched_symptoms: set[str]
    risk_score: int
    risk_level: str
    recommendation: str
    hospital_needed: bool
    emergency_mode: bool
    red_flags: list[str]

    def to_public_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["matched_symptoms"] = sorted(self.matched_symptoms)
        return d


def score_risk(vitals: dict[str, float], matched_symptoms: set[str]) -> tuple[int, list[str]]:
    score = 0
    red_flags: list[str] = []

    # Hospital risk scoring rules (requested):
    # - Pulse > 110 → +2
    # - Temp > 38 → +2
    # - Chest pain → +4
    # - Breathing difficulty → +5
    pulse = float(vitals.get("pulse_bpm", 0))
    temp = float(vitals.get("temperature_c", 0))
    if pulse > 110:
        score += 2
        red_flags.append("High pulse detected (>110 BPM).")
    if temp > 38:
        score += 2
        red_flags.append("Fever detected (>38°C).")
    if "chest_pain" in matched_symptoms:
        score += 4
        red_flags.append("Chest pain reported.")
    if "breathing_difficulty" in matched_symptoms:
        score += 5
        red_flags.append("Breathing difficulty reported.")

    return score, red_flags


def build_recommendation(risk_level: str, matched_symptoms: set[str]) -> str:
    if risk_level == "Critical":
        return (
            "Critical risk detected. Activate emergency workflow and seek immediate medical evaluation. "
            "If symptoms are severe or rapidly worsening, call local emergency services."
        )

    if risk_level == "Medium":
        return (
            "Moderate risk detected. Monitor closely and consider evaluation by a clinician, especially "
            "if symptoms persist beyond 24–48 hours or worsen."
        )

    if not matched_symptoms:
        return "Describe your main symptoms (for example: fever + cough + fatigue) and how long they have lasted."

    if {"fever", "cough", "fatigue"}.issubset(matched_symptoms):
        return "Symptoms may fit a viral respiratory illness. Rest, hydrate, and monitor temperature."

    if {"fever", "headache"}.issubset(matched_symptoms):
        return (
            "Fever with headache can occur with viral illness. Seek urgent care if stiff neck, confusion, "
            "rash, or severe/worsening headache occurs."
        )

    return "Monitor symptoms, rest, hydrate, and seek care if symptoms worsen."


def triage_assess(message: str, vitals: dict[str, float]) -> TriageResult:
    matched = extract_symptoms(message)
    score, red_flags = score_risk(vitals, matched)
    level = _risk_level(score)
    emergency_mode = score >= 6
    hospital_needed = level in {"Medium", "Critical"}
    recommendation = build_recommendation(level, matched)
    if emergency_mode and not red_flags:
        red_flags = ["Critical risk score reached."]
    return TriageResult(
        matched_symptoms=matched,
        risk_score=int(score),
        risk_level=level,
        recommendation=recommendation,
        hospital_needed=hospital_needed,
        emergency_mode=emergency_mode,
        red_flags=red_flags,
    )


def vitals_alerts(pulse_bpm: float, temperature_c: float) -> list[str]:
    alerts: list[str] = []
    if pulse_bpm > 110:
        alerts.append("Pulse is high (> 110 BPM).")
    if temperature_c > 38:
        alerts.append("Fever alert: temperature is above 38°C.")
    return alerts


def clamp(v: float, lo: float, hi: float) -> float:
    return float(min(hi, max(lo, v)))


def smooth_step(prev: float, target: float, alpha: float = 0.22) -> float:
    alpha = clamp(alpha, 0.0, 1.0)
    return prev + (target - prev) * alpha


def round_vitals(vitals: dict[str, float]) -> dict[str, float]:
    return {
        "pulse_bpm": round(float(vitals["pulse_bpm"]), 1),
        "temperature_c": round(float(vitals["temperature_c"]), 1),
        "oxygen_percent": round(float(vitals["oxygen_percent"]), 1),
        "air_quality_ppm": round(float(vitals["air_quality_ppm"]), 0),
    }

