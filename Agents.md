# AGENTS.md

Version: 2.2 — 2026-09

## Objective

Complete the current task correctly with the minimum sufficient context, smallest safe change, and fewest speculative retries.

These are efficiency defaults. Explicit current-task instructions and more-specific applicable project instructions take precedence.

## 1. Search, then read

Locate the likely relevant area first using repository search, symbols/references, filenames, routes, errors, or distinctive text.

For an unfamiliar repository, inspect only the small amount of structure or metadata needed to orient yourself.

Read enough context to act reliably, but do not scan the whole repository by default.

SEARCH -> READ ENOUGH -> EDIT MINIMALLY -> VERIFY

## 2. Default change constraints

Unless the current task explicitly requires otherwise:

- Do not change the database schema.
- Do not add new dependencies.
- Do not change public APIs, contracts, or external behavior.
- Do not change authentication or authorization behavior.
- Do not perform broad refactors.
- Do not change unrelated behavior.
- Do not modify unrelated files.
- Do not introduce new architecture when the existing structure can reasonably support the task.

If the task explicitly requires one of these changes, make only the minimum necessary change.

## 3. Stay in scope

- Do only what the task requires.
- Do not add unrelated features, cleanup, or refactors.
- Report unrelated issues instead of fixing them.

## 4. Protect existing work

When useful, inspect repository state and diffs before editing.

- Do not overwrite or revert unrelated user changes.
- Distinguish your edits from pre-existing changes.
- When relevant, determine whether a failing check already failed before your change.

## 5. Make the smallest safe change

Prefer focused, local, reversible edits.

Avoid touching unrelated files or rewriting a whole file when a smaller edit is sufficient.

## 6. Verify proportionally

Use actual project checks instead of guessing about correctness.

Start with the smallest meaningful check, then broaden only when risk or project rules justify it.

Examples: targeted test, lint, typecheck, build, relevant integration test.

Always run mandatory checks defined by applicable project instructions.

Fix only failures caused by or directly related to the current task unless asked otherwise.

## 7. Desktop app build rule

For desktop app projects that provide `Build.bat`, run `Build.bat` from the project root before reporting a coding task as complete when the task involved code, UI, config, launcher, packaging, versioning, or app behavior changes.

Reason: `Build.bat` updates the runnable desktop app so the user can usually refresh the app instead of running `STOP.bat` and `START.bat` after each coding task.

During implementation, do not run `Build.bat` after every tiny intermediate edit. Run it once when the task is ready to verify, unless an earlier build is needed for debugging.

If `Build.bat` fails, do not report completion. Fix only issues related to the current task, then rerun the relevant check.

If the task touches launcher, packaging, versioning, desktop shortcut, icon, Windows App Mode, or build behavior, first look for and read the project build documentation, such as `TinixBuild.md`, `Build.md`, `BUILD.md`, `Packaging.md`, or an equivalent project-specific build spec.

Commit rule:

- Do not create Git commits automatically.
- Commit only when the user explicitly requests it.
- When the user requests a commit, create one clear commit for the completed task.
- Do not create multiple commits unless explicitly requested.

Final report for coding tasks must include:

- what changed
- files changed
- `Build.bat` result, if applicable
- tests/lint result, if run
- remaining issue, if any
- note that Git commit was not created unless explicitly requested

## 8. Debug from evidence

Use errors, failing tests, logs, diffs, and reproducible behavior as evidence.

Do not repeatedly make speculative fixes.

If two materially different speculative fixes fail, stop editing and summarize:

1. current failure
2. evidence
3. attempts and results
4. likely root causes
5. relevant files
6. recommended next diagnostic step or escalation

If a failed attempt produces clear new evidence, continue from that evidence; this is not a blind retry.

## 9. Plan only when useful

For broad, high-risk, or multi-system changes, make a short plan first.

For small, obvious tasks, implement directly without spending tokens on a formal plan.

## 10. Delegate sparingly

Do not create subagents or delegated workers by default.

Delegate only genuinely separable work where each worker can use a smaller focused context. Avoid duplicating the same large repository context across workers.

## 11. Keep output concise

Do not restate unchanged code or explain routine edits at length.

At completion, report only the required result, verification, and remaining issues.

## 12. Preserve only durable knowledge

Update existing project documentation after major milestones only when important decisions or state must persist.

Do not create status documents or summaries automatically for every task.
