"""Slack Incoming Webhook を使った通知モジュール。"""

import logging
import os

import requests

from src.summarizer import SOURCE_ORDER, Digest

logger = logging.getLogger(__name__)

_SLACK_SECTION_MAX_LENGTH = 3000


def _split_text(text: str, max_length: int) -> list[str]:
    """テキストを max_length 以下のチャンクに分割する。"""
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        if current and len(current) + len(paragraph) + 2 > max_length:
            chunks.append(current.strip())
            current = ""
        current += paragraph + "\n\n"
    if current.strip():
        chunks.append(current.strip())

    return chunks


def _build_text(
    date_str: str, slack_summary: str, digest: Digest, notion_url: str
) -> str:
    """Slack メッセージテキストを構築する。unfurl_links 用に URL をベタ貼り。"""
    parts: list[str] = [f"*AI News Radar - {date_str}*"]

    if slack_summary:
        parts.append("")
        parts.append(slack_summary)

    # ピックアップ1本（最も注目度が高いもの）
    for source in SOURCE_ORDER:
        pick = digest.picks.get(source)
        if pick:
            parts.append("")
            parts.append("---")
            parts.append(f"*[Pick] {source}: {pick.title}*")
            parts.append(pick.description)
            break

    # Notion URL ベタ貼り（Slack が unfurl してプレビュー表示）
    if notion_url:
        parts.append("")
        parts.append(notion_url)

    return "\n".join(parts)


def notify(
    date_str: str, slack_summary: str, digest: Digest, notion_url: str
) -> None:
    """Slack にダイジェストを送信する。"""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("SLACK_WEBHOOK_URL environment variable is not set")

    text = _build_text(date_str, slack_summary, digest, notion_url)
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


def format_dry_run(
    date_str: str, digest: Digest, slack_summary: str = ""
) -> str:
    """dry-run 時の標準出力用テキストを生成する。"""
    lines = [f"=== AI News Radar - {date_str} ===", ""]

    if not digest.trends and not digest.picks:
        lines.append("No AI news articles found today.")
        return "\n".join(lines)

    if slack_summary:
        lines.append("[Slack Summary]")
        lines.append(slack_summary)
        lines.append("")

    if digest.trends:
        lines.append("[AI Trends]")
        for t in digest.trends:
            lines.append(f"  - {t.title}")
            lines.append(f"    {t.description}")
            lines.append(f"    {t.url}")
        lines.append("")

    if digest.picks:
        lines.append("[Picks]")
        for source in SOURCE_ORDER:
            pick = digest.picks.get(source)
            if not pick:
                continue
            lines.append(f"  {source}: {pick.title}")
            lines.append(f"    {pick.description}")
            lines.append(f"    {pick.url}")

    return "\n".join(lines)
