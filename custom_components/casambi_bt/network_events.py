"""Own observation capture, safe projections, status and archive notifications."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
import json
import logging
from pathlib import Path
import sqlite3
import time
from typing import Any
from uuid import uuid4

from CasambiBt import __version__ as DECODER_VERSION, input_observation

from .event_store import EventStore

_LOGGER = logging.getLogger(__name__)
DATA_NETWORK_EVENTS = "casambi_bt_network_events"
QUEUE_CAPACITY = 8192
EVENT_FIELDS = frozenset(
    {
        "time",
        "timestamp",
        "unit",
        "name",
        "type",
        "value",
        "numeric_value",
        "raw_value",
        "control",
        "control_index",
        "offset",
        "length",
        "source",
        "sensor_tag",
        "source_stream",
        "packet_type",
        "opcode",
        "opcode_name",
        "invocation_flags",
        "respond",
        "unique",
        "session",
        "flag_0400",
        "lifetime",
        "origin",
        "origin_unit_id",
        "origin_counter",
        "origin_handle",
        "target",
        "target_type",
        "age",
        "payload_length",
        "frame_offset",
        "packet_sequence",
        "arrival_sequence",
        "button_event_index",
        "pressed",
        "param_p",
        "param_s",
        "input_index",
        "input_code",
        "input_b1",
        "input_channel",
        "input_value16",
        "interpreted_payload_hex",
        "unparsed_payload_length",
    }
)
DIAGNOSTIC_FIELDS = {
    "evo_receive": {
        "arrival_sequence",
        "packet_sequence",
        "wire_length",
        "verified",
        "packet_type",
    },
    "switch_decode": {
        "arrival_sequence",
        "packet_sequence",
        "frames",
        "button_frames",
        "input_frames",
        "ignored_frames",
        "legacy_emitted",
        "suppressed_copies",
        "suppressed_paired",
    },
    "callback_error": {"arrival_sequence", "exception_type"},
    "connection": {"address", "gateway_unit", "device_protocol", "protocol_mode"},
}


def now_ms() -> int:
    """Return HA receive time, independently of a protocol timestamp."""
    return time.time_ns() // 1_000_000


def project_event(event: dict) -> dict:
    """Publish known decoded fields; unparsed buffers never enter this surface."""
    if not isinstance(event["time"], int):
        raise TypeError("Event receive time must be an integer")
    for key in ("name", "type", "source", "value"):
        if not isinstance(event[key], str):
            raise TypeError(f"Event {key} must be a string")
    projected = {key: value for key, value in event.items() if key in EVENT_FIELDS}
    projected.update(input_observation(projected))
    projected["decoder_version"] = DECODER_VERSION
    # Validate the explicit persistence contract at the capture boundary.
    return json.loads(json.dumps(projected, allow_nan=False))


def project_diagnostic(diagnostic: dict) -> dict:
    """Accept only the client's explicit receive-metadata contract."""
    stage = diagnostic["stage"]
    fields = DIAGNOSTIC_FIELDS[stage]
    projected = {
        "stage": stage,
        **{key: diagnostic[key] for key in fields},
    }
    return json.loads(json.dumps(projected, allow_nan=False))


