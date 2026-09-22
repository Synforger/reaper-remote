# `_core/` — 言語非依存の共通機構

派生プロジェクトで**言語を問わず全部入る**機構の置き場。 `task init` 実行時に中身が repo root に昇格し、 `_core/` 自体は削除される。

## ここに入っているもの

- **`Taskfile.yml`** — core task 群 (= setup / lint / test / build / docs:check / doctor / lint:versions / gen-notices / audit / clean / version:bump / release:cut 等の言語非依存 wrapper)
- **`.tooling/versions.yaml`** — toolchain 真値 (= host / stack / shared build の floor バージョン、 アルファベット順)
- **`.tooling/bump-targets.yaml`** — project version の真値 (= `current_version`) + bump 時に rewrite する file 一覧 (= 派生後に自分の version file を登録)
- **`.tooling/local-ci/`** — anon-scan.sh / docs-check.sh / doctor.sh / lint-versions.sh / clean.sh / audit.sh / version-bump.sh / release-cut.sh / setup-lib.sh + setup-lib.ps1 (= bash / PowerShell 共通プリミティブ) / 関連 ignore リスト
- **`.githooks/pre-commit`** — main/develop 直 commit guard + anon-scan + gitleaks secret scan
- **`.github/`** — ISSUE_TEMPLATE 3 種 + workflows (= anon-check / version-bump)
- **`scripts/`** — setup-branch-protection.sh / init.py / gen-third-party-notices.py / post-init-github-settings.sh / install-core.sh
- **`docs/`** — 利用者/contributor 2 層構造 (= README + setup/ + troubleshooting/ + reference/ + internals/)
- **`SECURITY.md`** — vulnerability 報告手順 + threat model + audit log template
- **`ROADMAP.md`** — 利用者向け「使える / 開発中 / 採用しない」 一覧 template
- **`THIRD_PARTY_NOTICES.md`** — OSS dep snapshot (= `task gen-notices` で自動生成)
- **`personalize.py`** — パッケージ名 / GitHub URL 等の対話 rename
- **`setup-requirements.txt`** — personalize.py の依存 (click + rich)
- **`.gitignore`** — 共通 ignore (= anon-words.txt + 一般的 build artifact)
- **`.vscode/`** — editor 設定

## ここに置く判断

「派生 repo の言語が何であっても入る」 もののみ置く (= 言語固有物は派生側の責務)。

例:
- pre-commit hook → core (= 言語によらず必要)
- anon-scan → core (= 言語によらず必要)
- pyproject.toml → python stack 固有 (= Python でしか使わない)
- Cargo.toml → rust stack 固有 (= Rust でしか使わない)

**stack 対応は実在する repo が現れた時に足す** (= audit section / versions floor / clean layer の種類先回り追加禁止、 使う日が来たら git history から 1 commit で復活)
