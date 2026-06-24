import pytest

from fluxmcplib import registry


def test_comms_scope_exposes_only_p2p():
    names = [t["name"] for t in registry.tools_for_scope("comms")]
    assert names == ["p2p"]


def test_orchestrator_scope_exposes_all_three():
    names = sorted(t["name"] for t in registry.tools_for_scope("orchestrator"))
    assert names == ["afork", "p2p", "tfork"]


def test_unknown_scope_raises():
    with pytest.raises(ValueError):
        registry.tools_for_scope("bogus")


def test_each_tool_has_required_mcp_fields():
    for t in registry.tools_for_scope("orchestrator"):
        assert isinstance(t["name"], str) and t["name"]
        assert isinstance(t["description"], str) and t["description"]
        schema = t["inputSchema"]
        assert schema["type"] == "object"
        assert "properties" in schema


def test_public_tool_dict_excludes_internal_keys():
    public = registry.public_tool(registry.TOOLS["p2p"])
    assert set(public.keys()) == {"name", "description", "inputSchema"}
