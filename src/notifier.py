"""Slack / Microsoft Teams の Incoming Webhook を使った通知モジュール。

Teams は Workflows（Power Automate）の webhook URL を想定する。
SLACK_WEBHOOK_URL / TEAMS_WEBHOOK_URL のうち設定されている方すべてに送る。

Teams の webhook は本文の形式によらず 202 を返す。素の {"text": ...} も
MessageCard も 202 が返るだけでチャネルには何も出ない。実際に投稿されるのは
Adaptive Card だけなので、Teams にはカードを組んで送る。
https://support.microsoft.com/en-us/workflows/send-messages-in-teams-using-incoming-webhooks

Adaptive Card の TextBlock が解釈する記法は太字・斜体・箇条書き・リンクだけで、
本文中の改行が行送りになるとは保証されていない。そのため1行を1つの TextBlock にする。
https://learn.microsoft.com/en-us/adaptive-cards/authoring-cards/text-features

カード幅は msteams.width で広げる。
https://learn.microsoft.com/en-us/microsoftteams/platform/task-modules-and-cards/cards/cards-format
"""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

import requests

from src.summarizer import FILTERED_SOURCES, SOURCE_ORDER, Digest

logger = logging.getLogger(__name__)

_ADAPTIVE_CARD_VERSION = "1.4"


def _slack_payload(parts: list[str]) -> dict:
    """Slack はプレーンテキスト1本。リンクのプレビュー展開は抑止する。"""
    return {
        "text": "\n".join(parts),
        "unfurl_links": False,
        "unfurl_media": False,
    }


def _teams_payload(parts: list[str]) -> dict:
    """Teams は Adaptive Card。空行は次のブロックの区切りに変換する。"""
    body: list[dict] = []
    gap = False
    for line in parts:
        if not line:
            gap = True
            continue
        block: dict = {"type": "TextBlock", "text": line, "wrap": True}
        if gap and body:
            block["separator"] = True
            block["spacing"] = "medium"
        gap = False
        body.append(block)

    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": _ADAPTIVE_CARD_VERSION,
                    # 既定の幅だと本文がかなり折り返される。Power Automate 経由でも効く
                    "msteams": {"width": "Full"},
                    "body": body,
                },
            }
        ],
    }


@dataclass(frozen=True)
class _Target:
    """通知先ごとの記法とペイロード形式。"""

    name: str
    env_var: str
    bold: str  # "*{}*" のようなフォーマット文字列
    link: str  # label / url を受けるフォーマット文字列
    url_line: str  # URL だけの行の書き方
    build_payload: Callable[[list[str]], dict]


# Slack は mrkdwn。裸の URL はそのままリンクになる
SLACK = _Target(
    name="Slack",
    env_var="SLACK_WEBHOOK_URL",
    bold="*{}*",
    link="<{url}|{label}>",
    url_line="{url}",
    build_payload=_slack_payload,
)
# Teams は Adaptive Card。裸の URL はリンクにならないので明示的に張る
TEAMS = _Target(
    name="Teams",
    env_var="TEAMS_WEBHOOK_URL",
    bold="**{}**",
    link="[{label}]({url})",
    url_line="[{url}]({url})",
    build_payload=_teams_payload,
)


def _targets() -> tuple[_Target, ...]:
    return (SLACK, TEAMS)


def _render_source_block(target: _Target, title: str, items: list) -> list[str]:
    """1ソース分のブロックを組み立てる。

    記事ごとに 見出し / Gemini 要約 / URL の3行。要約がなければ2行。
    要約内の改行は潰す（通知先ごとに改行の扱いが違うため）。
    """
    if not items:
        return []
    lines = [target.bold.format(title)]
    for a in items:
        lines.append(a.title)
        summary = " ".join((a.description or "").split())
        if summary:
            lines.append(summary)
        lines.append(target.url_line.format(url=a.url))
    return lines


def _build_parts(
    target: _Target, date_str: str, digest: Digest, notion_url: str
) -> list[str]:
    """通知先に合わせた本文を1行1要素のリストで組み立てる。

    AI トレンドと FILTERED_SOURCES（Zenn / Qiita）は先頭1件のみ。
    それ以外のソースを足した場合は全件出す。
    """
    parts: list[str] = [target.bold.format(f"AI News Radar - {date_str}")]
    cut_count = 0

    trends_shown = digest.kept_trends[:1]
    if trends_shown:
        parts.append("")
        parts.extend(_render_source_block(target, "AI トレンド", trends_shown))
    cut_count += max(0, len(digest.kept_trends) - len(trends_shown))

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
        parts.extend(_render_source_block(target, source, shown))

    if notion_url:
        parts.append("")
        label = f"記事の概要&その他の記事はこちら ({cut_count})"
        parts.append(target.link.format(url=notion_url, label=label))

    return parts


def _post(target: _Target, url: str, parts: list[str], context: str) -> None:
    """Teams は本文が壊れていても 202 を返すので、ここでの成功は「届いた」までしか意味しない。"""
    response = requests.post(url, json=target.build_payload(parts), timeout=30)
    response.raise_for_status()
    logger.info("%s notification sent (%s)", target.name, context)


def _webhooks() -> list[tuple[_Target, str]]:
    """環境変数が設定されている通知先を返す。1件もなければ RuntimeError。"""
    targets = _targets()
    found = [(t, os.environ.get(t.env_var, "").strip()) for t in targets]
    found = [(t, url) for t, url in found if url]
    if not found:
        raise RuntimeError(
            " / ".join(t.env_var for t in targets) + " のいずれも設定されていません"
        )
    return found


def notify(date_str: str, digest: Digest, notion_url: str) -> None:
    """設定済みの通知先にダイジェストを送信する。"""
    for target, url in _webhooks():
        _post(target, url, _build_parts(target, date_str, digest, notion_url), date_str)


def notify_no_articles(date_str: str) -> None:
    """新着記事がない場合の通知を送信する。"""
    parts = [f"本日（{date_str}）の AI ニュースはありませんでした。"]
    for target, url in _webhooks():
        _post(target, url, parts, f"no articles for {date_str}")


def _dry_run_article_lines(article) -> list[str]:
    lines = [f"  • {article.title}"]
    summary = " ".join((article.description or "").split())
    if summary:
        lines.append(f"    {summary}")
    lines.append(f"    {article.url}")
    return lines


def format_dry_run(date_str: str, digest: Digest) -> str:
    """dry-run 時の標準出力用テキストを生成する。"""
    lines = [f"=== AI News Radar - {date_str} ===", ""]

    if not digest.kept_trends and not any(digest.kept_by_source.values()):
        lines.append("No AI news articles found today.")
        return "\n".join(lines)

    if digest.kept_trends:
        lines.append("[AI トレンド]")
        for a in digest.kept_trends:
            lines.extend(_dry_run_article_lines(a))
        lines.append("")

    for source in SOURCE_ORDER:
        items = digest.kept_by_source.get(source) or []
        if not items:
            continue
        lines.append(f"[{source}]")
        for a in items:
            lines.extend(_dry_run_article_lines(a))
        lines.append("")

    return "\n".join(lines).rstrip()
