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
from src.summarizer import build_digest

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

    # 3. trend / Zenn / Qiita は LLM フィルタ、それ以外は全件採用
    digest = build_digest(new_articles)

    if args.dry_run:
        print(format_dry_run(today, digest))
        return

    # 全件フィルタ落ちケース
    if not digest.kept_trends and not any(digest.kept_by_source.values()):
        logger.info("All articles filtered out")
        notify_no_articles(today)
        return

    # 4. Notion にダイジェストページを作成
    notion_url = create_digest_page(digest)

    # 5. Slack に通知
    notify(today, digest, notion_url)

    # 6. state を更新・保存（Slack/Notion に出した記事のみ picked 扱い）
    picked_articles = list(digest.kept_trends)
    for items in digest.kept_by_source.values():
        picked_articles.extend(items)
    state = mark_processed(state, new_articles, picked_articles)
    save_state(state)

    logger.info("Done")


if __name__ == "__main__":
    main()
