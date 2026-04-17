"""Slack Incoming Webhook を使った通知モジュール。"""

import logging
import os

import requests

from src.summarizer import FILTERED_SOURCES, SOURCE_ORDER, Digest

logger = logging.getLogger(__name__)


def _render_source_block(title: str, items: list) -> list[str]:
    """1ソース分のブロックを組み立てる。"""
    if not items:
        return []
    lines = [f"*{title}*"]
    for a in items:
        lines.append(a.title)
        lines.append(a.url)
    return lines


def _build_text(date_str: str, digest: Digest, notion_url: str) -> str:
    """Slack メッセージテキストを構築する。

    Zenn / Qiita / AI トレンドは先頭1件のみ。
    OpenAI / Anthropic / Google AI / Claude Code は全件。
    """
    parts: list[str] = [f"*AI News Radar - {date_str}*"]
    cut_count = 0

    trends_for_slack = digest.kept_trends[:1]
    if trends_for_slack:
        parts.append("")
        parts.extend(_render_source_block("AI トレンド", trends_for_slack))
    cut_count += max(0, len(digest.kept_trends) - len(trends_for_slack))

    for source in SOURCE_ORDER:
        items = digest.kept_by_source.get(source) or []
        if not items:
            continue
        if source in FILTERED_SOURCES:
            shown = items[:1]
            cut_count += len(items) - len(shown)
        else:
            shown = items
        parts.append("")
        parts.extend(_render_source_block(source, shown))

    if notion_url:
        parts.append("")
        label = f"記事の概要&その他の記事はこちら ({cut_count})"
        parts.append(f"<{notion_url}|{label}>")

    return "\n".join(parts)


def notify(date_str: str, digest: Digest, notion_url: str) -> None:
    """Slack にダイジェストを送信する。"""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("SLACK_WEBHOOK_URL environment variable is not set")

    text = _build_text(date_str, digest, notion_url)
    payload = {
        "text": text,
        "unfurl_links": False,
        "unfurl_media": False,
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
    """dry-run 時の標準出力用テキストを生成する。"""
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
