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
            reselectable=True,
        ))
        i += 1

    return feeds


# 取り込むのは Zenn / Qiita と、環境変数で足す Google Alerts のみ。
# OpenAI / Anthropic / Google AI / Claude Code の公式フィードは、
# 1日あたりの件数が多く Slack が読みにくくなるため外した。
FEEDS: list[FeedSource] = [
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
