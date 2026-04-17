"""Slack Incoming Webhook を使った通知モジュール。"""

import logging
import os

import requests

from src.summarizer import SOURCE_ORDER, Digest

logger = logging.getLogger(__name__)


def _build_text(date_str: str, digest: Digest, notion_url: str) -> str:
    """Slack メッセージテキストを構築する（タイトル一覧型）。"""
    parts: list[str] = [f"*AI News Radar - {date_str}*"]

    if digest.kept_trends:
        parts.append("")
        parts.append("*AI トレンド*")
        for a in digest.kept_trends:
            parts.append(f"• <{a.url}|{a.title}>")

    for source in SOURCE_ORDER:
        items = digest.kept_by_source.get(source) or []
        if not items:
            continue
        parts.append("")
        parts.append(f"*{source}*")
        for a in items:
            parts.append(f"• <{a.url}|{a.title}>")

    if notion_url:
        parts.append("")
        parts.append(notion_url)

    return "\n".join(parts)


def notify(date_str: str, digest: Digest, notion_url: str) -> None:
    """Slack にダイジェストを送信する。"""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("SLACK_WEBHOOK_URL environment variable is not set")

    text = _build_text(date_str, digest, notion_url)
    payload = {
        "text": text,
        "unfurl_links": True,
        "unfurl_media": True,
    }

    response = requests.post(webhook_url, json=payload, timeout=30)
    response.raise_for_status()
    logger.info("Slack notification sent for %s", date_str)


def notify_no_articles(date_str: str) -> None:
    """新着記事がない場合の Slack 通知を送信する。"""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("SLACK_WEBHOOK_URL environment variable is not set")

    payload = {
        "text": f"本日（{date_str}）の AI ニュースはありませんでした。",
    }

    response = requests.post(webhook_url, json=payload, timeout=30)
    response.raise_for_status()
    logger.info("Slack notification sent: no articles for %s", date_str)


def format_dry_run(date_str: str, digest: Digest) -> str:
    """dry-run 時の標準出力用テキストを生成する（タイトル一覧型）。"""
    lines = [f"=== AI News Radar - {date_str} ===", ""]

    if not digest.kept_trends and not any(digest.kept_by_source.values()):
        lines.append("No AI news articles found today.")
        return "\n".join(lines)

    if digest.kept_trends:
        lines.append("[AI トレンド]")
        for a in digest.kept_trends:
            lines.append(f"  • {a.title}")
            lines.append(f"    {a.url}")
        lines.append("")

    for source in SOURCE_ORDER:
        items = digest.kept_by_source.get(source) or []
        if not items:
            continue
        lines.append(f"[{source}]")
        for a in items:
            lines.append(f"  • {a.title}")
            lines.append(f"    {a.url}")
        lines.append("")

    return "\n".join(lines).rstrip()
