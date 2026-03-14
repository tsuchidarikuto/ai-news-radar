"""Slack Incoming Webhook を使った通知モジュール。"""

import logging
import os

import requests

from src.summarizer import Digest

logger = logging.getLogger(__name__)

_SLACK_SECTION_MAX_LENGTH = 3000


def _split_text(text: str, max_length: int) -> list[str]:
    """テキストを max_length 以下のチャンクに分割する。段落境界で分割を試みる。"""
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


def _build_blocks(date_str: str, digest: Digest, notion_url: str) -> list[dict]:
    """Slack Block Kit メッセージを構築する。"""
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"AI News Radar - {date_str}",
            },
        },
    ]

    # ダイジェスト本文（3000文字制限で分割）
    for chunk in _split_text(digest.text, _SLACK_SECTION_MAX_LENGTH):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": chunk},
        })

    blocks.append({"type": "divider"})

    # ソース記事リスト
    if digest.sources:
        source_lines = []
        for s in digest.sources:
            source_lines.append(f"- <{s.url}|{s.title}> ({s.source})")
        source_text = "*Sources*\n" + "\n".join(source_lines)

        for chunk in _split_text(source_text, _SLACK_SECTION_MAX_LENGTH):
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": chunk},
            })

    # Notion リンク
    if notion_url:
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"<{notion_url}|Notion で詳細を見る>",
            }],
        })

    return blocks


def notify(date_str: str, digest: Digest, notion_url: str) -> None:
    """Slack にダイジェストを送信する。"""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("SLACK_WEBHOOK_URL environment variable is not set")

    blocks = _build_blocks(date_str, digest, notion_url)
    payload = {
        "blocks": blocks,
        "text": f"AI News Radar - {date_str}",
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
        "text": f":information_source: 本日（{date_str}）の AI ニュースはありませんでした。",
    }

    response = requests.post(webhook_url, json=payload, timeout=30)
    response.raise_for_status()
    logger.info("Slack notification sent: no articles for %s", date_str)


def format_dry_run(date_str: str, digest: Digest, notion_url: str = "") -> str:
    """dry-run 時の標準出力用テキストを生成する。"""
    lines = [f"=== AI News Radar - {date_str} ===", ""]

    if not digest.text:
        lines.append("No AI news articles found today.")
        return "\n".join(lines)

    lines.append(digest.text)
    lines.append("")
    lines.append("--- Sources ---")
    for s in digest.sources:
        lines.append(f"  - {s.title} ({s.source})")
        lines.append(f"    {s.url}")

    if notion_url:
        lines.append("")
        lines.append(f"Notion: {notion_url}")

    return "\n".join(lines)
