#!/usr/bin/env bats
# Tests for .tooling/local-ci/version-bump.sh (the release driver's core).

load helpers

setup() { mk_derived_repo; }

@test "patch bump rewrites truth and target file" {
    write_bump_targets "1.2.3"
    run_version_bump patch
    [ "$status" -eq 0 ]
    grep -q '"1.2.4"' .tooling/bump-targets.yaml
    grep -q 'version=1.2.4' VERSION.txt
}

@test "minor bump zeroes patch" {
    write_bump_targets "1.2.3"
    run_version_bump minor
    [ "$status" -eq 0 ]
    grep -q '"1.3.0"' .tooling/bump-targets.yaml
}

@test "major bump zeroes minor and patch" {
    write_bump_targets "1.2.3"
    run_version_bump major
    [ "$status" -eq 0 ]
    grep -q '"2.0.0"' .tooling/bump-targets.yaml
}

@test "DRY_RUN leaves everything untouched" {
    write_bump_targets "1.2.3"
    run_version_bump patch 1
    [ "$status" -eq 0 ]
    grep -q '"1.2.3"' .tooling/bump-targets.yaml
    grep -q 'version=1.2.3' VERSION.txt
}

@test "invalid LEVEL is rejected" {
    write_bump_targets "1.2.3"
    run_version_bump banana
    [ "$status" -eq 2 ]
}

@test "malformed current_version is rejected" {
    write_bump_targets "not-a-version"
    run_version_bump patch
    [ "$status" -eq 2 ]
}

@test "missing target file is reported as a skip, not a crash" {
    write_bump_targets "1.2.3"
    rm VERSION.txt
    run_version_bump patch
    [ "$status" -eq 0 ]
    [[ "$output" == *"skip"* ]]
}

@test "bump accepts an unquoted current_version (init.py reset form)" {
    write_bump_targets "1.2.3"
    sed -i.bak 's/^current_version: "1.2.3"$/current_version: 1.2.3/' .tooling/bump-targets.yaml
    run_version_bump patch
    [ "$status" -eq 0 ]
    grep -q "^current_version: 1.2.4$" .tooling/bump-targets.yaml
    grep -q 'version=1.2.4' VERSION.txt
}

@test "truth rewrite failure is loud, not a silent no-op" {
    write_bump_targets "1.2.3"
    # sabotage the truth line so the current_version rewrite cannot match,
    # while the version parse still reads 1.2.3 from the mangled line
    python3 - <<'PYEOF'
from pathlib import Path
p = Path(".tooling/bump-targets.yaml")
t = p.read_text().replace('current_version: "1.2.3"', 'current_version: "1.2.3" # trailing')
p.write_text(t)
PYEOF
    run_version_bump patch
    [ "$status" -ne 0 ]
}
