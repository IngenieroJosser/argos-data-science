import math
import pandas as pd

from argos.graph.temporal import temporal_graph_features, weighted_undirected_pagerank


def test_pagerank_is_normalized():
    snapshot = weighted_undirected_pagerank(
        {('s:a', 'e:x'): 2, ('s:b', 'e:x'): 1},
        alpha=0.85,
        tolerance=1e-10,
        max_iter=200,
    )
    assert snapshot.pagerank
    assert math.isclose(sum(snapshot.pagerank.values()), 1.0, rel_tol=1e-7, abs_tol=1e-7)


def test_graph_features_use_only_prior_month_relations():
    relations = pd.DataFrame({
        'contract_id': ['c1', 'c2', 'c3'],
        't0': pd.to_datetime(['2024-01-10', '2024-01-20', '2024-02-05']),
        'split': ['train', 'train', 'validation'],
        'supplier_code': ['s1', 's1', 's1'],
        'entity_id': ['e1', 'e2', 'e1'],
    })
    result = temporal_graph_features(
        relations,
        cobid_events=pd.DataFrame(columns=['supplier_a', 'supplier_b', 'observed_at']),
        pagerank_alpha=0.85,
        pagerank_tolerance=1e-8,
        pagerank_max_iter=100,
        pagerank_refresh_months=1,
    ).sort_values('contract_id')
    jan = result[result.contract_id.isin(['c1', 'c2'])]
    assert (jan['graph_supplier_weighted_degree_before_t0'] == 0).all()
    feb = result[result.contract_id == 'c3'].iloc[0]
    assert feb['graph_supplier_degree_before_t0'] == 2
    assert feb['graph_supplier_weighted_degree_before_t0'] == 2
    assert feb['graph_pair_weight_before_t0'] == 1
    assert pd.Timestamp(feb['_pit_graph_max_contract_t0']) < pd.Timestamp('2024-02-01')


def test_cobid_features_obey_snapshot_cutoff():
    relations = pd.DataFrame({
        'contract_id': ['c1', 'c2'],
        't0': pd.to_datetime(['2024-01-10', '2024-03-05']),
        'split': ['train', 'validation'],
        'supplier_code': ['s1', 's1'],
        'entity_id': ['e1', 'e1'],
    })
    cobids = pd.DataFrame({
        'supplier_a': ['s1', 's1'],
        'supplier_b': ['s2', 's3'],
        'observed_at': pd.to_datetime(['2024-02-01', '2024-03-02']),
    })
    result = temporal_graph_features(
        relations,
        cobid_events=cobids,
        pagerank_alpha=0.85,
        pagerank_tolerance=1e-8,
        pagerank_max_iter=100,
        pagerank_refresh_months=1,
    ).sort_values('contract_id')
    march = result[result.contract_id == 'c2'].iloc[0]
    # February co-bid is historical; March co-bid is same-month and therefore excluded.
    assert march['graph_cobid_partner_degree_before_t0'] == 1
    assert march['graph_cobid_weighted_degree_before_t0'] == 1
    assert pd.Timestamp(march['_pit_graph_max_cobid_at']) < pd.Timestamp('2024-03-01')
