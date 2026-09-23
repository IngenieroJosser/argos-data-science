from argos.production.deployment import transition_allowed


STAGES = ("candidate", "shadow", "paused", "archived")


def test_safe_shadow_and_rollback_transitions_exist() -> None:
    assert transition_allowed("candidate", "shadow", STAGES)
    assert transition_allowed("shadow", "paused", STAGES)
    assert transition_allowed("paused", "candidate", STAGES)


def test_direct_production_transition_is_impossible() -> None:
    assert not transition_allowed("candidate", "production", STAGES)
    assert not transition_allowed("shadow", "production", STAGES)
