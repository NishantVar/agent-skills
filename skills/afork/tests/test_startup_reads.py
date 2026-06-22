"""Required Startup Reads composer — the isolated deep module that produces the
startup-read block prepended to a definition-backed fork's persona. External
behavior only (the composed prose), no internal wiring."""

from aforklib.startup_reads import render_startup_reads


def _role_router(repo, role):
    path = repo / "agents" / "memory" / role / "AGENTS.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {role}\n")
    return path


def test_names_own_role_memory_router_same_name():
    out = render_startup_reads("reviewer-agent")
    assert "agents/memory/reviewer-agent/AGENTS.md" in out


def test_names_repo_and_agents_folder_instructions():
    out = render_startup_reads("reviewer-agent")
    assert "`AGENTS.md`" in out
    assert "agents/AGENTS.md" in out


def test_names_shared_role_memory_guide_and_router():
    out = render_startup_reads("reviewer-agent")
    assert "agents/memory/AGENTS.md" in out


def test_role_substituted_no_placeholder_left():
    out = render_startup_reads("systems-designer-agent")
    assert "agents/memory/systems-designer-agent/AGENTS.md" in out
    assert "{role}" not in out


def test_hyphenated_role_id_flows_through_same_name():
    # The seated, hyphenated role id resolves same-name (no -agent alias this
    # slice): the router path mirrors the role id verbatim.
    out = render_startup_reads("runtime-integration-engineer-agent")
    assert "agents/memory/runtime-integration-engineer-agent/AGENTS.md" in out


def test_same_name_router_wins_when_present(tmp_path):
    _role_router(tmp_path, "reviewer")
    _role_router(tmp_path, "reviewer-agent")

    out = render_startup_reads("reviewer", repo_root=tmp_path)

    assert "agents/memory/reviewer/AGENTS.md" in out


def test_agent_suffix_alias_router_used_when_same_name_missing(tmp_path):
    _role_router(tmp_path, "runtime-integration-engineer-agent")

    out = render_startup_reads("runtime-integration-engineer", repo_root=tmp_path)

    assert "agents/memory/runtime-integration-engineer-agent/AGENTS.md" in out


def test_missing_router_tells_role_to_report_gap(tmp_path):
    out = render_startup_reads("bootstrap-adapter", repo_root=tmp_path)

    assert "agents/memory/bootstrap-adapter/AGENTS.md" in out
    assert "agents/memory/bootstrap-adapter-agent/AGENTS.md" in out
    assert "report the missing role router" in out
    assert "Do not invent memory content" in out


def test_includes_conditional_deeper_instruction_rule_without_crawl():
    out = render_startup_reads("reviewer-agent")
    # Deeper agents-tree instruction files are a conditional, per-surface rule...
    assert "inspect or edit" in out
    # ...explicitly NOT a launch-time crawl of every nested instruction file.
    assert "do not crawl every" in out


def test_instructs_report_missing_and_no_invention():
    out = render_startup_reads("reviewer-agent")
    assert "missing" in out
    assert "Do not invent memory content" in out


def test_paths_resolved_relative_to_working_repo():
    out = render_startup_reads("reviewer-agent")
    assert "relative to the launched working repo" in out
