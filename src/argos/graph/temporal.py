from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.csgraph import connected_components

from argos.common.reports import write_report
from argos.common.validation import add_validation, write_manifest
from argos.config.advanced import AdvancedSpec
from argos.config.gold import GoldSpec


BUILD_IMPLEMENTATION = "m8-71-temporal-graph-intelligence-v1"


@dataclass(frozen=True, slots=True)
class GraphFeaturesResult:
    artifact: Path
    validation: pd.DataFrame
    manifest_path: Path

    @property
    def ready_for_next_stage(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    pagerank: dict[str, float]
    component_size: dict[str, int]
    edge_count: int
    node_count: int


def weighted_undirected_pagerank(
    edges: dict[tuple[str, str], int],
    *,
    alpha: float,
    tolerance: float,
    max_iter: int,
) -> GraphSnapshot:
    if not edges:
        return GraphSnapshot({}, {}, 0, 0)
    nodes = sorted({node for edge in edges for node in edge})
    node_index = {node: idx for idx, node in enumerate(nodes)}
    rows: list[int] = []
    cols: list[int] = []
    values: list[float] = []
    active_edges = 0
    for (left, right), weight in edges.items():
        if weight <= 0:
            continue
        active_edges += 1
        i = node_index[left]
        j = node_index[right]
        w = float(weight)
        rows.extend([i, j])
        cols.extend([j, i])
        values.extend([w, w])
    adjacency = sparse.csr_matrix(
        (values, (rows, cols)), shape=(len(nodes), len(nodes)), dtype=float
    )
    strength = np.asarray(adjacency.sum(axis=1)).ravel()
    n = len(nodes)
    rank = np.full(n, 1.0 / n, dtype=float)
    dangling = strength == 0
    transition = sparse.diags(1.0 / np.where(strength > 0, strength, 1.0)) @ adjacency
    teleport = (1.0 - alpha) / n
    for _ in range(max_iter):
        dangling_mass = float(rank[dangling].sum()) / n
        updated = alpha * (transition.T @ rank + dangling_mass) + teleport
        if np.abs(updated - rank).sum() <= tolerance:
            rank = updated
            break
        rank = updated
    if rank.sum() > 0:
        rank /= rank.sum()

    binary = adjacency.copy()
    binary.data[:] = 1.0
    n_components, labels = connected_components(binary, directed=False, return_labels=True)
    component_sizes = np.bincount(labels, minlength=n_components)
    return GraphSnapshot(
        pagerank={node: float(rank[idx]) for node, idx in node_index.items()},
        component_size={
            node: int(component_sizes[labels[idx]]) for node, idx in node_index.items()
        },
        edge_count=active_edges,
        node_count=n,
    )


def clean_identifier(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


class TemporalGraphState:
    def __init__(self) -> None:
        self.edge_counts: dict[tuple[str, str], int] = {}
        self.supplier_neighbors: dict[str, set[str]] = defaultdict(set)
        self.entity_neighbors: dict[str, set[str]] = defaultdict(set)
        self.supplier_weighted: dict[str, int] = defaultdict(int)
        self.entity_weighted: dict[str, int] = defaultdict(int)
        self.supplier_square_sum: dict[str, int] = defaultdict(int)
        self.entity_square_sum: dict[str, int] = defaultdict(int)
        self.cobid_counts: dict[tuple[str, str], int] = {}
        self.cobid_neighbors: dict[str, set[str]] = defaultdict(set)
        self.cobid_weighted: dict[str, int] = defaultdict(int)
        self.max_contract_t0: pd.Timestamp | None = None
        self.max_cobid_at: pd.Timestamp | None = None

    @staticmethod
    def supplier_node(supplier: str) -> str:
        return f"supplier::{supplier}"

    @staticmethod
    def entity_node(entity: str) -> str:
        return f"entity::{entity}"

    def add_contract(self, supplier: str | None, entity: str | None, t0: pd.Timestamp) -> None:
        if not supplier or not entity:
            return
        key = (supplier, entity)
        old = self.edge_counts.get(key, 0)
        new = old + 1
        self.edge_counts[key] = new
        self.supplier_neighbors[supplier].add(entity)
        self.entity_neighbors[entity].add(supplier)
        self.supplier_weighted[supplier] += 1
        self.entity_weighted[entity] += 1
        delta_square = new * new - old * old
        self.supplier_square_sum[supplier] += delta_square
        self.entity_square_sum[entity] += delta_square
        self.max_contract_t0 = t0 if self.max_contract_t0 is None else max(self.max_contract_t0, t0)

    def add_cobid(self, left: str, right: str, observed_at: pd.Timestamp) -> None:
        if not left or not right or left == right:
            return
        a, b = sorted((left, right))
        key = (a, b)
        self.cobid_counts[key] = self.cobid_counts.get(key, 0) + 1
        self.cobid_neighbors[a].add(b)
        self.cobid_neighbors[b].add(a)
        self.cobid_weighted[a] += 1
        self.cobid_weighted[b] += 1
        self.max_cobid_at = (
            observed_at
            if self.max_cobid_at is None
            else max(self.max_cobid_at, observed_at)
        )

    def bipartite_edges(self) -> dict[tuple[str, str], int]:
        return {
            (self.supplier_node(supplier), self.entity_node(entity)): weight
            for (supplier, entity), weight in self.edge_counts.items()
            if weight > 0
        }

    def features(
        self,
        supplier: str | None,
        entity: str | None,
        snapshot: GraphSnapshot,
    ) -> dict[str, Any]:
        supplier_key = supplier or ""
        entity_key = entity or ""
        supplier_degree = len(self.supplier_neighbors.get(supplier_key, set()))
        entity_degree = len(self.entity_neighbors.get(entity_key, set()))
        supplier_weighted = self.supplier_weighted.get(supplier_key, 0)
        entity_weighted = self.entity_weighted.get(entity_key, 0)
        pair_weight = self.edge_counts.get((supplier_key, entity_key), 0)
        supplier_hhi = (
            self.supplier_square_sum.get(supplier_key, 0) / float(supplier_weighted**2)
            if supplier_weighted
            else np.nan
        )
        entity_hhi = (
            self.entity_square_sum.get(entity_key, 0) / float(entity_weighted**2)
            if entity_weighted
            else np.nan
        )
        cobid_partners = self.cobid_neighbors.get(supplier_key, set())
        repeated_partners = sum(
            1
            for partner in cobid_partners
            if self.cobid_counts.get(tuple(sorted((supplier_key, partner))), 0) >= 2
        )
        supplier_node = self.supplier_node(supplier) if supplier else ""
        entity_node = self.entity_node(entity) if entity else ""
        return {
            "graph_supplier_degree_before_t0": supplier_degree,
            "graph_entity_degree_before_t0": entity_degree,
            "graph_supplier_weighted_degree_before_t0": supplier_weighted,
            "graph_entity_weighted_degree_before_t0": entity_weighted,
            "graph_pair_weight_before_t0": pair_weight,
            "graph_supplier_entity_share_before_t0": (
                pair_weight / float(supplier_weighted) if supplier_weighted else np.nan
            ),
            "graph_entity_supplier_share_before_t0": (
                pair_weight / float(entity_weighted) if entity_weighted else np.nan
            ),
            "graph_supplier_hhi_before_t0": supplier_hhi,
            "graph_entity_hhi_before_t0": entity_hhi,
            "graph_supplier_pagerank_before_t0": snapshot.pagerank.get(supplier_node, 0.0),
            "graph_entity_pagerank_before_t0": snapshot.pagerank.get(entity_node, 0.0),
            "graph_supplier_component_size_before_t0": snapshot.component_size.get(
                supplier_node, 0
            ),
            "graph_entity_component_size_before_t0": snapshot.component_size.get(entity_node, 0),
            "graph_cobid_partner_degree_before_t0": len(cobid_partners),
            "graph_cobid_weighted_degree_before_t0": self.cobid_weighted.get(supplier_key, 0),
            "graph_cobid_repeated_partner_share_before_t0": (
                repeated_partners / float(len(cobid_partners)) if cobid_partners else np.nan
            ),
        }


def build_cobid_pair_events(
    bidder_rows: pd.DataFrame,
    *,
    max_bidders_per_process: int,
) -> pd.DataFrame:
    required = {"process_id", "supplier_code", "observed_at"}
    missing = sorted(required - set(bidder_rows.columns))
    if missing:
        raise KeyError(f"Co-bid input missing columns: {missing}")
    work = bidder_rows.copy()
    work["observed_at"] = pd.to_datetime(work["observed_at"], errors="coerce")
    work["supplier_code"] = work["supplier_code"].map(clean_identifier)
    work = work.dropna(subset=["process_id", "supplier_code", "observed_at"])
    work = (
        work.groupby(["process_id", "supplier_code"], as_index=False, observed=True)["observed_at"]
        .min()
        .sort_values(["process_id", "supplier_code"])
    )
    records: list[dict[str, Any]] = []
    for process_id, group in work.groupby("process_id", sort=False, observed=True):
        values = list(group[["supplier_code", "observed_at"]].itertuples(index=False, name=None))
        if len(values) < 2 or len(values) > max_bidders_per_process:
            continue
        for (left, left_at), (right, right_at) in combinations(values, 2):
            a, b = sorted((str(left), str(right)))
            records.append(
                {
                    "process_id": process_id,
                    "supplier_a": a,
                    "supplier_b": b,
                    "observed_at": max(pd.Timestamp(left_at), pd.Timestamp(right_at)),
                }
            )
    if not records:
        return pd.DataFrame(columns=["process_id", "supplier_a", "supplier_b", "observed_at"])
    return pd.DataFrame.from_records(records).drop_duplicates(
        ["process_id", "supplier_a", "supplier_b"]
    )


def temporal_graph_features(
    relations: pd.DataFrame,
    cobid_events: pd.DataFrame,
    *,
    pagerank_alpha: float,
    pagerank_tolerance: float,
    pagerank_max_iter: int,
    pagerank_refresh_months: int,
) -> pd.DataFrame:
    required = {"contract_id", "t0", "split", "supplier_code", "entity_id"}
    missing = sorted(required - set(relations.columns))
    if missing:
        raise KeyError(f"Graph relation frame missing columns: {missing}")
    work = relations.copy()
    work["t0"] = pd.to_datetime(work["t0"], errors="raise")
    work["supplier_code"] = work["supplier_code"].map(clean_identifier)
    work["entity_id"] = work["entity_id"].map(clean_identifier)
    work["_month"] = work["t0"].dt.to_period("M")
    work = work.sort_values(["_month", "t0", "contract_id"], kind="stable")

    pairs = cobid_events.copy()
    if not pairs.empty:
        pairs["observed_at"] = pd.to_datetime(pairs["observed_at"], errors="raise")
        pairs = pairs.sort_values(["observed_at", "supplier_a", "supplier_b"], kind="stable")
    pair_records = pairs.to_dict(orient="records") if not pairs.empty else []
    pair_cursor = 0
    state = TemporalGraphState()
    snapshot = GraphSnapshot({}, {}, 0, 0)
    records: list[dict[str, Any]] = []

    for month_index, month in enumerate(work["_month"].drop_duplicates().tolist()):
        month_start = month.to_timestamp(how="start")
        while pair_cursor < len(pair_records):
            event = pair_records[pair_cursor]
            observed_at = pd.Timestamp(event["observed_at"])
            if observed_at >= month_start:
                break
            state.add_cobid(str(event["supplier_a"]), str(event["supplier_b"]), observed_at)
            pair_cursor += 1

        if month_index == 0 or month_index % pagerank_refresh_months == 0:
            snapshot = weighted_undirected_pagerank(
                state.bipartite_edges(),
                alpha=pagerank_alpha,
                tolerance=pagerank_tolerance,
                max_iter=pagerank_max_iter,
            )

        block = work.loc[work["_month"] == month]
        for _, row in block.iterrows():
            supplier = clean_identifier(row["supplier_code"])
            entity = clean_identifier(row["entity_id"])
            records.append(
                {
                    "contract_id": row["contract_id"],
                    "t0": pd.Timestamp(row["t0"]),
                    "split": row["split"],
                    **state.features(supplier, entity, snapshot),
                    "_pit_graph_snapshot_at": month_start,
                    "_pit_graph_max_contract_t0": state.max_contract_t0,
                    "_pit_graph_max_cobid_at": state.max_cobid_at,
                }
            )
        # Conservative same-month isolation: current month becomes history only afterwards.
        for _, row in block.iterrows():
            state.add_contract(
                clean_identifier(row["supplier_code"]),
                clean_identifier(row["entity_id"]),
                pd.Timestamp(row["t0"]),
            )
    return pd.DataFrame.from_records(records)


def build_graph_features(
    *,
    root: Path,
    silver_dir: Path,
    gold_dir: Path,
    reports_root: Path,
    manifest_dir: Path,
    gold_spec: GoldSpec,
    advanced_spec: AdvancedSpec,
) -> GraphFeaturesResult:
    from argos.common.duckdb import connect
    from argos.common.sql import quote_identifier
    from argos.gold.utils import parquet_source
    from argos.silver.utils import compact_identifier_expr

    split_path = gold_dir / "splits" / "temporal_split.parquet"
    contracts_path = silver_dir / "contracts.parquet"
    bidders_path = silver_dir / "bidder_participations.parquet"
    process_map_path = silver_dir / "procedure_process_map.parquet"
    entity_map_path = silver_dir / "bidder_supplier_entity_map.parquet"
    required_paths = [split_path, contracts_path, bidders_path, process_map_path, entity_map_path]
    missing_paths = [str(path) for path in required_paths if not path.exists()]
    if missing_paths:
        raise FileNotFoundError(f"M8 graph stage missing required artifacts: {missing_paths}")

    con = connect(
        threads=gold_spec.runtime.duckdb_threads,
        memory_limit=gold_spec.runtime.duckdb_memory_limit,
    )
    try:
        split = parquet_source(split_path)
        contracts = parquet_source(contracts_path)
        bidders = parquet_source(bidders_path)
        process_map = parquet_source(process_map_path)
        entity_map = parquet_source(entity_map_path)
        split_literals = ",".join(f"'{v}'" for v in advanced_spec.governance.development_splits)
        relations = con.execute(
            f"""
            SELECT s.contract_id, s.t0, s.split,
                   c.{quote_identifier(gold_spec.historical_features.supplier_key)}
                       AS supplier_code,
                   c.{quote_identifier(gold_spec.historical_features.entity_key)} AS entity_id
            FROM {split} s
            JOIN {contracts} c USING (contract_id)
            WHERE s.split IN ({split_literals})
            ORDER BY s.t0, s.contract_id
            """
        ).fetchdf()

        publication = advanced_spec.graph.publication_time_column
        nit_normalized = compact_identifier_expr("bidder_nit")
        publication_filter = (
            f"b.{quote_identifier(publication)} IS NOT NULL"
            if advanced_spec.graph.require_publication_timestamp
            else "TRUE"
        )
        bidder_rows = con.execute(
            f"""
            WITH prepared AS (
                SELECT
                    pm.process_id,
                    b.{quote_identifier(publication)} AS observed_at,
                    CASE
                        WHEN b.bidder_code IS NOT NULL THEN 'code:' || b.bidder_code
                        WHEN {nit_normalized} IS NOT NULL THEN 'nit:' || {nit_normalized}
                        ELSE 'row:' || b._source_row_hash
                    END AS bidder_key
                FROM {bidders} b
                JOIN {process_map} pm USING (procedure_id)
                WHERE pm.resolution_status = 'resolved_unique'
                  AND {publication_filter}
            )
            SELECT p.process_id, er.supplier_code, p.observed_at
            FROM prepared p
            JOIN {entity_map} er USING (bidder_key)
            WHERE er.resolution_status = 'resolved_unique'
              AND er.supplier_code IS NOT NULL
            """
        ).fetchdf()
    finally:
        con.close()

    cobid_events = build_cobid_pair_events(
        bidder_rows,
        max_bidders_per_process=advanced_spec.graph.max_bidders_per_process,
    )
    features = temporal_graph_features(
        relations,
        cobid_events,
        pagerank_alpha=advanced_spec.graph.pagerank_alpha,
        pagerank_tolerance=advanced_spec.graph.pagerank_tolerance,
        pagerank_max_iter=advanced_spec.graph.pagerank_max_iter,
        pagerank_refresh_months=advanced_spec.graph.pagerank_refresh_months,
    )
    features["_m8_schema_version"] = advanced_spec.schema_version
    artifact = root / advanced_spec.artifacts.graph_features
    artifact.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(artifact, index=False)

    t0 = pd.to_datetime(features["t0"])
    max_contract = pd.to_datetime(features["_pit_graph_max_contract_t0"], errors="coerce")
    max_cobid = pd.to_datetime(features["_pit_graph_max_cobid_at"], errors="coerce")
    contract_future = int((max_contract.notna() & (max_contract >= t0)).sum())
    cobid_future = int((max_cobid.notna() & (max_cobid >= t0)).sum())
    observed_splits = sorted(features["split"].astype(str).unique().tolist())
    graph_columns = [c for c in features.columns if c.startswith("graph_")]
    finite_or_null = all(
        np.isfinite(pd.to_numeric(features[column], errors="coerce").dropna()).all()
        for column in graph_columns
    )

    records: list[dict[str, Any]] = []
    add_validation(
        records,
        check_id="graph_rows_aligned",
        category="grain",
        passed=len(features) == len(relations) and features["contract_id"].is_unique,
        observed={"source_rows": len(relations), "feature_rows": len(features)},
        requirement="one graph feature row per M8 development contract",
    )
    add_validation(
        records,
        check_id="graph_contract_history_pit",
        category="point_in_time",
        passed=contract_future <= advanced_spec.governance.max_future_feature_violations,
        observed={"future_or_same_time_contract_history": contract_future},
        requirement="supplier-entity graph uses only prior monthly contract history",
    )
    add_validation(
        records,
        check_id="graph_cobid_history_pit",
        category="point_in_time",
        passed=cobid_future <= advanced_spec.governance.max_future_feature_violations,
        observed={"future_or_same_time_cobid_history": cobid_future},
        requirement="co-bidding graph uses only bidder observations published before current t0",
    )
    add_validation(
        records,
        check_id="graph_holdouts_isolated",
        category="evaluation_governance",
        passed=set(observed_splits).issubset(set(advanced_spec.governance.development_splits)),
        observed={"splits": observed_splits},
        requirement="M8 graph development consumes only TRAIN/VALIDATION",
    )
    add_validation(
        records,
        check_id="graph_family_nontrivial",
        category="quality",
        passed=finite_or_null and len(graph_columns) >= 10,
        observed={"feature_count": len(graph_columns)},
        requirement=(
            "graph intelligence exposes finite relational features beyond M3 count features"
        ),
    )
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "advanced" / "71_validation.parquet")

    manifest_path = root / advanced_spec.artifacts.graph_manifest
    write_manifest(
        manifest_path,
        {
            "schema_version": advanced_spec.schema_version,
            "implementation": BUILD_IMPLEMENTATION,
            "artifact": str(artifact.relative_to(root)),
            "rows": len(features),
            "splits": observed_splits,
            "snapshot_frequency": advanced_spec.graph.snapshot_frequency,
            "pagerank_refresh_months": advanced_spec.graph.pagerank_refresh_months,
            "co_bid_pair_events": len(cobid_events),
            "max_bidders_per_process": advanced_spec.graph.max_bidders_per_process,
            "feature_columns": graph_columns,
            "consumed_test_or_oot_for_selection": False,
        },
    )
    return GraphFeaturesResult(
        artifact=artifact, validation=validation, manifest_path=manifest_path
    )
