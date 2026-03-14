"""フィード定義モジュール。"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class FeedSource:
    """RSS/Atom フィードの定義。"""

    name: str
    url: str
    feed_type: str = "rss"  # "rss", "atom", "html"


def get_feeds() -> list[FeedSource]:
    """全フィードソースのリストを返す。環境変数から Google Alerts を動的に追加する。"""
    feeds = list(FEEDS)

    # GOOGLE_ALERTS_RSS_1, GOOGLE_ALERTS_RSS_2, ... を動的に追加
    i = 1
    while True:
        url = os.environ.get(f"GOOGLE_ALERTS_RSS_{i}")
        if not url:
            break
        feeds.append(FeedSource(name=f"Google Alerts #{i}", url=url))
        i += 1

    return feeds


FEEDS: list[FeedSource] = [
    FeedSource(
        name="OpenAI Blog",
        url="https://openai.com/blog/rss.xml",
    ),
    FeedSource(
        name="Anthropic News",
        url="https://www.anthropic.com/news",
        feed_type="html",
    ),
    FeedSource(
        name="Google AI Blog",
        url="https://blog.google/technology/ai/rss/",
    ),
    FeedSource(
        name="Claude Code Releases",
        url="https://github.com/anthropics/claude-code/releases.atom",
        feed_type="atom",
    ),
    FeedSource(
        name="Zenn AI",
        url="https://zenn.dev/topics/ai/feed",
    ),
    FeedSource(
        name="Qiita Popular",
        url="https://qiita.com/popular-items/feed",
        feed_type="atom",
    ),
]
