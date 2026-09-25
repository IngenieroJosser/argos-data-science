import numpy as np
import pandas as pd

from argos.survival.analysis import (
    CoxPHBundle,
    SurvivalEncoder,
    fit_cox_ph,
    harrell_c_index,
    kaplan_meier_table,
)


def test_kaplan_meier_handles_events_and_administrative_censoring():
    table = kaplan_meier_table([30, 90, 180, 180], [1, 1, 0, 0])
    assert table["time_days"].tolist() == [30, 90, 180]
    assert table.loc[table["time_days"] == 180, "censored"].item() == 2
    assert np.all(np.diff(table["survival_probability"].to_numpy()) <= 1e-12)
    assert table["survival_probability"].between(0.0, 1.0).all()


def test_harrell_c_index_is_one_for_perfect_earlier_event_ranking():
    value = harrell_c_index(
        durations=[10, 20, 30, 180],
        events=[1, 1, 1, 0],
        risk_scores=[4.0, 3.0, 2.0, 1.0],
    )
    assert value == 1.0


def test_penalized_cox_produces_monotone_survival_probabilities():
    rng = np.random.default_rng(7)
    rows = 500
    frame = pd.DataFrame(
        {
            "category": np.where(rng.random(rows) > 0.5, "A", "B"),
            "x1": rng.normal(size=rows),
            "x2": rng.normal(size=rows),
        }
    )
    encoder = SurvivalEncoder.fit(
        frame,
        categorical_features=("category",),
        numeric_features=("x1", "x2"),
        missing_category="__MISSING__",
    )
    matrix = encoder.transform(frame)
    latent = 0.9 * matrix[:, 1] - 0.4 * matrix[:, 2]
    raw_time = (-np.log(rng.uniform(size=rows)) / np.exp(latent) * 70).astype(int)
    duration = np.minimum(raw_time, 180)
    event = (raw_time <= 180).astype(np.int8)
    coefficients, times, hazard, success, message = fit_cox_ph(
        matrix,
        duration,
        event,
        horizon_days=180,
        l2_penalty=0.1,
        max_iter=100,
        tolerance=1e-7,
    )
    assert success, message
    bundle = CoxPHBundle(
        encoder=encoder,
        coefficients=coefficients,
        baseline_times=times,
        baseline_cumulative_hazard=hazard,
        horizon_days=180,
        l2_penalty=0.1,
        optimizer_success=success,
        optimizer_message=message,
    )
    survival = bundle.predict_survival(frame.head(50), [30, 90, 180])
    assert survival.shape == (50, 3)
    assert np.isfinite(survival).all()
    assert ((survival >= 0.0) & (survival <= 1.0)).all()
    assert np.all(np.diff(survival, axis=1) <= 1e-12)
