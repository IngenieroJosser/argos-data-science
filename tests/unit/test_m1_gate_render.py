import pandas as pd

from argos.evaluation.m1_gate import GateDecision, render_m1_gate_markdown


def test_nonblocking_failed_check_is_rendered_as_deferred() -> None:
    report = pd.DataFrame.from_records(
        [
            {
                "check_id": "core",
                "category": "grain",
                "description": "core check",
                "blocking": True,
                "passed": True,
                "observed": "ok",
                "requirement": "must pass",
            },
            {
                "check_id": "relationship_bidders_suppliers",
                "category": "relationships",
                "description": "direct relationship",
                "blocking": False,
                "passed": False,
                "observed": "coverage=0",
                "requirement": "coverage >= 90%",
            },
        ]
    )
    decision = GateDecision("CLOSED", 1, 1, ())

    rendered = render_m1_gate_markdown(report, decision)

    assert "M1 ✅ CLOSED" in rendered
    assert "DEFERRED" in rendered
    assert "non-blocking" in rendered
