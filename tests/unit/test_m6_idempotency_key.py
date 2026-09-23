from argos.production.common import stable_batch_id


def test_batch_id_is_stable_and_lineage_sensitive() -> None:
    a = stable_batch_id("input", "model", "cal", "contract")
    b = stable_batch_id("input", "model", "cal", "contract")
    c = stable_batch_id("input2", "model", "cal", "contract")
    assert a == b
    assert len(a) == 24
    assert a != c
