# Purpose

Execute a raw CLI command.

## Instructions

- Before executing the command, run `<command> --help` to understand the command and its options.
- If the user gives an exact shell alias or launcher command, preserve it verbatim instead of normalizing it to the underlying binary.
- If the command depends on aliases, shell functions, or shell startup files, wrap it in an interactive login shell, for example `zsh -lic 'cx'`.
