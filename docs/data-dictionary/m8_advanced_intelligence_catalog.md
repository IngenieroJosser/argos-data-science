# M8 Advanced Intelligence & Survival — Data Catalog

Schema: `m8-advanced-intelligence-v2`.

## `m8_semantic_features.parquet`

**Grain:** 1 row = 1 contract in M8 development population (`train`/`validation`).

| Column | Meaning |
|---|---|
| `semantic_neighbor_count` | prior semantic peers returned by ANN index |
| `semantic_similarity_mean/max/std` | cosine similarity statistics |
| `semantic_novelty_score` | `1 - max_similarity` |
| `semantic_matured_neighbor_count` | peers whose 180d label was observable before current `t0` |
| `semantic_neighbor_addition_rate_matured` | positive rate among matured peers only |
| `semantic_text_chars` | normalized text length |
| `semantic_text_missing` | short/missing text indicator |
| `_pit_semantic_max_peer_t0` | latest peer `t0` admitted |
| `_pit_semantic_max_label_available_at` | latest peer-label availability timestamp used |

## `m8_graph_features.parquet`

**Grain:** 1 row = 1 contract in M8 development population.

Includes temporal supplier/entity degree, weighted degree, pair repetition, concentration shares/HHI, PageRank, connected-component sizes and supplier co-bidding network statistics. `_pit_graph_max_contract_t0` and `_pit_graph_max_cobid_at` are audit metadata and are not model features.

## `m8_anomaly_features.parquet`

**Grain:** 1 row = 1 contract in M8 development population.

| Column | Meaning |
|---|---|
| `anomaly_isolation_raw_score` | negative IsolationForest decision function; higher = more unusual |
| `anomaly_score` | empirical percentile vs TRAIN anomaly-score reference |
| `anomaly_categorical_rarity_mean` | average TRAIN frequency rarity of categorical context |
| `_anomaly_model_fit_split` | audit field; must equal `train` |

`anomaly_score` is an analytical prioritization signal, not evidence of wrongdoing.

## `argos_m8_dev.parquet`

M3 audited tabular matrix joined 1:1 with semantic, graph and anomaly feature families. It deliberately excludes `test`; it exists for development/ablation only.

## `m8_survival_outcomes.parquet`

**Grain:** 1 row = 1 M8 development contract.

| Column | Meaning |
|---|---|
| `contract_id` | canonical contract identifier |
| `t0` | prediction/origin timestamp |
| `split` | `train` or `validation` only |
| `event_observed` | 1 when the first qualifying addition occurs within 180d; otherwise 0 |
| `duration_days` | days to first event, or 180 under administrative censoring |
| `administrative_horizon_days` | fixed target horizon (=180) |

For `event_observed=0`, `duration_days=180` means the contract is event-free through the target horizon. It does not assert absence of future events after day 180.

## Survival reports

`reports/advanced/76_survival_metrics.parquet` contains C-index, Brier and horizon-level event incidence. `76_survival_calibration.parquet` contains predicted vs observed event rates by probability bin. `76_kaplan_meier.parquet` contains TRAIN/VALIDATION KM curves. `76_ph_diagnostics.parquet` records the strongest time correlations in Schoenfeld-style residual diagnostics.
