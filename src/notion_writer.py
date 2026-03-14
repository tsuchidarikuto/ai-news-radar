"""Notion DB へのダイジェストページ作成モジュール。"""

import logging
import os
from datetime import datetime, timezone

from notion_client import Client

from src.summarizer import Digest

logger = logging.getLogger(__name__)


def _get_client() -> Client:
    """Notion クライアントを取得する。"""
    api_key = os.environ.get("NOTION_API_KEY")
    if not api_key:
        raise RuntimeError("NOTION_API_KEY environment variable is not set")
    return Client(auth=api_key)


def _build_page_children(digest: Digest) -> list[dict]:
    """ダイジェストの本文ブロックを構築する。"""
    children: list[dict] = []

    # ダイジェスト本文を段落ごとに分割
    for paragraph in digest.text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": paragraph}}],
            },
        })

    # ソース記事セクション
    if digest.sources:
        children.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Sources"}}],
            },
        })

        for source in digest.sources:
            text_content = f"{source.title} ({source.source})"
            children.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{
                        "type": "text",
                        "text": {
                            "content": text_content,
                            "link": {"url": source.url} if source.url else None,
                        },
                    }],
                },
            })

    return children


def create_digest_page(digest: Digest) -> str:
    """Notion DB にダイジェストページを作成する。

    Returns:
        作成されたページの URL。
    """
    database_id = os.environ.get("NOTION_DATABASE_ID")
    if not database_id:
        raise RuntimeError("NOTION_DATABASE_ID environment variable is not set")

    client = _get_client()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"AI News - {today}"

    page = client.pages.create(
        parent={"database_id": database_id},
        properties={
            "Name": {"title": [{"text": {"content": title}}]},
            "Date": {"date": {"start": today}},
        },
        children=_build_page_children(digest),
    )

    page_url = page.get("url", "")
    logger.info("Created Notion page: %s", page_url)
    return page_url
