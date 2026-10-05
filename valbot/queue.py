"""Durable webhook inbox; payloads encrypted, deduplicated using LINE webhookEventId."""
import json
import sqlite3
import time

from .storage import Vault


class Inbox:
    def __init__(self, vault: Vault):
        self.vault = vault
        self.path = vault.directory / "inbox.sqlite3"
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, payload BLOB NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                created REAL NOT NULL, lease REAL NOT NULL DEFAULT 0)""")

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def enqueue(self, event):
        payload = self.vault.cipher.encrypt(json.dumps(event).encode())
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO events (id,payload,created) VALUES (?,?,?)",
                       (event["webhookEventId"], payload, time.time()))
            db.execute("DELETE FROM events WHERE created < ?", (time.time() - 7 * 86400,))

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id,payload FROM events WHERE status='pending' OR "
                             "(status='processing' AND lease < ?) ORDER BY created LIMIT 1",
                             (time.time(),)).fetchone()
            if not row:
                return None
            db.execute("UPDATE events SET status='processing',lease=? WHERE id=?", (time.time() + 180, row[0]))
        return row[0], json.loads(self.vault.cipher.decrypt(row[1]))

    def finish(self, event_id):
        with self.connect() as db:
            db.execute("UPDATE events SET status='done' WHERE id=?", (event_id,))
