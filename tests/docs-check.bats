#!/usr/bin/env bats
# Tests for .tooling/local-ci/docs-check.sh (docs freshness guard).

load helpers

setup() { mk_derived_repo; }

commit_docs() {
    git add -A
    git commit -q -m "docs fixture"
}

@test "clean docs pass" {
    mkdir -p src
    echo "x" > src/real-file.txt
    echo 'See `src/real-file.txt` for details.' > README.md
    commit_docs
    run_docs_check
    [ "$status" -eq 0 ]
}

@test "dead inline path reference fails (axis A)" {
    echo 'See `src/gone.py` for details.' > README.md
    commit_docs
    run_docs_check
    [ "$status" -ne 0 ]
}

@test "git conflict marker in docs fails (axis G)" {
    printf 'intro\n<<<<<<< HEAD\nours\n>>>>>>> theirs\n' > README.md
    commit_docs
    run_docs_check
    [ "$status" -ne 0 ]
}

@test "tree diagram with existing entries passes (axis C)" {
    mkdir -p docs/setup
    echo "x" > docs/guide.md
    printf '```\ndocs/\n├── setup/\n└── guide.md\n```\n' > README.md
    commit_docs
    run_docs_check
    [ "$status" -eq 0 ]
}

@test "tree diagram with a dead entry fails (axis C)" {
    mkdir -p docs
    printf '```\ndocs/\n└── gone.md\n```\n' > README.md
    commit_docs
    run_docs_check
    [ "$status" -ne 0 ]
}

@test "composite tree line with all entries existing passes (axis C)" {
    mkdir -p docs/setup docs/reference
    echo "x" > docs/guide.md
    printf '```\ndocs/\n├── guide.md / setup/ / reference/\n└── setup/\n```\n' > README.md
    commit_docs
    run_docs_check
    [ "$status" -eq 0 ]
}

@test "composite tree line with a dead second entry fails (axis C)" {
    mkdir -p docs/setup
    echo "x" > docs/guide.md
    printf '```\ndocs/\n└── guide.md / gone/ / setup/\n```\n' > README.md
    commit_docs
    run_docs_check
    [ "$status" -ne 0 ]
    [[ "$output" == *"docs/gone"* ]]
}

@test "tree line with free-text annotation is not split as composite (axis C)" {
    mkdir -p docs
    echo "x" > docs/guide.md
    printf '```\ndocs/\n└── guide.md   ← overview / quick start notes\n```\n' > README.md
    commit_docs
    run_docs_check
    [ "$status" -eq 0 ]
}

@test "ignore file suppresses a flagged reference" {
    echo 'See `src/gone.py` for details.' > README.md
    echo 'src/gone.py' > .tooling/local-ci/docs-check-ignore.txt
    commit_docs
    run_docs_check
    [ "$status" -eq 0 ]
}
