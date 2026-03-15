"""AI News Radar のメインエントリーポイント。"""

import argparse
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from src.feeds import fetch_all_feeds
from src.notion_writer import create_digest_page
from src.notifier import format_dry_run, notify, notify_no_articles
from src.state import filter_new_articles, load_state, mark_processed, save_state
from src.summarizer import generate_slack_summary, summarize_by_source

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI News Radar")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Slack 送信・Notion 書込み・state 更新なし、stdout に結果表示",
    )
    args = parser.parse_args()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. 全フィードから記事を取得
    all_articles = fetch_all_feeds()

    # 2. 処理済み URL を除外
    state = load_state()
    new_articles = filter_new_articles(all_articles, state)

    if not new_articles:
        logger.info("No new articles found")
        if not args.dry_run:
            notify_no_articles(today)
        else:
            print("No new articles found today.")
        return

    logger.info("Processing %d new article(s)", len(new_articles))

    # 3. ソース別 Gemini ダイジェスト生成（各ソース独立に1回ずつ呼び出し）
    digest = summarize_by_source(new_articles)

    # 4. Slack 概要 + ピック選出を Gemini で生成
    try:
        slack_summary, best_pick_source = generate_slack_summary(digest)
    except Exception:
        logger.warning("Failed to generate Slack summary, using fallback", exc_info=True)
        slack_summary, best_pick_source = "", ""

    if args.dry_run:
        print(format_dry_run(today, digest, slack_summary))
        return

    # 5. Notion にダイジェストページを作成（ルールベース結合）
    notion_url = create_digest_page(digest, slack_summary)

    # 6. Slack に通知
    notify(today, slack_summary, digest, notion_url, best_pick_source)

    # 7. state を更新・保存
    # picked: Notion に書いた記事のみ（trends + picks の URL）
    picked_articles = []
    for t in digest.trends:
        picked_articles.extend(a for a in new_articles if a.url == t.url)
    for pick in digest.picks.values():
        picked_articles.extend(a for a in new_articles if a.url == pick.url)
    state = mark_processed(state, new_articles, picked_articles)
    save_state(state)

    logger.info("Done")


if __name__ == "__main__":
    main()
