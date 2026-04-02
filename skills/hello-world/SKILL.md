---
name: hello-world
description: >-
  A sample skill that demonstrates the cross-agent skill format.
  Use when the user asks for a greeting or to test that skills are working.
user-invocable: true
argument-hint: "[name]"
---

# Hello World

Greet the user with a friendly message and confirm this skill loaded successfully.

## Instructions

1. Say hello and mention which agent you're running in (Claude Code, Codex CLI, or Gemini CLI)
2. Confirm that the skill loaded correctly
3. If the user provided a name, personalize the greeting
