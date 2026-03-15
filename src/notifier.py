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


def _find_pick(digest: Digest, best_pick_source: str) -> tuple[str, "PickedArticle | None"]:
    """Gemini が選んだ best_pick_source に対応するピックを探す。"""
    from src.summarizer import PickedArticle  # noqa: F811

    # Gemini が選んだソースを探す
    if best_pick_source:
        if best_pick_source == "AI トレンド" and digest.trends:
            return "AI トレンド", digest.trends[0]
        pick = digest.picks.get(best_pick_source)
        if pick:
            return best_pick_source, pick

    # フォールバック: SOURCE_ORDER の先頭 → trend
    for source in SOURCE_ORDER:
        pick = digest.picks.get(source)
        if pick:
            return source, pick
    if digest.trends:
        return "AI トレンド", digest.trends[0]

    return "", None


def _build_text(
    date_str: str, slack_summary: str, digest: Digest, notion_url: str,
    best_pick_source: str = "",
) -> str:
    """Slack メッセージテキストを構築する。"""
    parts: list[str] = [f"*AI News Radar - {date_str}*"]

    if slack_summary:
        parts.append("")
        parts.append("*要約*")
        parts.append(slack_summary)

    # ピックアップ1本（Gemini が選出）
    _, pick = _find_pick(digest, best_pick_source)

    parts.append("")
    parts.append("*ピックアップ*")
    if pick:
        parts.append(f"<{pick.url}|{pick.title}>")
        parts.append(pick.description)
    else:
        parts.append("本日のピックアップはありませんでした。")

    # Notion リンク（ベタ貼りで unfurl 狙い）
    if notion_url:
        parts.append("")
        parts.append("詳細はこちら:")
        parts.append(notion_url)

    return "\n".join(parts)


def notify(
    date_str: str, slack_summary: str, digest: Digest, notion_url: str,
    best_pick_source: str = "",
) -> None:
    """Slack にダイジェストを送信する。"""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("SLACK_WEBHOOK_URL environment variable is not set")

    text = _build_text(date_str, slack_summary, digest, notion_url, best_pick_source)
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
