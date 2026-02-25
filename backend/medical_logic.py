import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable


def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def token_set(text: str) -> set[str]:
    text = normalize_text(text)
    if not text:
        return set()
    return set(text.split())


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def any_fuzzy_contains(tokens: set[str], phrase: str, threshold: float = 0.84) -> bool:
    phrase_tokens = phrase.split()
    if len(phrase_tokens) == 1:
        target = phrase_tokens[0]
        return any(similarity(t, target) >= threshold for t in tokens)
    normalized = " ".join(sorted(tokens))
    phrase_norm = " ".join(phrase_tokens)
    return similarity(normalized, phrase_norm) >= threshold


SYMPTOM_SYNONYMS: dict[str, set[str]] = {
    "fever": {"fever", "high", "temperature", "hot", "chills"},
    "headache": {"headache", "migraine", "head", "pain"},
    "cough": {"cough", "coughing"},
    "sore throat": {"throat", "sore", "pharyngitis"},
    "fatigue": {"fatigue", "tired", "exhausted", "weak"},
    "nausea": {"nausea", "nauseous", "queasy"},
    "vomiting": {"vomit", "vomiting", "throwing", "up"},
    "diarrhea": {"diarrhea", "diarrhoea", "loose", "stool"},
    "body aches": {"aches", "ache", "body", "muscle", "pain"},
    "dizziness": {"dizzy", "dizziness", "lightheaded"},
    "shortness of breath": {"shortness", "breath", "breathing", "wheeze"},
}


CONDITIONS: list[dict[str, object]] = [
    {
        "name": "Flu-like illness",
        "symptoms": {"fever", "headache", "body aches", "fatigue", "cough", "sore throat"},
        "advice": (
            "Your symptoms fit a flu-like pattern. Rest, hydrate, and monitor your temperature. "
            "Consider acetaminophen/paracetamol for fever if safe for you."
        ),
    },
    {
        "name": "Migraine / primary headache",
        "symptoms": {"headache", "nausea", "fatigue", "dizziness"},
        "advice": (
            "This may be consistent with a migraine or primary headache. Hydrate, rest in a dark room, "
            "and consider your usual headache medication if appropriate."
        ),
    },
    {
        "name": "Gastroenteritis / food-related illness",
        "symptoms": {"nausea", "vomiting", "diarrhea", "fever"},
        "advice": (
            "This pattern can be consistent with gastroenteritis. Focus on hydration (oral rehydration), "
            "eat light foods, and monitor for dehydration."
        ),
    },
    {
        "name": "Dehydration / heat stress",
        "symptoms": {"dizziness", "fatigue", "headache"},
        "advice": (
            "This may suggest dehydration or heat stress. Drink water/rehydration fluids and rest. "
            "If symptoms persist or worsen, seek medical advice."
        ),
    },
]


def extract_symptoms(message: str) -> set[str]:
    tokens = token_set(message)
    matched: set[str] = set()
    for canonical, variants in SYMPTOM_SYNONYMS.items():
        if any(v in tokens for v in variants):
            matched.add(canonical)
            continue
        if any(any_fuzzy_contains(tokens, v) for v in variants):
            matched.add(canonical)
    if "sore" in tokens and "throat" in tokens:
        matched.add("sore throat")
    if ("shortness" in tokens and "breath" in tokens) or ("breathing" in tokens and "hard" in tokens):
        matched.add("shortness of breath")
    return matched


@dataclass(frozen=True)
class MedicalAssessment:
    matched_symptoms: set[str]
    probable_condition: str | None
    confidence: float
    guidance: str
    red_flags: list[str]


def assess_symptoms(message: str) -> MedicalAssessment:
    matched = extract_symptoms(message)
    if not matched:
        return MedicalAssessment(
            matched_symptoms=set(),
            probable_condition=None,
            confidence=0.0,
            guidance=(
                "Tell me your main symptoms and how long they've been happening (for example: "
                "fever + headache for 2 days)."
            ),
            red_flags=[],
        )

    best_name: str | None = None
    best_score = 0.0
    best_advice = ""
    for c in CONDITIONS:
        symptoms: set[str] = set(c["symptoms"])  # type: ignore[assignment]
        overlap = len(matched.intersection(symptoms))
        score = overlap / max(1, len(symptoms))
        if score > best_score:
            best_score = score
            best_name = str(c["name"])
            best_advice = str(c["advice"])

    red_flags: list[str] = []
    if "shortness of breath" in matched:
        red_flags.append("Shortness of breath can be urgent. Consider emergency care if severe.")
    if "vomiting" in matched and "diarrhea" in matched:
        red_flags.append("Persistent vomiting/diarrhea can cause dehydration. Seek care if unable to keep fluids down.")

    confidence = float(min(0.95, math.sqrt(best_score)))
    guidance = best_advice or "Monitor symptoms and consider contacting a clinician."
    if matched == {"headache", "fever"} or ({"headache", "fever"}.issubset(matched)):
        guidance = (
            "Headache with fever can occur with viral illness. If you have stiff neck, confusion, "
            "severe headache, rash, or worsening symptoms, seek urgent medical evaluation."
        )

    return MedicalAssessment(
        matched_symptoms=matched,
        probable_condition=best_name,
        confidence=confidence,
        guidance=guidance,
        red_flags=red_flags,
    )


def vitals_alerts(pulse_bpm: float, temperature_c: float) -> list[str]:
    alerts: list[str] = []
    if pulse_bpm > 110:
        alerts.append("Pulse is high (> 110 BPM). Consider rest and monitoring.")
    if temperature_c > 38:
        alerts.append("Fever alert: temperature is above 38°C.")
    return alerts


def sanitize_user_text(text: str, max_len: int = 2000) -> str:
    text = text.strip()
    if len(text) > max_len:
        text = text[:max_len]
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


def safe_join_lines(lines: Iterable[str]) -> str:
    return "\n".join([l.rstrip() for l in lines if l.strip()])

