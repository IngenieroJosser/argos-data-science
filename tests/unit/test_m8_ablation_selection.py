import pandas as pd

from argos.advanced.ablation import select_m8_family


def _metrics(rows):
    return pd.DataFrame(rows, columns=['feature_family', 'pr_auc'])


def _ranking(rows):
    return pd.DataFrame(rows, columns=['feature_family', 'review_fraction', 'lift_at_k'])


def test_selection_promotes_only_if_pr_auc_and_lift_do_not_regress():
    metrics = _metrics([('tabular', 0.10), ('tabular_nlp', 0.12), ('tabular_graph', 0.11)])
    ranking = _ranking(
        [('tabular', 0.01, 4.0), ('tabular_nlp', 0.01, 4.4), ('tabular_graph', 0.01, 3.8)]
    )
    out = select_m8_family(
        metrics,
        ranking,
        operational_fraction=0.01,
        min_pr_auc_relative_gain=0.0,
        min_lift_relative_gain=0.0,
    )
    assert out['decision'] == 'PROMOTE_M8_FEATURES'
    assert out['selected_family'] == 'tabular_nlp'


def test_selection_can_close_research_without_promotion():
    metrics = _metrics([('tabular', 0.10), ('tabular_nlp', 0.09)])
    ranking = _ranking([('tabular', 0.01, 4.0), ('tabular_nlp', 0.01, 5.0)])
    out = select_m8_family(
        metrics,
        ranking,
        operational_fraction=0.01,
        min_pr_auc_relative_gain=0.0,
        min_lift_relative_gain=0.0,
    )
    assert out['decision'] == 'RESEARCH_COMPLETE_NO_PROMOTION'
    assert out['selected_family'] is None
