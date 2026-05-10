# アメブロ → note 自動投稿システム

アメブロの新記事を検知して、noteへ自動で最適化・投稿するBotです。

## 機能

- アメブロRSSを1時間ごとに監視して新記事を検知
- note用に自動変換（絵文字削除・ハッシュタグ自動付与・固定テンプレート挿入）
- GitHub Actionsで無料・自動実行

---

## セットアップ手順

### 1. GitHubリポジトリを作成（プライベート推奨）

```bash
cd ameblo-to-note
git init
git add .
git commit -m "initial commit"
```

GitHubで新しいプライベートリポジトリを作成して、pushしてください。

### 2. GitHub Secretsを登録

GitHubリポジトリの **Settings → Secrets and variables → Actions** を開き、以下を登録：

| Secret名 | 値 |
|---|---|
| `NOTE_EMAIL` | noteのログインメールアドレス |
| `NOTE_PASSWORD` | noteのパスワード |

### 3. GitHub Actionsを有効化

リポジトリの **Actions** タブを開き、ワークフローを有効にする。

### 4. 動作確認（手動実行）

Actions → **Ameblo to Note Sync** → **Run workflow** で手動実行して動作確認。

---

## 変換ルール

- 絵文字をすべて削除（noteの清潔感に合わせる）
- 記事内容に合わせてハッシュタグを5個自動選定
- 記事末尾に固定テンプレート（ウェビナー誘導・お客様の声）を自動挿入

## ファイル構成

```
ameblo-to-note/
├── .github/workflows/sync.yml   # GitHub Actionsの定義
├── scripts/
│   ├── main.py                  # メインスクリプト
│   ├── rss_monitor.py           # アメブロRSS監視
│   ├── content_transformer.py   # note用コンテンツ変換
│   └── note_publisher.py        # Playwrightでnoteに投稿
├── data/
│   └── published.json           # 投稿済み記事のキャッシュ（自動生成）
└── requirements.txt
```
