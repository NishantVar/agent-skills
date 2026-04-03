# Follow-Up Code Review — Round {{ROUND_NUMBER}}

Previous round found these issues. The HIGH and MEDIUM ones have since been fixed by another agent:

<previous_findings>
{{PREVIOUS_FINDINGS}}
</previous_findings>

<fixes_applied>
{{FIXES_APPLIED}}
</fixes_applied>

## What to review

Run `{{DIFF_COMMAND}}` to see the current changes. Stay scoped to the same diff as Round 1 — do not expand to unstaged or unrelated files.

## Instructions

Review the changed code again. Look for:
1. Any HIGH or MEDIUM issues that still remain after the fixes
2. Any NEW issues introduced by the fixes
3. Any additional LOW issues you notice

{{SEVERITY_CATEGORIES}}

Do NOT modify any files. Only report what you find. Do NOT invoke any skills, plugins, or external tools beyond reading files and running the diff command.

## Output Format

{{GUIDANCE_FORMAT}}

If no high/medium issues found:
JUDGY_REPORT_START
NO_ISSUES_FOUND
- [LOW] description — file:line
JUDGY_REPORT_END
