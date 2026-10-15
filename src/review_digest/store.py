import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY, date TEXT NOT NULL, sku TEXT, rating INTEGER NOT NULL,
  text TEXT NOT NULL, ingested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
  review_id TEXT PRIMARY KEY REFERENCES reviews(id),
  themes TEXT NOT NULL, other_label TEXT, confidence REAL, flags TEXT NOT NULL,
  model TEXT, prompt_version TEXT, analyzed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, week_start TEXT NOT NULL, text TEXT NOT NULL,
  created_at TEXT NOT NULL, sent_at TEXT, telegram_message_id INTEGER
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def add_reviews(conn, reviews: list[dict]) -> int:
    """Insert new reviews; ids already stored are ignored, so re-running an import is safe."""
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO reviews (id, date, sku, rating, text, ingested_at) VALUES (?,?,?,?,?,?)",
        [(r["id"], r["date"], r["sku"], r["rating"], r["text"], now()) for r in reviews])
    conn.commit()
    return conn.total_changes - before


def pending(conn, force: bool = False) -> list[dict]:
    sql = "SELECT * FROM reviews" if force else \
        "SELECT * FROM reviews WHERE id NOT IN (SELECT review_id FROM analyses)"
    return [dict(r) for r in conn.execute(sql + " ORDER BY date, id")]


def save_analysis(conn, review_id: str, result: dict, flags: list[str], model: str, version: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO analyses (review_id, themes, other_label, confidence, flags, model,"
        " prompt_version, analyzed_at) VALUES (?,?,?,?,?,?,?,?)",
        (review_id, json.dumps(result["themes"], ensure_ascii=False), result.get("other_label"),
         result["confidence"], json.dumps(flags), model, version, now()))
    conn.commit()


def analyzed_reviews(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT r.*, a.themes, a.other_label, a.confidence, a.flags FROM reviews r"
        " JOIN analyses a ON a.review_id = r.id ORDER BY r.date, r.id").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["themes"] = json.loads(d["themes"])
        d["flags"] = json.loads(d["flags"])
        out.append(d)
    return out


def count_unanalyzed(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM reviews WHERE id NOT IN (SELECT review_id FROM analyses)").fetchone()[0]
