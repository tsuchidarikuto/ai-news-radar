"""フィード定義モジュール。"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class FeedSource:
    """RSS/Atom フィードの定義。"""

    name: str
    url: str
    feed_type: str = "rss"  # "rss", "atom", "html"
    category: str = "tech"  # "tech" (個別ソース) or "trend" (Google Alerts)
    reselectable: bool = False  # True: 未ピックアップ記事を7日間再候補にする


def get_feeds() -> list[FeedSource]:
    """全フィードソースのリストを返す。環境変数から Google Alerts を動的に追加する。"""
    feeds = list(FEEDS)

    # GOOGLE_ALERTS_RSS_1, GOOGLE_ALERTS_RSS_2, ... を動的に追加
    i = 1
    while True:
        url = os.environ.get(f"GOOGLE_ALERTS_RSS_{i}")
        if not url:
            break
        feeds.append(FeedSource(
            name=f"Google Alerts #{i}",
            url=url,
            category="trend",
        ))
        i += 1

    return feeds


FEEDS: list[FeedSource] = [
    FeedSource(
        name="OpenAI",
        url="https://openai.com/blog/rss.xml",
    ),
    FeedSource(
        name="Anthropic",
        url="https://www.anthropic.com/news",
        feed_type="html",
    ),
    FeedSource(
        name="Google AI",
        url="https://blog.google/technology/ai/rss/",
    ),
    FeedSource(
        name="Claude Code",
        url="https://github.com/anthropics/claude-code/releases.atom",
        feed_type="atom",
    ),
    FeedSource(
        name="Zenn",
        url="https://zenn.dev/topics/ai/feed",
        reselectable=True,
    ),
    FeedSource(
        name="Qiita",
        url="https://qiita.com/popular-items/feed",
        feed_type="atom",
        reselectable=True,
    ),
]
