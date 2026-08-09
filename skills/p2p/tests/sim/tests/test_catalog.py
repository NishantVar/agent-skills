from pathlib import Path

from lib.catalog import load_catalog, validate_catalog


def test_load_catalog_returns_steps_and_settings():
    catalog_path = Path(__file__).resolve().parents[1] / "catalog.yaml"
    cat = load_catalog(catalog_path)
    assert cat.run_settings.max_hops_per_step == 4
    assert cat.run_settings.step_timeout_seconds == 60
    assert len(cat.steps) == 11
    assert cat.steps[0].name == "baseline"
    assert cat.steps[10].classification == "probe"


def test_validate_catalog_passes_on_real_file():
    catalog_path = Path(__file__).resolve().parents[1] / "catalog.yaml"
    cat = load_catalog(catalog_path)
    validate_catalog(cat)  # no exception


def test_validate_rejects_step_id_gaps(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "run_settings: {max_hops_per_step: 4, step_timeout_seconds: 60, ttl_seconds: 1800}\n"
        "steps:\n"
        "  - {id: 1, name: a, classification: pass_fail, actions: [], assertions: []}\n"
        "  - {id: 3, name: c, classification: pass_fail, actions: [], assertions: []}\n"
    )
    import pytest
    with pytest.raises(ValueError, match="step id gap"):
        validate_catalog(load_catalog(bad))


def test_classification_must_be_pass_fail_or_probe(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "run_settings: {max_hops_per_step: 4, step_timeout_seconds: 60, ttl_seconds: 1800}\n"
        "steps:\n"
        "  - {id: 1, name: a, classification: typo, actions: [], assertions: []}\n"
    )
    import pytest
    with pytest.raises(ValueError, match="classification"):
        validate_catalog(load_catalog(bad))
