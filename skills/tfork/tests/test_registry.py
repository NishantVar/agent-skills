"""Registry read/write round-trips and the self-building behaviour."""

import tforklib as ft


def test_absent_registry_reads_as_empty(tmp_path):
    assert ft.read_registry(tmp_path / "missing.toml") == {}


def test_write_then_read_roundtrip(tmp_path):
    reg = tmp_path / "registry.toml"
    ft.write_registry_entry("claude", True, reg)
    ft.write_registry_entry("npm", False, reg)
    assert ft.read_registry(reg) == {"claude": True, "npm": False}


def test_write_creates_the_config_directory(tmp_path):
    reg = tmp_path / "deep" / "nested" / "registry.toml"
    ft.write_registry_entry("claude", True, reg)
    assert reg.exists()
    assert ft.read_registry(reg) == {"claude": True}


def test_corrupt_registry_is_treated_as_absent(tmp_path):
    reg = tmp_path / "registry.toml"
    reg.write_text("this is = = not valid toml\n")
    assert ft.read_registry(reg) == {}


def test_hand_edited_correction_is_honored(tmp_path):
    reg = tmp_path / "registry.toml"
    ft.write_registry_entry("claude", True, reg)
    # the human corrects a misclassification by editing the one line
    reg.write_text(reg.read_text().replace('"claude" = true', '"claude" = false'))
    assert ft.read_registry(reg) == {"claude": False}


def test_keys_with_special_characters_roundtrip(tmp_path):
    reg = tmp_path / "registry.toml"
    ft.write_registry_entry("./script.sh", False, reg)
    assert ft.read_registry(reg) == {"./script.sh": False}
