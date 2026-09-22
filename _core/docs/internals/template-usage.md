# personal-template の使い方 (= 派生者向け、 init 後に削除される)

このファイルは `task init` 実行時に自動削除される。 派生 repo 作成直後の人が読む想定で書く。

## 派生フロー (= 4 step)

```bash
# 1. このテンプレを「Use this template」 で新 repo 作成 → clone
gh repo create synforger/<new-project> --template synforger/personal-template --clone

# 2. テンプレ構造を root に展開 (= _core を昇格、 template 残骸を削除)
cd <new-project>
task init

# 2a. (推奨) toolchain 診断 = `task doctor` で MISSING / TOO OLD / OK を確認
task doctor

# 3. パッケージ名 / GitHub URL / Python バージョン等を対話設定
pip install -r setup-requirements.txt
python personalize.py

# 4. 開発依存 install + git hooks 配備
task setup
```

## 構造 (= 派生 repo に残る分のみ)

```
<new-project>/
├── LICENSE / README.md / .gitignore
├── Taskfile.yml                 # setup / lint / test / docs:check / py:* 等
├── Taskfile.python.yml          # python 固有 task (= py: namespace)
├── pyproject.toml / pytest.ini / .flake8 / .coveragerc
├── pyinstaller.spec
├── src/my_package/              # Python source 雛形
├── tests/                       # pytest 骨格
├── docs/                        # 利用者/contributor 2 層構造
│   ├── README.md / setup/ / troubleshooting/ / reference/
│   └── internals/               # contributor 専用
├── personalize.py               # 派生時の対話 rename
├── scripts/setup-branch-protection.sh
├── .githooks/pre-commit         # main/develop guard + anon-scan
├── .tooling/
│   ├── local-ci/                # anon-scan.sh / docs-check.sh
│   └── os/<os>/python/          # OS 別の setup/lint/test/build/run スクリプト
└── .github/
    ├── ISSUE_TEMPLATE/
    └── workflows/anon-check.yml + version-bump.yml
```

## 言語選択 (= 現状)

`task init` は `_core/` の昇格 + version reset + template 残骸掃除を行う。 言語 scaffolding は同梱しないので、 昇格後に Taskfile の stack stub を埋める。

## GitHub settings 1 発復元

`task init:github` で template 化で引き継がれない GitHub settings (= secret scanning / PVR / merge config / branch protection) を gh CLI 経由で自動適用。 残 manual TODO (= Non-provider patterns / CodeQL UI) は script 末尾で URL 付き表示。

## back-port (= 既存 repo へのテンプレ機構持ち込み)

既存 repo に **後追い install** する手順:

```bash
cd REDACTED_PATH

# _core 機構一式
task install:core TARGET=REDACTED_PATH

```

衝突は `<name>.tmpl.orig` backup で残し、 上書きしない (= 手動 merge 用)。 詳細は [`install-to-existing.md`](install-to-existing.md) 参照。
