import pandas as pd

from argos.evaluation.m2_gate import M2GateDecision, render_m2_gate_markdown


def test_m2_gate_render_closed() -> None:
    report = pd.DataFrame.from_records(
        [
            {
                "check_id": "core",
                "category": "validation",
                "blocking": True,
                "passed": True,
                "observed": "ok",
                "requirement": "must pass",
            }
        ]
    )
    decision = M2GateDecision("CLOSED", 1, 1, ())

    rendered = render_m2_gate_markdown(report, decision)

    assert "M2 ✅ CLOSED" in rendered
    assert "1/1" in rendered
