# Purpose

Create a new Gemini CLI agent to execute the command.

## Variables

DEFAULT_MODEL: gemini-3-pro-preview
HEAVY_MODEL: gemini-3-pro-preview
BASE_MODEL: gemini-3-pro-preview
FAST_MODEL: gemini-2.5-flash

## Instructions

- If the user provides an exact Gemini launcher command or alias, use it verbatim. Do not replace it with a hand-built `gemini ...` command.
- Before executing the command, run `gemini --help` to understand the command and its options, but only when you are constructing a direct `gemini` invocation yourself.
- Always use interactive mode with the -i flag as the last flag, right before the prompt (e.g., `gemini --model gemini-2.5-flash -y -i "prompt here"`)
- For the --model argument, use the DEFAULT_MODEL if not specified. If 'fast' is requested, use the FAST_MODEL. If 'heavy' is requested, use the HEAVY_MODEL.
- Always run with `--yolo` (or `-y` for short)
- If the chosen launcher relies on aliases, shell functions, or shell startup files, wrap it in an interactive login shell.
