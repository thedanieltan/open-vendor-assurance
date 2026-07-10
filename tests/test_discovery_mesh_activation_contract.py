from pathlib import Path


def test_discovery_mesh_activation_keeps_canonical_mutation_outside_intake() -> None:
    text = Path("tools/openva/discovery_mesh_activation.py").read_text(encoding="utf-8")
    assert "one reviewed plan per vendor" in text
    assert "vendor_count_cap" in text
    assert "action_count_cap" in text
    assert '"writes_canonical_vendors": False' in text
    assert '"writes_canonical_sources": False' in text
    assert "candidate-promotion workflow remains the sole canonical mutation" in text
