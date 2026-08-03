# setup-repo-safety.ps1
# Purpose: Apply repo-local Codex safety files without clobbering existing repo
# configuration. Run inside the target Git repository.

$ErrorActionPreference = "Stop"

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Error "$Name is not installed or not available in PATH."
        exit 1
    }
}

function Backup-File {
    param([string]$Path)
    if (Test-Path $Path) {
        $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $backupPath = "$Path.bak.$timestamp"
        Copy-Item -LiteralPath $Path -Destination $backupPath
        return $backupPath
    }
    return $null
}

function Write-Utf8NoBom {
    param(
        [string]$Path,
        [string]$Content
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Add-Utf8NoBom {
    param(
        [string]$Path,
        [string]$Content
    )

    $existing = ""
    if (Test-Path $Path) {
        $existing = Get-Content -LiteralPath $Path -Raw
    }
    Write-Utf8NoBom -Path $Path -Content ($existing + $Content)
}

function Add-Block-IfMissing {
    param(
        [string]$Path,
        [string]$Marker,
        [string]$Block
    )

    if (Test-Path $Path) {
        $existing = Get-Content -LiteralPath $Path -Raw
        if ($existing -notmatch [regex]::Escape($Marker)) {
            if ($existing.Length -gt 0 -and -not $existing.EndsWith("`n")) {
                Add-Utf8NoBom -Path $Path -Content "`n"
            }
            Add-Utf8NoBom -Path $Path -Content "$Block`n"
        }
    } else {
        Write-Utf8NoBom -Path $Path -Content $Block.TrimStart()
    }
}

Require-Command "git"

$repoRoot = git rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repoRoot)) {
    Write-Error "This is not a Git repository. Run inside the target repo."
    exit 1
}

Set-Location $repoRoot

$codexDir = Join-Path $repoRoot ".codex"
$rulesDir = Join-Path $codexDir "rules"
$repoRulesPath = Join-Path $rulesDir "repo.rules"
$agentsPath = Join-Path $repoRoot "AGENTS.md"
$readmePath = Join-Path $repoRoot "README.md"
$gitignorePath = Join-Path $repoRoot ".gitignore"
$precommitPath = Join-Path $repoRoot ".pre-commit-config.yaml"
$baselinePath = Join-Path $repoRoot ".secrets.baseline"

New-Item -ItemType Directory -Force -Path $rulesDir | Out-Null

$gitignoreBlock = @"

# --- Codex safety ignore block ---
.venv/
venv/
.env
.env.*
*.pem
*.key
*.token
*.secret
__pycache__/
*.pyc
.cache/
.ipynb_checkpoints/
.codex/
.pre-commit-config.yaml
AGENTS.md
setup-repo-safety.ps1
PLAN.md
TODO.md
docs/PLAN.md
docs/TODO.md
# --- End Codex safety ignore block ---
"@

Add-Block-IfMissing -Path $gitignorePath -Marker "Codex safety ignore block" -Block $gitignoreBlock

@"
# Repo-local Codex safety rules
#
# Codex evaluates each safely separable command in a shell script independently.
# Rules under this project layer apply only after this repository is trusted and
# Codex is restarted. `match` entries are load-time tests for each command rule.

# PowerShell filesystem deletion cmdlet and its aliases.
prefix_rule(
    pattern = ["Remove-Item"],
    decision = "forbidden",
    justification = "Repository deletion is forbidden. Ask the user to run it manually.",
    match = ["Remove-Item -LiteralPath data", "Remove-Item -Recurse temp"],
)

prefix_rule(
    pattern = ["ri"],
    decision = "forbidden",
    justification = "Repository deletion is forbidden. Ask the user to run it manually.",
    match = ["ri -Force file.txt"],
)

# PowerShell aliases that can delete files or directories; these also cover the
# equivalent cmd.exe/POSIX spellings when invoked through a shell.
prefix_rule(
    pattern = ["rm"],
    decision = "forbidden",
    justification = "Repository deletion is forbidden. Ask the user to run it manually.",
    match = ["rm -r generated"],
)

prefix_rule(
    pattern = ["rmdir"],
    decision = "forbidden",
    justification = "Repository deletion is forbidden. Ask the user to run it manually.",
    match = ["rmdir cache"],
)

prefix_rule(
    pattern = ["rd"],
    decision = "forbidden",
    justification = "Repository deletion is forbidden. Ask the user to run it manually.",
    match = ["rd cache"],
)

