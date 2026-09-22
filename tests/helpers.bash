# Shared fixtures for the personal-template test suite.
#
# Each test builds a throwaway derived-repo layout under $BATS_TEST_TMPDIR
# with the scripts under test copied in, so nothing in this checkout is
# mutated and the suite runs identically anywhere.

TEMPLATE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# mk_derived_repo — create a minimal post-init repo layout and cd into it.
mk_derived_repo() {
    local dir="${BATS_TEST_TMPDIR}/derived-${RANDOM}"
    mkdir -p "${dir}/.tooling/local-ci"
    cp "${TEMPLATE_ROOT}/_core/.tooling/local-ci/setup-lib.sh" \
       "${TEMPLATE_ROOT}/_core/.tooling/local-ci/version-bump.sh" \
       "${TEMPLATE_ROOT}/_core/.tooling/local-ci/docs-check.sh" \
       "${dir}/.tooling/local-ci/"
    touch "${dir}/.tooling/local-ci/docs-check-ignore.txt"
    cd "${dir}" || return 1
    git init -q .
    git config user.email "fixture@example.com"
    git config user.name "Fixture"
    git config commit.gpgsign false
    git config core.hooksPath /dev/null
}

# write_bump_targets <version> — minimal bump-targets.yaml with one target.
write_bump_targets() {
    local version="$1"
    cat > .tooling/bump-targets.yaml <<EOF
current_version: "${version}"

targets:
  - file: VERSION.txt
    replacements:
      - search: 'version={OLD}'
        replace: 'version={NEW}'
EOF
    echo "version=${version}" > VERSION.txt
}

run_version_bump() { run env LEVEL="${1:-patch}" DRY_RUN="${2:-0}" bash .tooling/local-ci/version-bump.sh; }
run_docs_check()   { run bash .tooling/local-ci/docs-check.sh; }
