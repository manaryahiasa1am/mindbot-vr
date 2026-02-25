import sqlite3
from pathlib import Path
from typing import Any

from flask import g


def _base_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _db_path() -> Path:
    database_dir = _base_dir() / "database"
    database_dir.mkdir(parents=True, exist_ok=True)
    return database_dir / "mindbot_vr.sqlite3"


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(_db_path(), detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        g.db = conn
    return g.db


def close_db(_: Any = None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db() -> None:
    conn = sqlite3.connect(_db_path(), detect_types=sqlite3.PARSE_DECLTYPES)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
              content TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS vitals (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              pulse_bpm REAL NOT NULL,
              temperature_c REAL NOT NULL,
              oxygen_percent REAL NOT NULL,
              air_quality_ppm REAL NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS symptom_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              raw_message TEXT NOT NULL,
              matched_symptoms_json TEXT NOT NULL,
              risk_score INTEGER NOT NULL,
              risk_level TEXT NOT NULL,
              recommendation TEXT NOT NULL,
              hospital_needed INTEGER NOT NULL,
              emergency_mode INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sos_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              trigger TEXT NOT NULL CHECK(trigger IN ('manual','auto')),
              lat REAL NOT NULL,
              lng REAL NOT NULL,
              hospital_id TEXT NOT NULL,
              hospital_name TEXT NOT NULL,
              hospital_phone TEXT NOT NULL,
              distance_km REAL NOT NULL,
              eta_minutes INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

