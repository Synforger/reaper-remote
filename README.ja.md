# personal-template

> 🇬🇧 English: [README.md](README.md)

> 個人公開リポジトリ用の **言語非依存テンプレート**。
> `_core/` (= 全派生共通の品質機構) を派生時に root へ昇格する形で、
> `task init` 1 発で派生プロジェクトの足場が完成する。

## このテンプレが提供するもの

| カテゴリ | 中身 |
|---|---|
| **ローカル CI 完結** | `task lint` / `task test:unit` / `task docs:check` で品質ガードが手元で全部走る (= GitHub Actions 課金ゼロ運用) |
| **匿名性ガード** | [guard-dispatcher](https://github.com/Synforger/guard-dispatcher) (= マシン全体の hooks 関所) が commit / push / PR 境界で個人名 / 業務識別子の混入を機械検出。 本 template は repo 固有 hook (= branch guard + gitleaks) だけを持つ |
| **secret ガード** | pre-commit hook に gitleaks 同梱、 API key / password / private key の流入を機械検出 |
| **docs 鮮度ガード** | md 内の path 参照 / `task` 名 / tree 図 / git conflict marker (4 軸) が実態と一致するか機械検証 |
| **toolchain 真値一元化** | `.tooling/versions.yaml` 1 file で host floor を集約、 `task doctor` で MISSING / TOO OLD / OK を診断、 `task lint:versions` で下流 config drift を検知 |
| **集約 security audit** | `task audit` で anon-scan + gitleaks 全履歴 + pip-audit + npm audit + cargo audit を 1 発実行、 不在 tool は skip |
| **per-layer clean** | `task clean LAYER=<layer>` で言語別 build artefact + cache を選択削除 (= python/node/rust/swift/kotlin/cs/docs/all) |
| **release driver** | `task release:cut LEVEL=patch\|minor\|major` で version bump + commit + tag + push を 1 発、 DRY_RUN=1 で plan 確認 |
| **公開 OSS 必須要件** | `SECURITY.md` / `ROADMAP.md` / `THIRD_PARTY_NOTICES.md` template 同梱、 後者は `task gen-notices` で自動生成 |
| **branch protection** | gh CLI で main 保護を 1 発設定 |
| **対話 personalization** | パッケージ名 / GitHub URL / バージョン等の placeholder を対話的に置換 |

派生プロジェクトは上記機構が全部入った状態でスタートできる。 派生実例 = [claude-code-statusline](https://github.com/Synforger/claude-code-statusline) 。

## なぜ local-first か (CI の位置づけ)

全 gate は手元のマシンでオフライン実行できる — runner 分数ゼロ、 fork でも動き、 CI の価格変更に影響されない。 public repo では薄い `ci.yml` が PR ごとに**同じ `task ci`** を再実行して status check の鏡になる (public は無料、 private では実行を拒否する)。 検査の実体を workflow file に実装することはない。

## Language policy

- `README.md` = 英語、 `README.ja.md` = 日本語 (= 冒頭相互リンク)
- ユーザー向け出力 (= `--help` / エラーメッセージ / CI 出力) = 英語
- コードコメント・内部設計メモ = 日本語可

## 使い方 (= 派生プロジェクト初期化、 4 step)

```bash
# 1. このテンプレを「Use this template」 で新 repo 作成 → clone
gh repo create synforger/<new-project> --template synforger/personal-template --clone

# 2. テンプレ構造を root に展開 (= _core を昇格、 template 残骸を削除)
cd <new-project>
task init

# 3. パッケージ名 / GitHub URL / バージョン等を対話設定
pip install -r setup-requirements.txt
python personalize.py

# 4. 開発依存 install + git hooks 配備
task setup
```

派生後の構造・運用は [`_core/docs/internals/template-usage.md`](_core/docs/internals/template-usage.md) を参照 (= このファイルは `task init` で削除される)。

## 構造 (= template state)

```
personal-template/
├── README.md                     # このファイル (= template 状態の入口)
├── Taskfile.yml                  # init / install:core (= 派生時に _core/Taskfile.yml で上書き)
├── _core/                        # 言語非依存の共通機構 (全派生で root に昇格)
│   ├── _README.md
│   ├── .gitignore / .vscode/
│   ├── Taskfile.yml              # core task 定義 (= 派生後 root Taskfile.yml になる)
│   ├── .githooks/pre-commit      # repo-local hook (= branch guard + gitleaks、 anon baseline は
│   │                             #   guard-dispatcher が AND 実行)
│   ├── .github/
│   │   ├── ISSUE_TEMPLATE/
│   │   └── workflows/version-bump.yml
│   ├── .tooling/local-ci/        # docs-check / doctor / audit / clean / lint-versions /
│   │                             #   version-bump / release-cut / setup-lib (= anon 系 scanner
│   │                             #   は guard-dispatcher 所管)
│   ├── docs/                     # 利用者/contributor 2 層構造 placeholder
│   ├── scripts/                  # init.py / install-core.sh /
│   │                             #   post-init-github-settings.sh / setup-branch-protection.sh /
│   │                             #   gen-third-party-notices.py
│   ├── personalize.py
│   └── setup-requirements.txt


## 言語 scaffolding は同梱しない

本テンプレは言語非依存の品質機構だけを配る。 `task setup / lint / test:unit / test:integration / build / run` は stub として置かれ、 派生後に自分の stack の実 command で埋める (= 別 file にしたい場合は `Taskfile.local.yml` が include される)。 全派生 repo が同じ動詞に応答する統一だけを規約として持つ。


## 設計思想

- **構造美の徹底** — 全派生 repo で task 動詞 / file 配置を完全対称化
- **機能保存** — 既存 personal-template の機構は basically 全部温存、 削除は真に不要なもの (= Sphinx) のみ
- **追加 cost 最小** — stack 追加は Taskfile stub を埋める + versions.yaml 1 行だけ
- **言語非依存 core** — anon / docs-check / pre-commit / GitHub workflow / branch protection は全部 `_core/` で共通化

## Tests

テンプレ自身の機構は bats で機械検証している:

```sh
brew install bats-core   # 初回のみ
task test:template       # or: bats tests/
```

## License

Apache-2.0 (= [`LICENSE`](LICENSE))
