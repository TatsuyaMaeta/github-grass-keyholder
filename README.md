# GitHub草キーホルダー

GitHubのコントリビューショングラフ（草）を、3Dプリントできる積層式キーホルダーに変換するツールです。直近54週分（27週 × 2枚）のコントリビューションを取得し、色ごとに単色で印刷できる層に分けたSTL/3MFを生成します。4色までのプリンタでも組み立てて多色に見せられる構成になっています。

## できること

- GitHub GraphQL APIから、指定した開始週を基準に54週分のコントリビューションデータを取得
- 半年ずつ2枚（1枚27週 × 7日）のグリッドに分割し、レベル（L0〜L4）ごとに単色の層を生成
- 白の天板に月のラベル（Jan〜Dec）を貫通くり抜き、各層の裏に組み立て順マークを刻印
- 最下層の裏面にユーザー名などを刻印
- デスクトップアプリ（pywebview）でプレビューしながらパラメータ調整・STL/3MF書き出し
- CLIでも同じ処理を実行可能（自動化・再生成向け）

## 必要なもの

- Python 3.11
- GitHubのアクセストークン（`GITHUB_TOKEN`環境変数、`gh auth token`、またはアプリ内でキーチェーンに保存）
  - classicトークンは `read:user` スコープ、fine-grainedトークンはスコープ不要（公開分のみ）
  - 非公開リポジトリの分も含めたい場合は、GitHubのプロフィール設定で「Include private contributions on my profile」を有効にする

## セットアップ

```zsh
python3.11 -m venv venv
venv/bin/pip install numpy manifold3d matplotlib truststore pywebview keyring
```

## 使い方

### デスクトップアプリ

```zsh
venv/bin/python -m app
```

`草キーホルダー.command` をダブルクリックしても起動します。GitHubユーザー名を入力して「取得」→プレビューを確認しながら寸法・色・刻印を調整→「STL / 3MFを書き出す」で完了です。

### CLI

```zsh
venv/bin/python grass_keychain.py <GitHubユーザー名>                    # APIから取得して生成
venv/bin/python grass_keychain.py <ユーザー名> --start-date 2025-01-05  # 開始週（日曜）を固定して生成
venv/bin/python grass_keychain.py <ユーザー名> --demo                  # ランダムデータで試す
venv/bin/python grass_keychain.py <ユーザー名> --json out/<ユーザー名>_contributions.json  # 保存済みデータで再生成
venv/bin/python grass_keychain.py -h                                   # オプション一覧
```

出力先は `out/`（`--out` で変更可）。層ごとのSTL、組み立て確認用3MF、プレビュー画像、生データのJSON、設定内容のテキストが書き出されます。

### 自分以外の人のデータで作る場合

GitHub本家のGraphQL API Explorer（Web版）は2025年11月に廃止されました。本人以外のデータを取得してもらう手順は [docs/データ提供の手順.pdf](docs/データ提供の手順.pdf) にまとめてあります。

## プロジェクト構成

```
core/            データ取得・寸法計算・形状生成・書き出しのロジック
app/             デスクトップアプリ（pywebview + Web UI）
grass_keychain.py  CLI版のエントリーポイント
docs/            設計ドキュメント・外部の人向けデータ提供手順
```

設計の詳細（層構成、寸法の決定経緯、印刷時の注意など）は [docs/設計まとめ.md](docs/設計まとめ.md) を参照してください。

## 注意

`out/` 以下の生成結果と、印刷用にエクスポートした `.3mf` / `.stl` ファイルは、個人のGitHub活動データを含むためリポジトリには含めていません（`.gitignore` で除外）。
