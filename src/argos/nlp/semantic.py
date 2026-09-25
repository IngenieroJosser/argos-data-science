from __future__ import annotations

import os

# Keep the native NLP stack deterministic and stable on macOS/Apple Silicon.
# These must be set before importing NumPy / sklearn / torch-backed libraries.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")

import hashlib
import importlib.metadata
import re
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from argos.common.reports import write_report
from argos.common.validation import add_validation, write_manifest
from argos.config.advanced import AdvancedSpec
from argos.config.gold import GoldSpec


BUILD_IMPLEMENTATION = "m8-70-semantic-intelligence-v1"


@dataclass(frozen=True, slots=True)
class SemanticFeaturesResult:
    artifact: Path
    validation: pd.DataFrame
    manifest_path: Path
    backend_used: str
    index_backend_used: str

    @property
    def ready_for_next_stage(self) -> bool:
        blocking = self.validation.loc[self.validation["blocking"]]
        return bool(not blocking.empty and blocking["passed"].all())


class _Encoder(Protocol):
    backend_name: str

    def encode(self, texts: list[str]) -> np.ndarray: ...


class SentenceTransformerEncoder:
    backend_name = "sentence_transformers"

    def __init__(self, model_name: str, revision: str, batch_size: int) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "M8 semantic closure requires sentence-transformers. "
                "Install the optional M8 dependencies."
            ) from exc
        kwargs: dict[str, Any] = {
            "trust_remote_code": False,
            # M8 closure prioritizes reproducibility/stability over accelerator speed.
            # Explicit CPU avoids native MPS crashes observed on macOS/Apple Silicon.
            "device": "cpu",
        }
        if revision:
            kwargs["revision"] = revision
        self.model = SentenceTransformer(model_name, **kwargs)
        self.batch_size = batch_size

    def encode(self, texts: list[str]) -> np.ndarray:
        values = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return np.asarray(values, dtype=np.float32)


class TfidfSVDEncoder:
    backend_name = "tfidf_svd"

    def __init__(self, train_texts: list[str], components: int, seed: int) -> None:
        self.vectorizer = TfidfVectorizer(
            lowercase=False,
            ngram_range=(1, 2),
            min_df=2,
            max_df=0.995,
            max_features=120_000,
            sublinear_tf=True,
            dtype=np.float32,
        )
        matrix = self.vectorizer.fit_transform(train_texts)
        max_components = min(components, matrix.shape[0] - 1, matrix.shape[1] - 1)
        if max_components < 2:
            raise ValueError(
                "TF-IDF fallback requires at least 3 non-empty training documents/terms"
            )
        self.svd = TruncatedSVD(n_components=max_components, random_state=seed)
        self.svd.fit(matrix)

    def encode(self, texts: list[str]) -> np.ndarray:
        values = self.svd.transform(self.vectorizer.transform(texts)).astype(np.float32)
        return normalize(values, norm="l2", copy=False).astype(np.float32)