class NetworkEventsManager:
    """Share one durable collector across entries, reloads and browser viewers."""

    def __init__(self, path: Path) -> None:
        """Allocate a bounded ingress queue without touching network credentials."""
        self.store = EventStore(path)
        self.networks: dict[str, dict[str, Any]] = {}
        self.subscribers: set[asyncio.Event] = set()
        self._queue: asyncio.Queue[dict | None] = asyncio.Queue(QUEUE_CAPACITY)
        self._worker: asyncio.Task | None = None
        self._closing = False
        self._failure: str | None = None
        self._dropped: Counter[str] = Counter()
        self._gap_started: int | None = None
        self.streams: dict[tuple[int, int], Any] = {}
        self.archive_ready = False

    async def start(self) -> None:
        """Restore public archive metadata and start the supervised writer."""
        try:
            await self.store.open(now_ms())
            self.networks = {
                row["entry_id"]: {
                    **row,
                    "state": "archived",
                    "connection_id": None,
                    "receive": {},
                    "has_gaps": bool(await self.store.gaps(row["entry_id"])),
                }
                for row in await self.store.networks()
            }
        except (OSError, sqlite3.Error, ValueError) as error:
            # The archive is optional to lighting control, but never an empty-history fallback.
            self._failure = f"archive_open_{type(error).__name__}"
            _LOGGER.error("Casambi event archive unavailable (%s)", self._failure)
            return
        self.archive_ready = True
        self._worker = asyncio.create_task(self._writer(), name="Casambi event archive")
        self._worker.add_done_callback(self._writer_finished)

    def _writer_finished(self, task: asyncio.Task) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            self._failure = type(error).__name__
            _LOGGER.error(
                "Casambi event archive failed at writer boundary (%s)", self._failure
            )
            self._wake()

    def _wake(self) -> None:
        for wake in tuple(self.subscribers):
            wake.set()

    def listen(self, wake: asyncio.Event) -> Callable[[], None]:
        """Register before taking a watermark to avoid a replay/live race."""
        self.subscribers.add(wake)
        return lambda: self.subscribers.discard(wake)

    async def attach(self, entry_id: str, name: str, address: str) -> None:
        """Attach public network identity before the client's first observation."""
        if self.archive_ready:
            await self.store.register_network(entry_id, name, address)
        previous = self.networks.get(entry_id)
        self.networks[entry_id] = {
            "entry_id": entry_id,
            "name": name,
            "address": address,
            "state": "loading",
            "saved": previous["saved"]
            if previous
            else 0
            if self.archive_ready
            else None,
            "last_saved": previous["last_saved"] if previous else None,
            "connection_id": None,
            "receive": {},
            "has_gaps": previous["has_gaps"] if previous else not self.archive_ready,
        }
        self._wake()

    def status(self, entry_id: str) -> dict:
        """Expose transport, capture and storage states as separate facts."""
        network = self.networks[entry_id]
        return {
            **network,
            "receive": dict(network["receive"]),
            "storage": "failed" if self._failure else "ready",
            "storage_error": self._failure,
            "pending": self._queue.qsize(),
            "capture_dropped": self._dropped[entry_id],
        }

    def _submit(
        self, entry_id: str, kind: str, data: dict, *, time_ms: int | None = None
    ) -> None:
        if self._closing:
            return
        if not self.archive_ready:
            self._dropped[entry_id] += 1
            self.networks[entry_id]["has_gaps"] = True
            self._wake()
            return
        record = {
            "kind": kind,
            "entry_id": entry_id,
            "connection_id": self.networks[entry_id]["connection_id"],
            "time": now_ms() if time_ms is None else time_ms,
            "data": data,
        }
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            self.networks[entry_id]["has_gaps"] = True
            self._failure = "ingress_overflow"
            self._gap_started = self._gap_started or now_ms()
            self._dropped[entry_id] += 1
            self._wake()

    def event(self, entry_id: str, event: dict) -> None:
        """Capture observations without interrupting the BLE control owner."""
        try:
            projected = project_event(event)
        except (KeyError, TypeError, ValueError) as error:
            self._capture_error(entry_id, type(error).__name__)
            return
        self._submit(entry_id, "event", projected, time_ms=projected["time"])

    def _capture_error(self, entry_id: str, reason: str) -> None:
        self._failure = f"projection_{reason}"
        self.networks[entry_id]["has_gaps"] = True
        self._gap_started = self._gap_started or now_ms()
        self._dropped[entry_id] += 1
        self._submit(
            entry_id, "diagnostic", {"stage": "capture_error", "exception_type": reason}
        )
        self._wake()

    def start_session(self, entry_id: str, target: str) -> None:
        """Give each GATT connection attempt an identity independent of event IDs."""
        network = self.networks[entry_id]
        if network["connection_id"] is not None:
            self._submit(entry_id, "session_end", {})
        network.update(
            connection_id=uuid4().hex,
            gateway_address=target,
            connection=None,
            state="connecting",
            receive={},
        )
        self._submit(entry_id, "session_start", {"gateway_address": target})
        self._wake()

    def set_state(self, entry_id: str, state: str) -> None:
        """Report an actual lifecycle transition without guessing connectivity."""
        network = self.networks[entry_id]
        if state in ("disconnected", "unloaded", "failed") and network["connection_id"]:
            self._submit(entry_id, "session_end", {})
        network["state"] = state
        self._wake()

    def diagnostic(self, entry_id: str, diagnostic: dict) -> None:
        """Keep receive counters separate from the observation count."""
        try:
            projected = project_diagnostic(diagnostic)
        except (KeyError, TypeError, ValueError) as error:
            self._capture_error(entry_id, type(error).__name__)
            return
        self._submit(entry_id, "diagnostic", projected)
        receive = self.networks[entry_id]["receive"]
        stage = projected["stage"]
        if stage == "evo_receive":
            receive["packets"] = receive.get("packets", 0) + 1
            receive["invalid_signatures"] = receive.get("invalid_signatures", 0) + int(
                not projected["verified"]
            )
            receive["type7_packets"] = receive.get("type7_packets", 0) + int(
                projected["packet_type"] == 7
            )
            receive["last_sequence"] = projected["packet_sequence"]
        elif stage == "switch_decode":
            for output, source in (
                ("legacy_emitted", "legacy_emitted"),
                ("legacy_copies", "suppressed_copies"),
                ("legacy_paired", "suppressed_paired"),
            ):
                receive[output] = receive.get(output, 0) + projected[source]
        elif stage == "callback_error":
            receive["callback_errors"] = receive.get("callback_errors", 0) + 1
        elif stage == "connection":
            self.networks[entry_id]["connection"] = projected
        self._wake()

    async def _writer(self) -> None:
        while (first := await self._queue.get()) is not None:
            batch = [first]
            await asyncio.sleep(0.025)
            while len(batch) < 256 and not self._queue.empty():
                item = self._queue.get_nowait()
                assert item is not None
                batch.append(item)
            dropped = dict(self._dropped)
            gaps = [
                {
                    "kind": "gap",
                    "entry_id": entry_id,
                    "time": now_ms(),
                    "data": {
                        "started": self._gap_started,
                        "reason": self._failure,
                        "count": count,
                    },
                }
                for entry_id, count in dropped.items()
                if count
            ]
            for attempt in range(3):
                try:
                    saved = await self.store.append([*gaps, *batch])
                    break
                except (sqlite3.OperationalError, OSError):
                    if attempt == 2:
                        raise
                    self._failure = "archive_write_retry"
                    self._wake()
                    await asyncio.sleep(attempt + 1)
            for entry_id, count in dropped.items():
                self._dropped[entry_id] -= count
            for event in saved:
                network = self.networks[event["entry_id"]]
                network["saved"] += 1
                network["last_saved"] = event["time"]
            for _ in batch:
                self._queue.task_done()
            if not any(self._dropped.values()):
                self._failure = None
                self._gap_started = None
            self._wake()
        self._queue.task_done()

    async def flush(self) -> None:
        """Wait for accepted observations, propagating a failed writer."""
        assert self._worker is not None
        joined = asyncio.create_task(self._queue.join())
        try:
            done, _ = await asyncio.wait(
                (joined, self._worker), return_when=asyncio.FIRST_COMPLETED
            )
            if self._worker in done:
                await self._worker
            await joined
        finally:
            joined.cancel()

    async def close(self) -> None:
        """Stop subscribers and drain capture within a finite shutdown interval."""
        self._closing = True
        for stream in tuple(self.streams.values()):
            stream.close()
        clean = False
        try:
            if self._worker is not None:
                async with asyncio.timeout(10):
                    await self.flush()
                    await self._queue.put(None)
                    await self._worker
                    clean = self._failure is None
        except Exception as error:  # noqa: BLE001
            # Shutdown still closes the archive after a supervised writer failure.
            _LOGGER.error(
                "Casambi event archive shutdown incomplete (%s)", type(error).__name__
            )
        finally:
            if self._worker is not None:
                self._worker.cancel()
                await asyncio.gather(self._worker, return_exceptions=True)
            await self.store.close(now_ms(), clean=clean)
