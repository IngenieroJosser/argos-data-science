from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
from typing import Any

from argos.production.common import resolve

GENESIS_HASH = "0" * 64


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def append_audit_event(
    root: Path,
    *,
    log_path: str,
    event_type: str,
    actor: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Append a hash-chained audit event using an OS file lock.

    The log is append-only by convention.  Each event includes the previous
    event hash, making accidental or silent mutation detectable by
    :func:`verify_audit_chain`.
    """
    path = resolve(root, log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        lines = [line.strip() for line in handle if line.strip()]
        previous_hash = GENESIS_HASH
        if lines:
            previous_hash = str(json.loads(lines[-1])["event_hash"])
        base = {
            "event_type": str(event_type),
            "actor": str(actor),
            "occurred_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "previous_hash": previous_hash,
            "payload": payload,
        }
        event_hash = hashlib.sha256(previous_hash.encode("ascii") + b"|" + _canonical(base)).hexdigest()
        event = {**base, "event_hash": event_hash}
        handle.seek(0, 2)
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        handle.flush()
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return event


def verify_audit_chain(root: Path, *, log_path: str) -> tuple[bool, int, str | None]:
    path = resolve(root, log_path)
    if not path.exists():
        return True, 0, None
    previous_hash = GENESIS_HASH
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            count += 1
            event = json.loads(line)
            observed_hash = str(event.pop("event_hash"))
            if event.get("previous_hash") != previous_hash:
                return False, count, f"previous_hash mismatch at line {line_no}"
            expected = hashlib.sha256(previous_hash.encode("ascii") + b"|" + _canonical(event)).hexdigest()
            if observed_hash != expected:
                return False, count, f"event_hash mismatch at line {line_no}"
            previous_hash = observed_hash
    return True, count, None
