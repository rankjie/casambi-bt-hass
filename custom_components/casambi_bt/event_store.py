"""Durable, paginated observation history, independent of the credential cache."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from functools import partial
import json
import os
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = 1
PAGE_SIZE = 250


class EventStore:
    """Serialize writes in one worker and use short, independent read snapshots."""

    def __init__(self, path: Path) -> None:
        """Bind a dedicated archive path; no credential source is accessed."""
        self.path = path
        self.store_id = ""
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="casambi-events"
        )
        self._db: sqlite3.Connection | None = None
        self._run_id = uuid4().hex

    async def _write(self, function, *args):
        return await asyncio.get_running_loop().run_in_executor(
            self._executor, function, *args
        )

    async def open(self, now_ms: int) -> None:
        """Open the archive and record interrupted capture runs explicitly."""
        self.store_id = await self._write(self._open, now_ms)

    def _open(self, now_ms: int) -> str:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.path.exists():
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        db = self._db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            db.close()
            self._db = None
            raise ValueError(f"Unsupported event archive version {version}")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS networks (
                entry_id TEXT PRIMARY KEY, name TEXT NOT NULL, address TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id TEXT NOT NULL, connection_id TEXT, time INTEGER NOT NULL,
                unit INTEGER, name TEXT NOT NULL, type TEXT NOT NULL,
                source TEXT NOT NULL, source_stream TEXT,
                search TEXT NOT NULL, data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS event_entry ON events(entry_id, sequence);
            CREATE INDEX IF NOT EXISTS event_time ON events(entry_id, time);
            CREATE INDEX IF NOT EXISTS event_unit ON events(entry_id, unit, sequence);
            CREATE INDEX IF NOT EXISTS event_type ON events(entry_id, type, sequence);
            CREATE INDEX IF NOT EXISTS event_source ON events(entry_id, source, sequence);
            CREATE TABLE IF NOT EXISTS sessions (
                connection_id TEXT PRIMARY KEY, entry_id TEXT NOT NULL,
                started INTEGER NOT NULL, ended INTEGER, data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS receive_diagnostics (
                id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id TEXT NOT NULL,
                connection_id TEXT, time INTEGER NOT NULL, stage TEXT NOT NULL, data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, started INTEGER NOT NULL, ended INTEGER
            );
            CREATE TABLE IF NOT EXISTS gaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id TEXT,
                started INTEGER NOT NULL, ended INTEGER, reason TEXT NOT NULL,
                count INTEGER
            );
        """)
        with db:
            db.execute(
                "INSERT OR IGNORE INTO meta VALUES ('store_id', ?)", (uuid4().hex,)
            )
            for run in db.execute(
                "SELECT started FROM runs WHERE ended IS NULL"
            ).fetchall():
                db.execute(
                    "INSERT INTO gaps(entry_id,started,ended,reason) VALUES(NULL,?,?,?)",
                    (run[0], now_ms, "unclean_shutdown"),
                )
            db.execute("UPDATE runs SET ended=? WHERE ended IS NULL", (now_ms,))
            db.execute(
                "INSERT INTO runs(id,started) VALUES(?,?)", (self._run_id, now_ms)
            )
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        return db.execute("SELECT value FROM meta WHERE key='store_id'").fetchone()[0]

    async def register_network(self, entry_id: str, name: str, address: str) -> None:
        """Keep enough public metadata to identify an archived network."""
        await self._write(self._register_network, entry_id, name, address)

    def _register_network(self, entry_id, name, address):
        assert self._db is not None
        with self._db:
            self._db.execute(
                "INSERT INTO networks VALUES(?,?,?) ON CONFLICT(entry_id) DO UPDATE SET name=excluded.name,address=excluded.address",
                (entry_id, name, address),
            )

    async def append(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Commit an accepted batch before returning IDs that can be announced."""
        return await self._write(self._append, records)

    def _append(self, records):
        assert self._db is not None
        saved = []
        with self._db:
            for record in records:
                kind, entry_id = record["kind"], record["entry_id"]
                connection_id, time = record.get("connection_id"), record["time"]
                data = record["data"]
                encoded = json.dumps(
                    data, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                )
                if kind == "event":
                    search = " ".join(
                        str(data.get(key, ""))
                        for key in (
                            "unit",
                            "name",
                            "type",
                            "value",
                            "control",
                            "source_stream",
                            "button",
                            "input_action",
                            "opcode_name",
                        )
                    ).casefold()
                    cursor = self._db.execute(
                        "INSERT INTO events(entry_id,connection_id,time,unit,name,type,source,source_stream,search,data) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            entry_id,
                            connection_id,
                            time,
                            data.get("unit"),
                            data["name"],
                            data["type"],
                            data["source"],
                            data.get("source_stream"),
                            search,
                            encoded,
                        ),
                    )
                    saved.append(
                        self._event(cursor.lastrowid, entry_id, connection_id, data)
                    )
                elif kind == "diagnostic":
                    self._db.execute(
                        "INSERT INTO receive_diagnostics(entry_id,connection_id,time,stage,data) VALUES(?,?,?,?,?)",
                        (entry_id, connection_id, time, data["stage"], encoded),
                    )
                elif kind == "session_start":
                    self._db.execute(
                        "INSERT INTO sessions VALUES(?,?,?,NULL,?)",
                        (connection_id, entry_id, time, encoded),
                    )
                elif kind == "session_end":
                    self._db.execute(
                        "UPDATE sessions SET ended=? WHERE connection_id=?",
                        (time, connection_id),
                    )
                elif kind == "gap":
                    self._db.execute(
                        "INSERT INTO gaps(entry_id,started,ended,reason,count) VALUES(?,?,?,?,?)",
                        (
                            entry_id,
                            data["started"],
                            time,
                            data["reason"],
                            data.get("count"),
                        ),
                    )
                else:
                    raise ValueError(f"Unsupported archive record kind {kind}")
        return saved

    def _event(self, sequence, entry_id, connection_id, data):
        return {
            **data,
            "id": f"{self.store_id}:{sequence}",
            "sequence": sequence,
            "entry_id": entry_id,
            "connection_id": connection_id,
        }

    async def _read(self, function, *args):
        return await asyncio.get_running_loop().run_in_executor(None, function, *args)

    def _reader(self):
        db = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    async def networks(self) -> list[dict[str, Any]]:
        """Return public network metadata and the complete saved count."""
        return await self._read(self._networks)

    def _networks(self):
        with closing(self._reader()) as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT n.*,count(e.sequence) AS saved,max(e.time) AS last_saved FROM networks n LEFT JOIN events e USING(entry_id) GROUP BY n.entry_id"
                )
            ]

    async def watermark(self) -> int:
        """Return the latest committed observation sequence."""
        return await self._read(self._watermark)

    def _watermark(self):
        with closing(self._reader()) as db:
            return db.execute(
                "SELECT coalesce(max(sequence),0) FROM events"
            ).fetchone()[0]

    @staticmethod
    def _where(entry_id, filters, upper):
        conditions, values = ["entry_id=?", "sequence<=?"], [entry_id, upper]
        for key, column in (
            ("unit", "unit"),
            ("event_type", "type"),
            ("source", "source"),
            ("source_stream", "source_stream"),
        ):
            if key in filters and filters[key] != "":
                conditions.append(f"{column}=?")
                values.append(filters[key])
        for key, operator in (("start_ms", ">="), ("end_ms", "<=")):
            if key in filters:
                conditions.append(f"time{operator}?")
                values.append(filters[key])
        if query := filters.get("query", "").strip():
            conditions.append("instr(search,?)>0")
            values.append(query.casefold())
        return conditions, values

    async def query(
        self,
        entry_id: str,
        filters: dict,
        *,
        upper: int,
        after: int | None = None,
        before: int | None = None,
        limit: int = PAGE_SIZE,
    ) -> dict:
        """Read a keyset page from the whole archive, not a live-memory window."""
        if after is not None and before is not None:
            raise ValueError("Cannot use both replay and history cursors")
        return await self._read(
            partial(
                self._query,
                entry_id,
                filters,
                upper=upper,
                after=after,
                before=before,
                limit=limit,
            )
        )

    def _query(self, entry_id, filters, *, upper, after, before, limit):
        conditions, values = self._where(entry_id, filters, upper)
        if after is not None:
            conditions.append("sequence>?")
            values.append(after)
        if before is not None:
            conditions.append("sequence<?")
            values.append(before)
        order = "ASC" if after is not None else "DESC"
        with closing(self._reader()) as db:
            rows = db.execute(
                # SQL fragments are internal constants; every user value is bound.
                f"SELECT * FROM events WHERE {' AND '.join(conditions)} ORDER BY sequence {order} LIMIT ?",  # noqa: S608
                (*values, limit + 1),
            ).fetchall()
        more = len(rows) > limit
        events = [
            self._event(
                row["sequence"], entry_id, row["connection_id"], json.loads(row["data"])
            )
            for row in rows[:limit]
        ]
        scanned = events[-1]["sequence"] if more and after is not None else upper
        return {
            "events": events,
            "has_more": more,
            "upper_sequence": upper,
            "before_sequence": events[-1]["sequence"] if events and more else None,
            "scanned_to_sequence": scanned,
        }

    async def get(self, entry_id: str, sequence: int) -> dict | None:
        """Fetch an inspected record independently of the resident list page."""
        return await self._read(self._get, entry_id, sequence)

    def _get(self, entry_id, sequence):
        with closing(self._reader()) as db:
            row = db.execute(
                "SELECT * FROM events WHERE entry_id=? AND sequence=?",
                (entry_id, sequence),
            ).fetchone()
        return (
            self._event(
                sequence, entry_id, row["connection_id"], json.loads(row["data"])
            )
            if row
            else None
        )

    async def facets(self, entry_id: str) -> dict:
        """Discover device/type filters across all saved observations."""
        return await self._read(self._facets, entry_id)

    def _facets(self, entry_id):
        with closing(self._reader()) as db:
            units = [
                dict(row)
                for row in db.execute(
                    "SELECT unit,name FROM events WHERE sequence IN (SELECT max(sequence) FROM events WHERE entry_id=? AND unit IS NOT NULL GROUP BY unit) ORDER BY name",
                    (entry_id,),
                )
            ]
            types = [
                row[0]
                for row in db.execute(
                    "SELECT DISTINCT type FROM events WHERE entry_id=? ORDER BY type",
                    (entry_id,),
                )
            ]
        return {"units": units, "types": types}

    async def gaps(self, entry_id: str) -> list[dict]:
        """Report explicit capture gaps, including interrupted process intervals."""
        return await self._read(self._gaps, entry_id)

    def _gaps(self, entry_id):
        with closing(self._reader()) as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT started,ended,reason,count FROM gaps WHERE entry_id=? OR entry_id IS NULL ORDER BY id",
                    (entry_id,),
                )
            ]

    async def close(self, now_ms: int, *, clean: bool = True) -> None:
        """Close the worker, retaining an open run marker after capture failure."""
        try:
            await self._write(self._close, now_ms, clean)
        finally:
            self._executor.shutdown(wait=False)

    def _close(self, now_ms, clean):
        if self._db is None:
            return
        try:
            if clean:
                with self._db:
                    self._db.execute(
                        "UPDATE runs SET ended=? WHERE id=?", (now_ms, self._run_id)
                    )
        finally:
            self._db.close()
            self._db = None
