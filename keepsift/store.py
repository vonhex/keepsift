"""SQLite record of what has been processed and what was done (audit log)."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed (
    gm_msgid     TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL,
    sender       TEXT,
    subject      TEXT,
    category     TEXT,
    priority     TEXT,
    summary      TEXT,
    reply_action TEXT,
    actions      TEXT,
    detail       TEXT
);
CREATE INDEX IF NOT EXISTS idx_processed_at ON processed(processed_at);
CREATE TABLE IF NOT EXISTS cleanup (
    gm_msgid TEXT PRIMARY KEY,
    at       TEXT NOT NULL,
    sender   TEXT,
    subject  TEXT,
    result   TEXT,
    reasons  TEXT
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def seen(self, ids):
        ids = [i for i in ids if i]
        found = set()
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = f"SELECT gm_msgid FROM processed WHERE gm_msgid IN ({','.join('?' * len(chunk))})"
            found.update(r[0] for r in self.db.execute(q, chunk))
        return found

    def record(self, em, cls, reply_action, actions, detail):
        self.db.execute(
            "INSERT OR REPLACE INTO processed VALUES (?,?,?,?,?,?,?,?,?,?)",
            (em.gm_msgid, _now(), em.from_addr, em.subject, cls.get("category"), cls.get("priority"),
             cls.get("summary"), reply_action, ",".join(actions), json.dumps(detail, ensure_ascii=False)),
        )
        self.db.commit()

    def sends_since(self, hours):
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        q = "SELECT COUNT(*) FROM processed WHERE reply_action = 'sent' AND processed_at >= ?"
        return self.db.execute(q, (since,)).fetchone()[0]

    def cleanup_seen(self, ids, exclude_kept=False):
        """IDs a cleanup already handled. exclude_kept: leave out ones that were kept (to re-check them)."""
        ids = [i for i in ids if i]
        found = set()
        extra = " AND result != 'kept'" if exclude_kept else ""
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = f"SELECT gm_msgid FROM cleanup WHERE gm_msgid IN ({','.join('?' * len(chunk))}){extra}"
            found.update(r[0] for r in self.db.execute(q, chunk))
        return found

    def record_cleanup(self, gm_msgid, sender, subject, result, reasons):
        self.db.execute("INSERT OR REPLACE INTO cleanup VALUES (?,?,?,?,?,?)",
                        (gm_msgid, _now(), sender, subject, result, "; ".join(reasons)))
        self.db.commit()

    def cleanup_kept(self, n=500):
        q = "SELECT * FROM cleanup WHERE result = 'kept' ORDER BY at DESC LIMIT ?"
        return [dict(r) for r in self.db.execute(q, (n,))]

    def stats(self):
        """Totals for the Home dashboard."""
        one = lambda q: self.db.execute(q).fetchone()[0]
        return {
            "sorted": one("SELECT COUNT(*) FROM processed"),
            "drafted": one("SELECT COUNT(*) FROM processed WHERE reply_action IN ('drafted', 'sent')"),
            "removed": one("SELECT COUNT(*) FROM cleanup WHERE result IN ('trashed', 'marked')"),
            "kept": one("SELECT COUNT(*) FROM cleanup WHERE result = 'kept'"),
        }

    def recent(self, n=20):
        q = "SELECT * FROM processed ORDER BY processed_at DESC LIMIT ?"
        return [dict(r) for r in self.db.execute(q, (n,))]
