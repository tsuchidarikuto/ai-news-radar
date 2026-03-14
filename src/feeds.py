"""RSS/Atom/HTML フィード取得・パースモジュール。"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

from src.config import FeedSource, get_feeds

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30


@dataclass
class Article:
    """取得した記事。"""

    title: str
    url: str
    source: str
    description: str = ""
    published: str = ""


def fetch_all_feeds() -> list[Article]:
    """全フィードから記事を取得して返す。"""
    feeds = get_feeds()
    articles: list[Article] = []

    for feed in feeds:
        try:
            if feed.feed_type == "html":
                new_articles = _fetch_html(feed)
            else:
                new_articles = _fetch_rss(feed)
            articles.extend(new_articles)
            logger.info("Fetched %d articles from %s", len(new_articles), feed.name)
        except Exception:
            logger.error("Failed to fetch %s", feed.name, exc_info=True)

    logger.info("Total articles fetched: %d", len(articles))
    return articles


def _fetch_rss(feed: FeedSource) -> list[Article]:
    """RSS/Atom フィードをパースして Article リストを返す。"""
    response = requests.get(feed.url, timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()

    parsed = feedparser.parse(response.content)
    articles: list[Article] = []

    for entry in parsed.entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        if not title or not link:
            continue

        description = ""
        if entry.get("summary"):
            description = _strip_html(entry.summary)
        elif entry.get("description"):
            description = _strip_html(entry.description)

        published = entry.get("published", "")

        articles.append(Article(
            title=title,
            url=link,
            source=feed.name,
            description=description[:500],
            published=published,
        ))

    return articles


def _fetch_html(feed: FeedSource) -> list[Article]:
    """HTML ページをスクレイピングして Article リストを返す（Anthropic News 用）。"""
    response = requests.get(feed.url, timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    articles: list[Article] = []

    # Anthropic News のリンク構造に対応
    for link_tag in soup.select("a[href*='/news/']"):
        href = link_tag.get("href", "")
        if not href or href == "/news/" or href == "/news":
            continue

        title = link_tag.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        url = href if href.startswith("http") else "https://www.anthropic.com" + href

        # 重複排除（同一 URL の複数リンク）
        if any(a.url == url for a in articles):
            continue

        articles.append(Article(
            title=title,
            url=url,
            source=feed.name,
        ))

    return articles


def _strip_html(text: str) -> str:
    """HTML タグを除去してプレーンテキストを返す。"""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ", strip=True)
