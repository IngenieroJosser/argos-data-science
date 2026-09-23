import json
from pathlib import Path

from argos.production.audit import append_audit_event, verify_audit_chain


def test_hash_chain_detects_tampering(tmp_path: Path) -> None:
    log = "audit/events.jsonl"
    append_audit_event(tmp_path, log_path=log, event_type="one", actor="test", payload={"x": 1})
    append_audit_event(tmp_path, log_path=log, event_type="two", actor="test", payload={"x": 2})
    ok, count, error = verify_audit_chain(tmp_path, log_path=log)
    assert ok and count == 2 and error is None

    path = tmp_path / log
    lines = path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    event["payload"]["x"] = 999
    lines[0] = json.dumps(event, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, _, error = verify_audit_chain(tmp_path, log_path=log)
    assert not ok
    assert error is not None
