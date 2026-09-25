# M8 Code Readiness — 2026-09-23

The M8 implementation is present for semantic NLP, temporal graph intelligence, contextual anomaly detection, temporal ablation and survival analysis.

The review ZIP intentionally omits the large `data/bronze`, `data/silver` and `data/gold` workspace; therefore empirical M8 artifacts/gate evidence must be regenerated in the real workspace and are not fabricated here.

Code readiness includes:

- `configs/advanced.toml` schema `m8-advanced-intelligence-v2` + typed loader;
- SentenceTransformer/FAISS semantic pipeline with matured-label PIT guard;
- temporal supplier/entity + co-bid graph features;
- TRAIN-only IsolationForest contextual anomaly scoring;
- development matrix and M7 hash-integrity PIT audit;
- same-seed temporal feature-family ablation;
- survival outcome construction with 180-day administrative censoring;
- Kaplan–Meier, penalized Cox PH, C-index, Brier/calibration and PH diagnostics;
- formal M8 gate requiring Survival evidence;
- notebooks `70`–`77`;
- one-command orchestration via `pipelines/run_advanced_m8.py`.

Formal `M8 ✅ CLOSED` must be produced by executing this exact code against the real Silver/Gold workspace.
