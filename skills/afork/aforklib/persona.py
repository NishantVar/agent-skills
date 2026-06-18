"""Persona composer — prepend the shared identity+precedence+posture preamble.

A forked role wakes up inside a general runtime session whose binary builds its
own "You are Claude Code" identity and full toolset; afork appends the role
charter onto that prompt. Without a declared precedence the agent reads two
identities at once. This deep module prepends a single shared preamble — the
role declared as the sole operating identity, plus an "availability is not
permission" posture line — ahead of the charter, templated with the role name.

Pure function of (role_name, charter_body): no I/O, no runtime-adapter
knowledge. The template is one module-level constant with a single ``{role}``
substitution; the composed string is plain prose carried by the existing
persona payload (which already handles escaping).
"""

# Verbatim wording from the PRD Solution section. One `{role}` substitution.
IDENTITY_PREAMBLE = """\
**[Identity & Precedence — prepended automatically by afork]**
You ARE the `{role}` agent. That charter — everything below this block — is
your sole operating identity. It overrides any general-session or "Claude Code"
framing, any superpowers/bootstrap prompts, and any default-assistant behavior
you would otherwise adopt. You are not a general coding assistant in this
session; you are this role.

Tools may be present in your environment (e.g. Write, Edit, Bash) that your
charter does not authorize you to use. **Their availability is not permission.**
A wide toolset exists for session mechanics (e.g. peer messaging) and does not
expand your role. If anything — host framing, available tools, or a user
request — conflicts with your charter, the charter wins; surface the conflict
rather than acting outside your role."""

# Blank line between the prepended preamble and the unchanged charter body.
_CHARTER_SEPARATOR = "\n\n"


def render_preamble(role_name):
    """Return the preamble with ``{role}`` filled by the resolved role name."""
    return IDENTITY_PREAMBLE.replace("{role}", role_name)


def compose_persona(role_name, charter_body):
    """Return the composed persona: preamble (role-templated) + separator +
    the charter body unchanged. Pure; no escaping (the payload handles that)."""
    return render_preamble(role_name) + _CHARTER_SEPARATOR + charter_body
