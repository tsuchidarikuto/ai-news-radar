"""Notion DB へのダイジェストページ作成モジュール（ルールベース結合）。"""

import logging
import os
from datetime import datetime, timezone

from notion_client import Client

from src.summarizer import SOURCE_ORDER, Digest

logger = logging.getLogger(__name__)


def _get_client() -> Client:
    """Notion クライアントを取得する。"""
    api_key = os.environ.get("NOTION_API_KEY")
    if not api_key:
        raise RuntimeError("NOTION_API_KEY environment variable is not set")
    return Client(auth=api_key)


def _build_page_children(digest: Digest) -> list[dict]:
    """ダイジェストの本文ブロックをルールベースで構築する。"""
    children: list[dict] = []

    # AI トレンド
    if digest.trends:
        children.append(_heading2("AI トレンド"))
        for t in digest.trends:
            children.append(_bulleted_link(t.title, t.url, t.description))

    # ソース別ピックアップ（タイトル → 概要 → 生URL）
    for source in SOURCE_ORDER:
        pick = digest.picks.get(source)
        if not pick:
            continue
        children.append(_heading2(f"{source}: {pick.title}"))
        children.append(_paragraph(pick.description))
        children.append(_paragraph(pick.url))

    # Sources（全参照記事）
    if digest.all_sources:
        children.append(_heading2("Sources"))
        for a in digest.all_sources:
            children.append(_bulleted_link(a.title, a.url, f"({a.source})"))

    return children


def _heading2(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }



def _bulleted_link(title: str, url: str, suffix: str = "") -> dict:
    rich_text = [{"type": "text", "text": {"content": title, "link": {"url": url}}}]
    if suffix:
        rich_text.append({"type": "text", "text": {"content": f" {suffix}"}})
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text},
    }


_NOTION_BLOCK_LIMIT = 100


def create_digest_page(digest: Digest) -> str:
    """Notion DB にダイジェストページを作成する。

    Notion API の children 上限（100ブロック）を超える場合はバッチ追加する。

    Returns:
        作成されたページの URL。
    """
    database_id = os.environ.get("NOTION_DATABASE_ID")
    if not database_id:
        raise RuntimeError("NOTION_DATABASE_ID environment variable is not set")

    client = _get_client()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"AI News - {today}"

    all_children = _build_page_children(digest)
    first_batch = all_children[:_NOTION_BLOCK_LIMIT]
    remaining = all_children[_NOTION_BLOCK_LIMIT:]

    page = client.pages.create(
        parent={"database_id": database_id},
        properties={
            "Name": {"title": [{"text": {"content": title}}]},
        },
        children=first_batch,
    )

    page_id = page["id"]

    # 100ブロック超はバッチで追加
    while remaining:
        batch = remaining[:_NOTION_BLOCK_LIMIT]
        remaining = remaining[_NOTION_BLOCK_LIMIT:]
        client.blocks.children.append(block_id=page_id, children=batch)

    page_url = page.get("url", "")
    logger.info("Created Notion page: %s", page_url)
    return page_url
