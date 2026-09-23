# ARGOS — M7 Handoff

M6 is closed with deployment state `OPERATIONALLY_READY_PROMOTION_BLOCKED`. M7 begins from that exact frozen state and does not weaken its governance.

## Frozen V1 contract

- target: `y_addition_180d`
- event: `ADICION EN EL VALOR`
- t0: `fecha_de_firma`
- horizon: `(t0, t0 + 180d]`
- ranking: calibrated score DESC, raw score DESC, contract_id ASC
- review fraction: 1%
- model: frozen ARGOS V1 HistGradientBoosting + isotonic calibration
- execution: batch-first
- decision mode: human review required

## M7 boundary

M7 evaluates the frozen V1 prospectively. It may conclude that V1 should remain in shadow, be recalibrated, be replaced by V2, or enter a controlled pilot. M7 itself never tunes V1 using the same future cohorts used to judge it.

The protocol manifest created by notebook 60 is immutable: rerunning notebook 60 may verify and preserve it, but may not silently replace it with new hashes after future evidence becomes available.
