# Follow-Up Review & Fix — Round {{ROUND_NUMBER}}

You fixed these issues in the previous round:

<previous_findings_and_fixes>
{{PREVIOUS_FINDINGS}}
</previous_findings_and_fixes>

## What to review

Run `{{DIFF_COMMAND}}` to see the current state of changes. Stay scoped to the same diff as Round 1 — do not expand to unstaged or unrelated files.

## Instructions

Review the changed code again. Look for:
1. Any HIGH or MEDIUM issues that still remain after your previous fixes
2. Any NEW issues introduced by those fixes
3. Any additional LOW issues you notice

{{SEVERITY_CATEGORIES}}

**Fix all HIGH and MEDIUM issues directly in the code.** Do NOT fix LOW issues — only report them.

After fixing:
- If you ran `git diff --cached`: run `git add <files you edited>` to re-stage your changes.
- If you ran `git diff <branch>...HEAD`: run `git commit -am "judgy fixes"` to commit your changes.
- If you ran `git diff HEAD`: no extra step needed.

Do NOT invoke any skills, plugins, or external tools beyond reading and editing files and running the diff command.

## Output Format

{{FIXED_FORMAT}}