class IncrementalCosineIndex:
    def __init__(self, dimension: int, requested_backend: str) -> None:
        self.backend_used = "numpy"
        self._matrix = np.empty((0, dimension), dtype=np.float32)
        self._faiss = None
        if requested_backend == "faiss":
            try:
                import faiss  # type: ignore

                # HNSW has shown native SIGSEGV behaviour on some macOS/arm64 builds.
                # IndexFlatIP is exact cosine search (embeddings are L2-normalized),
                # deterministic, and materially safer for a reproducible closure run.
                if hasattr(faiss, "omp_set_num_threads"):
                    faiss.omp_set_num_threads(1)
                index = faiss.IndexFlatIP(dimension)
                self._faiss = index
                self.backend_used = "faiss"
            except ImportError:
                self._faiss = None
        elif requested_backend != "numpy":
            raise ValueError(f"Unsupported semantic index backend: {requested_backend!r}")

    @property
    def size(self) -> int:
        return int(self._faiss.ntotal) if self._faiss is not None else int(len(self._matrix))

    def add(self, vectors: np.ndarray) -> None:
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        if self._faiss is not None:
            self._faiss.add(vectors)
        else:
            self._matrix = np.vstack([self._matrix, vectors])

    def search(self, vectors: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        if self.size == 0:
            return (
                np.empty((len(vectors), 0), dtype=np.float32),
                np.empty((len(vectors), 0), dtype=np.int64),
            )
        take = min(k, self.size)
        if self._faiss is not None:
            scores, indices = self._faiss.search(vectors, take)
            return scores.astype(np.float32), indices.astype(np.int64)
        scores = vectors @ self._matrix.T
        if take == self.size:
            indices = np.argsort(-scores, axis=1)[:, :take]
        else:
            partial = np.argpartition(-scores, take - 1, axis=1)[:, :take]
            local_scores = np.take_along_axis(scores, partial, axis=1)
            local_order = np.argsort(-local_scores, axis=1)
            indices = np.take_along_axis(partial, local_order, axis=1)
        selected_scores = np.take_along_axis(scores, indices, axis=1)
        return selected_scores.astype(np.float32), indices.astype(np.int64)


def normalize_contract_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    text = "".join(ch if unicodedata.category(ch)[0] != "C" else " " for ch in text)
    return re.sub(r"\s+", " ", text)


def combine_text_columns(frame: pd.DataFrame, columns: tuple[str, ...]) -> list[str]:
    texts: list[str] = []
    for row in frame.loc[:, list(columns)].itertuples(index=False, name=None):
        parts = [normalize_contract_text(value) for value in row]
        texts.append(" [SEP] ".join(part for part in parts if part))
    return texts


def embedding_fingerprint(encoder: _Encoder) -> str:
    sentinels = [
        "contrato de obra pública para mantenimiento vial",
        "servicio profesional de apoyo a la gestión",
        "adquisición de equipos y suministros",
    ]
    values = np.round(encoder.encode(sentinels), decimals=6)
    return hashlib.sha256(values.tobytes()).hexdigest()


def make_encoder(
    frame: pd.DataFrame,
    texts: list[str],
    spec: AdvancedSpec,
) -> tuple[_Encoder, str]:
    if spec.nlp.embedding_backend == "sentence_transformers":
        try:
            encoder = SentenceTransformerEncoder(
                spec.nlp.model_name,
                spec.nlp.model_revision,
                spec.nlp.batch_size,
            )
            return encoder, encoder.backend_name
        except RuntimeError:
            if not spec.nlp.allow_fallback_for_gate:
                raise
    if spec.nlp.fallback_backend != "tfidf_svd":
        raise ValueError(f"Unsupported NLP fallback backend: {spec.nlp.fallback_backend!r}")
    train_mask = frame["split"].astype(str).eq("train").to_numpy()
    train_texts = [text for text, keep in zip(texts, train_mask, strict=True) if keep]
    encoder = TfidfSVDEncoder(train_texts, spec.nlp.svd_components, spec.nlp.random_seed)
    return encoder, encoder.backend_name


SEMANTIC_OUTPUT_TIMESTAMP_COLUMNS = frozenset(
    {
        "t0",
        "_pit_semantic_max_peer_t0",
        "_pit_semantic_max_label_available_at",
    }
)


def canonicalize_semantic_arrow_table(table: Any, pa: Any) -> Any:
    """Return a stable Arrow table schema for streaming semantic feature writes.

    Monthly blocks can infer different timestamp units when a PIT column is all-null
    in an early month and populated in a later month. ParquetWriter requires every
    batch to have the exact same schema, so all semantic timestamps are normalized
    to microseconds and pandas metadata is intentionally removed.
    """
    fields = [
        pa.field(
            field.name,
            pa.timestamp("us")
            if field.name in SEMANTIC_OUTPUT_TIMESTAMP_COLUMNS
            else field.type,
            nullable=field.nullable,
        )
        for field in table.schema
    ]
    canonical_schema = pa.schema(fields)
    return table.cast(canonical_schema, safe=False)


class TemporalSemanticPeerState:
    def __init__(
        self,
        *,
        dimension: int,
        index_backend: str,
        target_column: str,
        horizon_days: int,
        neighbor_k: int,
        min_neighbors: int,
    ) -> None:
        self.index = IncrementalCosineIndex(dimension, index_backend)
        self.target_column = target_column
        self.horizon_days = horizon_days
        self.neighbor_k = neighbor_k
        self.min_neighbors = min_neighbors
        self.history_t0: list[pd.Timestamp] = []
        self.history_label_available: list[pd.Timestamp] = []
        self.history_y: list[int] = []

    @property
    def backend_used(self) -> str:
        return self.index.backend_used

    def transform_month(self, block: pd.DataFrame, embeddings: np.ndarray) -> pd.DataFrame:
        required = {"contract_id", "t0", "split", self.target_column}
        missing = sorted(required - set(block.columns))
        if missing:
            raise KeyError(f"Semantic peer frame missing columns: {missing}")
        if len(block) != len(embeddings):
            raise ValueError("Semantic frame and embedding row counts differ")
        if embeddings.ndim != 2 or embeddings.shape[1] < 2:
            raise ValueError("Semantic embeddings must be a 2D matrix")

        work = block.reset_index(drop=True).copy()
        work["t0"] = pd.to_datetime(work["t0"], errors="raise")
        vectors = np.ascontiguousarray(embeddings, dtype=np.float32)
        scores, ids = self.index.search(vectors, self.neighbor_k)
        records: list[dict[str, Any]] = []
        for local_index, row in work.iterrows():
            peer_ids = ids[local_index] if ids.size else np.empty(0, dtype=np.int64)
            peer_scores = scores[local_index] if scores.size else np.empty(0, dtype=np.float32)
            peer_t0 = [self.history_t0[int(i)] for i in peer_ids]
            label_available = [self.history_label_available[int(i)] for i in peer_ids]
            matured_mask = np.asarray(
                [available < row["t0"] for available in label_available], dtype=bool
            )
            matured_ids = peer_ids[matured_mask] if len(peer_ids) else peer_ids
            matured_count = int(len(matured_ids))
            positive_rate = np.nan
            max_label_available = pd.NaT
            if matured_count >= self.min_neighbors:
                positive_rate = float(
                    np.mean([self.history_y[int(i)] for i in matured_ids])
                )
                max_label_available = max(
                    self.history_label_available[int(i)] for i in matured_ids
                )
            max_similarity = float(np.max(peer_scores)) if len(peer_scores) else np.nan
            records.append(
                {
                    "contract_id": row["contract_id"],
                    "t0": row["t0"],
                    "split": row["split"],
                    "semantic_neighbor_count": int(len(peer_ids)),
                    "semantic_similarity_mean": (
                        float(np.mean(peer_scores)) if len(peer_scores) else np.nan
                    ),
                    "semantic_similarity_max": max_similarity,
                    "semantic_similarity_std": (
                        float(np.std(peer_scores)) if len(peer_scores) else np.nan
                    ),
                    "semantic_novelty_score": (
                        float(1.0 - max_similarity) if len(peer_scores) else 1.0
                    ),
                    "semantic_matured_neighbor_count": matured_count,
                    "semantic_neighbor_addition_rate_matured": positive_rate,
                    "_pit_semantic_max_peer_t0": max(peer_t0) if peer_t0 else pd.NaT,
                    "_pit_semantic_max_label_available_at": max_label_available,
                }
            )

        # The entire month becomes historical only after all rows were scored.
        self.index.add(vectors)
        for _, row in work.iterrows():
            t0 = pd.Timestamp(row["t0"])
            self.history_t0.append(t0)
            self.history_label_available.append(t0 + timedelta(days=self.horizon_days))
            self.history_y.append(int(row[self.target_column]))
        return pd.DataFrame.from_records(records)


def temporal_semantic_peer_features(
    frame: pd.DataFrame,
    embeddings: np.ndarray,
    *,
    target_column: str,
    horizon_days: int,
    neighbor_k: int,
    min_neighbors: int,
    index_backend: str,
) -> tuple[pd.DataFrame, str]:
    required = {"contract_id", "t0", "split", target_column}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"Semantic peer frame missing columns: {missing}")
    if len(frame) != len(embeddings):
        raise ValueError("Semantic frame and embedding row counts differ")
    if embeddings.ndim != 2 or embeddings.shape[1] < 2:
        raise ValueError("Semantic embeddings must be a 2D matrix")

    work = frame.reset_index(drop=True).copy()
    work["t0"] = pd.to_datetime(work["t0"], errors="raise")
    work["_original_row"] = np.arange(len(work), dtype=np.int64)
    work["_month"] = work["t0"].dt.to_period("M")
    order = work.sort_values(["_month", "t0", "contract_id"], kind="stable").index.to_numpy()
    sorted_work = work.loc[order].reset_index(drop=True)
    sorted_embeddings = np.ascontiguousarray(embeddings[order], dtype=np.float32)

    state = TemporalSemanticPeerState(
        dimension=sorted_embeddings.shape[1],
        index_backend=index_backend,
        target_column=target_column,
        horizon_days=horizon_days,
        neighbor_k=neighbor_k,
        min_neighbors=min_neighbors,
    )
    parts: list[pd.DataFrame] = []
    for _, block in sorted_work.groupby("_month", sort=True, observed=True):
        positions = block.index.to_numpy(dtype=np.int64)
        part = state.transform_month(
            block.drop(columns=["_month"]), sorted_embeddings[positions]
        )
        part["_original_row"] = block["_original_row"].to_numpy()
        parts.append(part)
    result = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if not result.empty:
        result = (
            result.sort_values("_original_row")
            .drop(columns=["_original_row"])
            .reset_index(drop=True)
        )
    return result, state.backend_used


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def build_semantic_features(
    *,
    root: Path,
    silver_dir: Path,
    gold_dir: Path,
    reports_root: Path,
    manifest_dir: Path,
    gold_spec: GoldSpec,
    advanced_spec: AdvancedSpec,
) -> SemanticFeaturesResult:
    from argos.common.duckdb import connect
    from argos.common.sql import quote_identifier
    from argos.gold.utils import columns_of, parquet_source

    split_path = gold_dir / "splits" / "temporal_split.parquet"
    contracts_path = silver_dir / "contracts.parquet"
    if not split_path.exists() or not contracts_path.exists():
        raise FileNotFoundError(
            "M8 semantic stage requires Gold temporal_split and Silver contracts"
        )

    artifact = root / advanced_spec.artifacts.semantic_features
    artifact.parent.mkdir(parents=True, exist_ok=True)
    if artifact.exists():
        artifact.unlink()

    con = connect(
        threads=gold_spec.runtime.duckdb_threads,
        memory_limit=gold_spec.runtime.duckdb_memory_limit,
    )
    try:
        split_source = parquet_source(split_path)
        contracts_source = parquet_source(contracts_path)
        contract_columns = set(columns_of(con, contracts_source))
        text_columns = tuple(c for c in advanced_spec.nlp.text_columns if c in contract_columns)
        if not text_columns:
            raise KeyError(
                "None of the configured point-in-time text columns exist in contracts.parquet: "
                f"{list(advanced_spec.nlp.text_columns)}"
            )
        split_literals = ",".join(
            f"'{v}'" for v in advanced_spec.governance.development_splits
        )
        projection = ", ".join(
            f"c.{quote_identifier(c)} AS {quote_identifier(c)}" for c in text_columns
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW m8_semantic_source AS
            SELECT s.contract_id, s.t0, s.split,
                   s.{quote_identifier(gold_spec.target.name)}, {projection}
            FROM {split_source} s
            JOIN {contracts_source} c USING (contract_id)
            WHERE s.split IN ({split_literals})
            """
        )
        source_rows = int(con.execute("SELECT COUNT(*) FROM m8_semantic_source").fetchone()[0])
        if source_rows <= 0:
            raise ValueError("M8 semantic source has no TRAIN/VALIDATION rows")
        months = (
            con.execute(
                """
                SELECT DISTINCT DATE_TRUNC('month', t0) AS month_start
                FROM m8_semantic_source
                WHERE t0 IS NOT NULL
                ORDER BY 1
                """
            )
            .fetchdf()["month_start"]
            .tolist()
        )

        encoder: _Encoder
        backend_used: str
        use_streaming = advanced_spec.nlp.embedding_backend == "sentence_transformers"
        if use_streaming:
            try:
                encoder = SentenceTransformerEncoder(
                    advanced_spec.nlp.model_name,
                    advanced_spec.nlp.model_revision,
                    advanced_spec.nlp.batch_size,
                )
                backend_used = encoder.backend_name
            except RuntimeError:
                if not advanced_spec.nlp.allow_fallback_for_gate:
                    raise
                use_streaming = False

        if not use_streaming:
            frame = con.execute(
                "SELECT * FROM m8_semantic_source ORDER BY t0, contract_id"
            ).fetchdf()
            texts = combine_text_columns(frame, text_columns)
            char_counts = np.asarray([len(text) for text in texts], dtype=np.int64)
            usable = char_counts >= advanced_spec.nlp.min_text_chars
            encoded_texts = [
                text if is_usable else "__missing_contract_text__"
                for text, is_usable in zip(texts, usable, strict=True)
            ]
            encoder, backend_used = make_encoder(frame, encoded_texts, advanced_spec)
            embeddings = encoder.encode(encoded_texts)
            features, index_backend_used = temporal_semantic_peer_features(
                frame[["contract_id", "t0", "split", gold_spec.target.name]],
                embeddings,
                target_column=gold_spec.target.name,
                horizon_days=gold_spec.target.horizon_days,
                neighbor_k=advanced_spec.nlp.neighbor_k,
                min_neighbors=advanced_spec.nlp.min_neighbors,
                index_backend=advanced_spec.nlp.index_backend,
            )
            features["semantic_text_chars"] = char_counts
            features["semantic_text_missing"] = (~usable).astype("int8")
            features["_m8_schema_version"] = advanced_spec.schema_version
            features.to_parquet(artifact, index=False)
            rows_written = len(features)
        else:
            import pyarrow as pa
            import pyarrow.parquet as pq

            writer: pq.ParquetWriter | None = None
            rows_written = 0
            state: TemporalSemanticPeerState | None = None
            try:
                total_months = len(months)
                for month_index, raw_month_start in enumerate(months, start=1):
                    month_start = pd.Timestamp(raw_month_start)
                    month_end = month_start + pd.offsets.MonthBegin(1)
                    print(
                        f"[M8:70] month {month_index}/{total_months} "
                        f"{month_start:%Y-%m}: loading rows",
                        flush=True,
                    )
                    frame = con.execute(
                        """
                        SELECT *
                        FROM m8_semantic_source
                        WHERE t0 >= ? AND t0 < ?
                        ORDER BY t0, contract_id
                        """,
                        [month_start.to_pydatetime(), month_end.to_pydatetime()],
                    ).fetchdf()
                    if frame.empty:
                        continue
                    texts = combine_text_columns(frame, text_columns)
                    char_counts = np.asarray([len(text) for text in texts], dtype=np.int64)
                    usable = char_counts >= advanced_spec.nlp.min_text_chars
                    encoded_texts = [
                        text if is_usable else "__missing_contract_text__"
                        for text, is_usable in zip(texts, usable, strict=True)
                    ]
                    print(
                        f"[M8:70] month {month_index}/{total_months} "
                        f"{month_start:%Y-%m}: encoding {len(encoded_texts):,} texts",
                        flush=True,
                    )
                    embeddings = encoder.encode(encoded_texts)
                    print(
                        f"[M8:70] month {month_index}/{total_months} "
                        f"{month_start:%Y-%m}: semantic peer search",
                        flush=True,
                    )
                    if state is None:
                        state = TemporalSemanticPeerState(
                            dimension=embeddings.shape[1],
                            index_backend=advanced_spec.nlp.index_backend,
                            target_column=gold_spec.target.name,
                            horizon_days=gold_spec.target.horizon_days,
                            neighbor_k=advanced_spec.nlp.neighbor_k,
                            min_neighbors=advanced_spec.nlp.min_neighbors,
                        )
                    features = state.transform_month(
                        frame[["contract_id", "t0", "split", gold_spec.target.name]],
                        embeddings,
                    )
                    features["semantic_text_chars"] = char_counts
                    features["semantic_text_missing"] = (~usable).astype("int8")
                    features["_m8_schema_version"] = advanced_spec.schema_version
                    table = pa.Table.from_pandas(features, preserve_index=False)
                    table = canonicalize_semantic_arrow_table(table, pa)
                    if writer is None:
                        writer = pq.ParquetWriter(artifact, table.schema, compression="zstd")
                    else:
                        # Defensive cast: ParquetWriter requires exact schema equality
                        # for every monthly block, including timestamp precision.
                        table = table.cast(writer.schema, safe=False)
                    writer.write_table(table)
                    rows_written += len(features)
                    print(
                        f"[M8:70] month {month_index}/{total_months} "
                        f"{month_start:%Y-%m}: wrote {len(features):,} rows "
                        f"(total={rows_written:,})",
                        flush=True,
                    )
            except Exception:
                if writer is not None:
                    writer.close()
                    writer = None
                artifact.unlink(missing_ok=True)
                raise
            finally:
                if writer is not None:
                    writer.close()
            if state is None:
                raise ValueError("M8 semantic streaming stage produced no monthly blocks")
            index_backend_used = state.backend_used

        semantic = parquet_source(artifact)
        stats = con.execute(
            f"""
            SELECT
                COUNT(*) AS rows,
                COUNT(DISTINCT contract_id) AS distinct_contracts,
                COUNT(*) FILTER (
                    WHERE _pit_semantic_max_peer_t0 IS NOT NULL
                      AND _pit_semantic_max_peer_t0 >= t0
                ) AS peer_future,
                COUNT(*) FILTER (
                    WHERE _pit_semantic_max_label_available_at IS NOT NULL
                      AND _pit_semantic_max_label_available_at >= t0
                ) AS label_future
            FROM {semantic}
            """
        ).fetchdf().iloc[0]
        observed_splits = (
            con.execute(f"SELECT DISTINCT split FROM {semantic} ORDER BY 1")
            .fetchdf()["split"]
            .astype(str)
            .tolist()
        )
    finally:
        con.close()

    peer_future = int(stats["peer_future"])
    label_future = int(stats["label_future"])
    row_count = int(stats["rows"])
    distinct_contracts = int(stats["distinct_contracts"])
    backend_ok = backend_used == advanced_spec.nlp.embedding_backend
    index_ok = (
        index_backend_used == advanced_spec.nlp.index_backend
        or advanced_spec.nlp.allow_fallback_for_gate
    )

    records: list[dict[str, Any]] = []
    add_validation(
        records,
        check_id="semantic_rows_aligned",
        category="grain",
        passed=(
            row_count == source_rows
            and distinct_contracts == source_rows
            and rows_written == source_rows
        ),
        observed={
            "source_rows": source_rows,
            "feature_rows": row_count,
            "distinct_contracts": distinct_contracts,
        },
        requirement="one semantic feature row per M8 development contract",
    )
    add_validation(
        records,
        check_id="semantic_peer_pit",
        category="point_in_time",
        passed=peer_future <= advanced_spec.governance.max_future_feature_violations,
        observed={"future_or_same_time_peer_violations": peer_future},
        requirement="semantic peers come only from prior monthly snapshots",
    )
    add_validation(
        records,
        check_id="semantic_label_maturity_pit",
        category="point_in_time",
        passed=label_future <= advanced_spec.governance.max_future_feature_violations,
        observed={"unmatured_label_violations": label_future},
        requirement=(
            "semantic peer outcome rates use only 180-day labels already mature at current t0"
        ),
    )
    add_validation(
        records,
        check_id="semantic_holdouts_isolated",
        category="evaluation_governance",
        passed=set(observed_splits).issubset(
            set(advanced_spec.governance.development_splits)
        ),
        observed={"splits": observed_splits},
        requirement="M8 semantic development consumes only TRAIN/VALIDATION",
    )
    add_validation(
        records,
        check_id="semantic_backend_contract",
        category="runtime",
        passed=backend_ok and index_ok,
        observed={
            "embedding_requested": advanced_spec.nlp.embedding_backend,
            "embedding_used": backend_used,
            "index_requested": advanced_spec.nlp.index_backend,
            "index_used": index_backend_used,
        },
        requirement="M8 closure uses the configured SentenceTransformer + FAISS semantic backend",
    )
    validation = pd.DataFrame.from_records(records)
    write_report(validation, reports_root / "advanced" / "70_validation.parquet")

    manifest_path = root / advanced_spec.artifacts.semantic_manifest
    write_manifest(
        manifest_path,
        {
            "schema_version": advanced_spec.schema_version,
            "implementation": BUILD_IMPLEMENTATION,
            "artifact": str(artifact.relative_to(root)),
            "rows": row_count,
            "splits": observed_splits,
            "text_columns": list(text_columns),
            "embedding_backend_requested": advanced_spec.nlp.embedding_backend,
            "embedding_backend_used": backend_used,
            "embedding_model": advanced_spec.nlp.model_name,
            "embedding_revision": advanced_spec.nlp.model_revision or None,
            "embedding_fingerprint": embedding_fingerprint(encoder),
            "index_backend_requested": advanced_spec.nlp.index_backend,
            "index_backend_used": index_backend_used,
            "neighbor_k": advanced_spec.nlp.neighbor_k,
            "target_label_maturity_days": gold_spec.target.horizon_days,
            "processing_mode": "monthly_streaming" if use_streaming else "materialized_fallback",
            "sentence_transformers_version": package_version("sentence-transformers"),
            "faiss_version": package_version("faiss-cpu"),
            "consumed_test_or_oot_for_selection": False,
        },
    )
    return SemanticFeaturesResult(
        artifact=artifact,
        validation=validation,
        manifest_path=manifest_path,
        backend_used=backend_used,
        index_backend_used=index_backend_used,
    )

