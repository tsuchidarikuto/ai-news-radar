# ai-news-radar

AI ニュース自動収集 → Gemini ダイジェスト → Notion 記録 → Slack 通知

## 実行

```bash
uv run python -m src.main --dry-run  # テスト実行
uv run python -m src.main            # 本番実行
```

## 環境変数

`.env` に設定（`.env.example` 参照）。`GEMINI_API_KEY`, `NOTION_API_KEY`, `NOTION_DATABASE_ID` が必須。

通知先は `SLACK_WEBHOOK_URL` と `TEAMS_WEBHOOK_URL` のうち設定されている方すべてに送る（どちらも未設定ならエラー）。Teams は Workflows (Power Automate) の webhook URL を使う。

Teams 向けは既定で記法なしの素のテキスト。Markdown が描画されると確認できたら `TEAMS_MARKDOWN=1` で太字とリンクを使う版に切り替える。

## 構成

- `src/config.py` — フィード定義（追加はここ）
- `src/feeds.py` — RSS/Atom/HTML 取得
- `src/summarizer.py` — Gemini ダイジェスト生成
- `src/notion_writer.py` — Notion DB 書き込み
- `src/notifier.py` — Slack 通知
- `src/state.py` — 重複排除（`data/state.json`）

## Bash

Python は uv 経由で実行する。pip は使わない。
