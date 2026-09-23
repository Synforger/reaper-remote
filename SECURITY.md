# Security Policy

## Reporting a vulnerability

Use **GitHub Security Advisories private vulnerability reporting** to
disclose security issues responsibly:

1. Open https://github.com/Synforger/reaper-remote/security/advisories/new
2. Fill in the affected version + reproduction + impact estimate
3. Maintainer will acknowledge within 7 days

Do not file public Issues or PRs for security-relevant findings. Public
discussion only after a fix has shipped and end users have had time to
update.

If GitHub access is unavailable, open a GitHub issue asking for a private
contact channel, without details of the finding.

## Supported versions

| version | supported |
|---|---|
| main (= rolling release) | ✅ active |
| tagged releases (= v0.x) | ⚠️ best effort (= no formal LTS) |
| forks / mirrors | ❌ out of scope |

This is a personal project; there is no enterprise LTS. Security fixes
land on `main` and the next tagged release. Pin to a specific tag if
your environment requires reproducibility.

## Threat model

reaper-remote runs on a single user's Mac and is reached from that user's
own devices over their tailnet.

- The server has **no authentication of its own**. It binds to loopback
  (`127.0.0.1`) by default, and access is granted by whoever can reach it
  through `tailscale serve` — i.e. the members of the tailnet. Anyone who
  can open the page can control REAPER, hear the Mac's output, switch the
  Mac's output device and trigger renders.
- Binding to a non-loopback `host` exposes all of that to the network
  without authentication. Do not do it on a network you do not control.
- REAPER's own web interface (default port 8080) also has no authentication
  unless you set one, and listens on all interfaces. reaper-remote only needs
  it on loopback.
- Commands sent to `/reaper/_/` are passed to REAPER unchanged; the server
  does not filter them. Rendered files are served only from `render.dir`.

## In scope

- Authentication / authorization flaws (= when applicable)
- Sensitive data leakage (= secrets in logs / errors / responses)
- Path traversal / SSRF / XSS / RCE in the server or the UI
- Dependency vulnerabilities surfaced by `task audit`

## Out of scope

- Issues in upstream dependencies that are already disclosed
  (= report those upstream; this repo will pick up the fix on next bump)
- Best-practice nudges with no concrete exploit path
- Vulnerabilities only reproducible with privileged local access
  (= `sudo` / root) — those imply the threat model has already failed
- Cosmetic / DoS-via-resource-exhaustion in dev-mode tools

## Audit log

The maintainer runs `task audit` (= `pip-audit` + `npm audit` +
`cargo audit` + `gitleaks` + `anon-scan` aggregated) at least every
6 months. Findings + resolutions are tracked here:

| date | findings | resolution |
|---|---|---|
| 2026-09-23 | (initial) | repository created |

## Upstream redirect

When a vulnerability originates in a transitive dependency, the
disclosure goes to the upstream maintainer first. This repo only
contains the integration layer; the offending logic lives elsewhere
and should be patched there.
