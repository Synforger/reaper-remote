# personal-template

> 🇯🇵 日本語版: [README.ja.md](README.ja.md)

A **language-neutral quality template** for public personal
repositories. `task init` promotes `_core/` (the quality machinery
shared by every derived project) to the repo root and your project
starts with the full toolchain below already wired.

Living example of a derived repository:
[claude-code-statusline](https://github.com/Synforger/claude-code-statusline).

## What you get

| category | contents |
|---|---|
| **Local-first CI** | `task lint` / `task test:unit` / `task docs:check` run every quality gate on your machine — zero GitHub Actions billing |
| **Anonymity guard** | [guard-dispatcher](https://github.com/Synforger/guard-dispatcher) (machine-wide hooks gate) machine-checks commits / pushes / PRs for identity leaks; this template ships only the repo-specific hook (branch guard + gitleaks) |
| **Secret guard** | gitleaks in the pre-commit hook catches API keys, passwords, private keys before they leave the working tree |
| **Docs freshness guard** | verifies that paths, `task` names, tree diagrams, and conflict markers inside your markdown match reality (4 axes) |
| **Toolchain single-source** | `.tooling/versions.yaml` holds the host floor; `task doctor` diagnoses MISSING / TOO OLD / OK, `task lint:versions` catches downstream config drift |
| **Aggregate security audit** | `task audit` runs anon-scan + gitleaks full history + pip-audit + npm audit + cargo audit in one pass, skipping absent tools |
| **Stack-aware clean** | `task clean` removes build artefacts + caches for whichever stacks are present |
| **Release driver** | `task release:cut LEVEL=patch\|minor\|major` bumps, commits, tags, and pushes in one command; `DRY_RUN=1` previews |
| **Public-OSS essentials** | `SECURITY.md` / `ROADMAP.md` / `THIRD_PARTY_NOTICES.md` templates included; the latter regenerates via `task gen-notices` |
| **Branch protection** | one command applies main-branch protection via the gh CLI |
| **Interactive personalization** | replaces package name / GitHub URL / version placeholders interactively |

## Usage (4 steps)

```bash
# 1. Create a new repo from this template, then clone it
gh repo create <owner>/<new-project> --template Synforger/personal-template --clone

# 2. Promote the template structure to the repo root
cd <new-project>
task init

# 3. Set package name / GitHub URL / version interactively
pip install -r setup-requirements.txt
python personalize.py

# 4. Install dev dependencies + arm the git hooks
task setup
```

See
[`_core/docs/internals/template-usage.md`](_core/docs/internals/template-usage.md)
for the post-init structure and workflow (the file is removed by
`task init`).

## No language scaffolding

This template ships quality machinery only. The stack verbs —
`task setup / lint / test:unit / test:integration / build / run` —
are stubs you fill in with your project's real commands after
deriving (a `Taskfile.local.yml` include is honoured if you prefer
keeping them separate). The contract is that every derived repo
answers to the same verbs; the implementation is yours.

## Why local-first (and where CI fits)

Every gate runs offline on the maintainer's machine — no runner
minutes, works in forks, and survives any CI pricing change. On public
repositories a thin `ci.yml` re-runs the exact same `task ci` on pull
requests as a status-check mirror (free on public repos, and it
refuses to run on private ones). The checks themselves are never
implemented in workflow files.

## Language policy

- `README.md` is English; `README.ja.md` is Japanese. Both link to
  each other at the top.
- User-facing output (`--help`, error messages, CI output) is
  English.
- Code comments and internal design notes may be Japanese.

## Structure (template state)

```
personal-template/
├── README.md / README.ja.md     # this file + Japanese counterpart
├── Taskfile.yml                 # init / install:core (overwritten by _core/Taskfile.yml on init)
├── _core/                       # language-neutral machinery, promoted to root on init
│   ├── Taskfile.yml             # core task definitions (becomes the root Taskfile.yml)
│   ├── .githooks/pre-commit     # repo-local hook (branch guard + gitleaks; the anon
│   │                            #   baseline runs in guard-dispatcher, AND-composed)
│   ├── .github/                 # ISSUE_TEMPLATE/ + workflows/version-bump.yml
│   ├── .tooling/local-ci/       # docs-check / doctor / audit / clean / lint-versions /
│   │                            #   version-bump / release-cut / setup-lib
│   ├── docs/                    # two-tier user/contributor docs placeholder
│   ├── scripts/                 # init.py / install-core.sh / post-init-github-settings.sh /
│   │                            #   setup-branch-protection.sh / gen-third-party-notices.py
│   ├── personalize.py
│   └── setup-requirements.txt
```

## Design principles

- **Structural symmetry** — every derived repo answers to the same
  task verbs and file layout
- **Minimal adoption cost** — adopting a stack means filling in the
  Taskfile stubs plus one line in versions.yaml
- **Language-neutral core** — docs-check, hooks, GitHub workflow,
  branch protection are all shared via `_core/`

## Tests

The template's own machinery is covered by a bats suite:

```sh
brew install bats-core   # once
task test:template       # or: bats tests/
```

Fixtures build throwaway repos under the test tmpdir — nothing in the
checkout is mutated.

## License

Apache-2.0 ([`LICENSE`](LICENSE))
