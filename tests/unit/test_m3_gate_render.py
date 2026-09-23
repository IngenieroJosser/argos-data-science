import pandas as pd

from argos.evaluation.m3_gate import M3GateDecision, render_m3_gate_markdown


def test_m3_gate_render_closed() -> None:
    report = pd.DataFrame(
        [
            {
                "check_id": "example",
                "category": "test",
                "blocking": True,
                "passed": True,
                "observed": "{}",
                "requirement": "must pass",
            }
        ]
    )
    decision = M3GateDecision("CLOSED", 1, 1, ())
    rendered = render_m3_gate_markdown(report, decision)
    assert "M3 ✅ CLOSED" in rendered
    assert "1/1" in rendered
    assert "argos_v1.parquet" in rendered
