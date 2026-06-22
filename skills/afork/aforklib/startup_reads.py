"""Startup-reads composer — the block that tells a forked role which minimum
context to read before its task.

A forked role wakes into a thin task brief and could begin work without loading
the repo operating instructions, the shared role-memory guide, or its own
role-memory router — the failure this block prevents. afork prepends this block
after the identity preamble and before the role charter so every
definition-backed fork inherits the same startup-read contract without per-role
or per-brief boilerplate.

Pure function of the resolved role name plus the launched working repo: no
runtime-adapter knowledge. Router discovery checks the same-name role-memory
router first, then the seated ``-agent`` alias when the launched role id omits
that suffix. The prose tells the role to resolve every path against the launched
working repo and to report — not invent — any missing optional file. The
composed string is plain prose carried by the existing persona payload (which
already handles escaping).
"""

from pathlib import Path


def _router_candidates(role_name):
    candidates = [f"agents/memory/{role_name}/AGENTS.md"]
    if not role_name.endswith("-agent"):
        candidates.append(f"agents/memory/{role_name}-agent/AGENTS.md")
    return candidates


def resolve_role_memory_router(role_name, repo_root=None):
    """Return (router prose, resolved path or None) for the launched role.

    Same-name wins. If absent and the launched role id lacks ``-agent``, the
    seated alias is checked. Missing routers are reportable context gaps, not
    launch failures, so the returned prose tells the role what was checked.
    """
    candidates = _router_candidates(role_name)
    if repo_root is None:
        return f"`{candidates[0]}`", candidates[0]

    root = Path(repo_root)
    for rel_path in candidates:
        if (root / rel_path).is_file():
            return f"`{rel_path}`", rel_path

    if len(candidates) == 1:
        checked = f"`{candidates[0]}`"
    else:
        checked = f"`{candidates[0]}` and `{candidates[1]}`"
    prose = (f"look for {checked}; if no role-memory router is present, "
             "report the missing role router briefly")
    return prose, None


# The `{role_router}` substitution is the role's discovered role-memory router
# path or missing-router lookup prose. All paths are resolved by the role
# relative to the launched working repo (cwd); a missing optional file is a
# reportable gap, not a launch failure.
STARTUP_READS_BLOCK = """\
**[Required Startup Reads — prepended automatically by afork]**
Before the run-specific task, load the minimum startup context below. Resolve
every path relative to the launched working repo (cwd), and read each one when
it is present:

1. The root repo operating instructions: `AGENTS.md`.
2. The agents-folder instructions: `agents/AGENTS.md`.
3. The shared role-memory guide and shared-memory router: `agents/memory/AGENTS.md`.
4. Your own role-memory router: {role_router}.
5. Any sibling role-memory files that router points to and that are relevant to
   the task.
6. After the minimum startup reads, the task-relevant shared docs, ADRs, specs,
   QA artifacts, or todo entries your task references.

Also read any deeper agents-folder instruction file for an agent-tree surface
you later inspect or edit — read it then, for that surface; do not crawl every
nested `AGENTS.md` at startup.

If a listed optional file is missing, say so briefly and continue only when the
task can proceed without it. Do not invent memory content or assume the contents
of an absent router."""


def render_startup_reads(role_name, repo_root=None):
    """Return the startup-reads block for the resolved role name."""
    role_router, _ = resolve_role_memory_router(role_name, repo_root)
    return STARTUP_READS_BLOCK.replace("{role_router}", role_router)
