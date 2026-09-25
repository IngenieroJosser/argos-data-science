import numpy as np
import pandas as pd

from argos.nlp.semantic import temporal_semantic_peer_features


def test_semantic_peers_are_prior_month_only_and_labels_must_be_matured():
    frame = pd.DataFrame({
        'contract_id': ['a', 'b', 'c'],
        't0': pd.to_datetime(['2024-01-10', '2024-01-20', '2024-08-15']),
        'split': ['train', 'train', 'validation'],
        'target_adicion_180d': [1, 0, 0],
    })
    embeddings = np.asarray([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    result, backend = temporal_semantic_peer_features(
        frame,
        embeddings,
        target_column='target_adicion_180d',
        horizon_days=180,
        neighbor_k=2,
        min_neighbors=1,
        index_backend='numpy',
    )
    result = result.sort_values('contract_id')
    assert backend == 'numpy'
    jan = result[result.contract_id.isin(['a', 'b'])]
    assert (jan['semantic_neighbor_count'] == 0).all()
    aug = result[result.contract_id == 'c'].iloc[0]
    assert aug['semantic_neighbor_count'] == 2
    assert aug['semantic_matured_neighbor_count'] == 2
    assert aug['semantic_neighbor_addition_rate_matured'] == 0.5
    assert pd.Timestamp(aug['_pit_semantic_max_peer_t0']) < pd.Timestamp('2024-08-01')
    assert pd.Timestamp(aug['_pit_semantic_max_label_available_at']) < pd.Timestamp('2024-08-15')
