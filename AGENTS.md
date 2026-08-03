<!-- BEGIN CODEX SAFETY HARNESS -->
# Codex Repository Instructions

## Safety Rules

- Treat uncommitted user changes as user-owned work. Do not overwrite, reset, delete, or move them unless the user explicitly asks.
- Do not run destructive Git commands such as `git reset`, `git clean`, or force pushes unless the user explicitly asks for that exact operation.
- Do not delete files or directories unless the user explicitly asks for deletion.
- Treat every `.env` and `.env.*` file as opaque secret material. Never open, read, search, print, diff, or otherwise inspect its contents with any tool. File-name or existence checks and moving the file without reading it are allowed. This does not apply to `config.example.env` files that contain only placeholder values.
- Do not make adjacent or follow-on edits unless the user explicitly asks for them, even when they would naturally fit the current context.
- Before changing dependencies, package manager lockfiles, generated files, migrations, or broad formatting, state the reason and keep the change scoped to the task.
- Prefer repository-local commands and documented project workflows over global tools.
- Run focused validation after edits when the repository provides a clear test, lint, typecheck, or build command. Report any validation that could not be run.

## Planning Document Rules

- Use `docs/TODO.md` and `docs/PLAN.md` to track follow-up work that comes up during user conversations.
- When a requested change involves multiple steps or more than a trivial edit, classify the work before or while making the change.
- Use `docs/TODO.md` for small maintenance items that do not block the system from running but should be fixed eventually. Examples include one- or two-file hotfixes, path cleanup such as converting absolute paths to relative paths, or verifying whether local dataset files match server-generated outputs.
- Use `docs/PLAN.md` for broader work, especially when the user gives an abstract request such as adding a feature without naming the exact files or implementation details.
- When changing non-documentation files, check whether the work is already reflected in `docs/TODO.md` or `docs/PLAN.md`, and update the appropriate document if it is not.
- Keep both planning documents current by removing completed items instead of letting finished work accumulate.

## Commit Message Rules

Use these rules when proposing commit messages:

- Initial commit: `init: Initialize with <file names>`
- New files or directories: `add: Add <file or directory names>`
- Fixes or updates to existing files: `fix: Fix <file or directory name>`
- Structure or location changes: `refactor: <target> <one-sentence purpose>`

Keep commit messages concise and match the dominant change type.
<!-- END CODEX SAFETY HARNESS -->