prefix_rule(
    pattern = ["del"],
    decision = "forbidden",
    justification = "Repository deletion is forbidden. Ask the user to run it manually.",
    match = ["del output.txt"],
)

prefix_rule(
    pattern = ["erase"],
    decision = "forbidden",
    justification = "Repository deletion is forbidden. Ask the user to run it manually.",
    match = ["erase output.txt"],
)

# Other PowerShell commands that erase repository content or properties.
prefix_rule(
    pattern = ["Clear-Content"],
    decision = "forbidden",
    justification = "Erasing repository file content is forbidden. Ask the user to run it manually.",
    match = ["Clear-Content notes.txt"],
)

prefix_rule(
    pattern = ["Remove-ItemProperty"],
    decision = "forbidden",
    justification = "Removing repository item properties is forbidden. Ask the user to run it manually.",
    match = ["Remove-ItemProperty -Path item -Name property"],
)

prefix_rule(
    pattern = ["Clear-RecycleBin"],
    decision = "forbidden",
    justification = "Permanently clearing the recycle bin is forbidden. Ask the user to run it manually.",
    match = ["Clear-RecycleBin -Force"],
)

prefix_rule(
    pattern = ["git", "reset"],
    decision = "forbidden",
    justification = "git reset can discard local work.",
)

prefix_rule(
    pattern = ["git", "clean"],
    decision = "forbidden",
    justification = "git clean deletes untracked files.",
)

prefix_rule(
    pattern = ["git", "push", "--force"],
    decision = "forbidden",
    justification = "Force push rewrites remote history.",
)

prefix_rule(
    pattern = ["git", "push", "-f"],
    decision = "forbidden",
    justification = "Force push rewrites remote history.",
)
"@ | ForEach-Object { Write-Utf8NoBom -Path $repoRulesPath -Content $_ }

$agentsBlock = @'

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
'@

Add-Block-IfMissing -Path $agentsPath -Marker "BEGIN CODEX SAFETY HARNESS" -Block $agentsBlock

if (-not (Test-Path $readmePath)) {
    $repoName = Split-Path -Leaf $repoRoot
    $readmeTemplate = @'
# {{REPO_NAME}}

Project one-line description.

## Repository Structure

```text
.
```

## Installation

```bash
# Add installation steps here.
```

## Usage

```bash
# Add run commands here.
```

## Important Paths

- `docs/`: Project documentation.

## References

- `AGENTS.md`: Repository instructions for Codex.
'@
    Write-Utf8NoBom -Path $readmePath -Content ($readmeTemplate.Replace("{{REPO_NAME}}", $repoName))
}

$createdPrecommit = $false
if (-not (Test-Path $precommitPath)) {
    @"
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: ["--baseline", ".secrets.baseline"]
"@ | ForEach-Object { Write-Utf8NoBom -Path $precommitPath -Content $_ }
    $createdPrecommit = $true
} else {
    Write-Host ".pre-commit-config.yaml already exists; left unchanged."
    Write-Host "Add detect-secrets manually if this repository should enforce secret scanning."
}

if ((Get-Command detect-secrets -ErrorAction SilentlyContinue) -and -not (Test-Path $baselinePath)) {
    detect-secrets scan --baseline $baselinePath
} elseif (-not (Get-Command detect-secrets -ErrorAction SilentlyContinue)) {
    Write-Host "detect-secrets not found; skipped baseline generation."
}

if (Get-Command pre-commit -ErrorAction SilentlyContinue) {
    pre-commit install
} else {
    Write-Host "pre-commit not found; skipped hook installation."
    Write-Host "Install it separately, then run: pre-commit install"
}

if (Get-Command codex -ErrorAction SilentlyContinue) {
    codex execpolicy check --rules $repoRulesPath -- rm -rf codex-safety-smoke-test | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Codex exec policy check failed."
        exit $LASTEXITCODE
    }
}

Write-Host "Repo safety files prepared at:"
Write-Host "  $gitignorePath"
Write-Host "  $agentsPath"
Write-Host "  $repoRulesPath"
if ($createdPrecommit) { Write-Host "  $precommitPath" }
if (Test-Path $baselinePath) { Write-Host "  $baselinePath" }
Write-Host ""
Write-Host "Current repo status:"
git status --short
