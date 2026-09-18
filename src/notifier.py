"""Slack / Microsoft Teams の Incoming Webhook を使った通知モジュール。

Teams は Workflows（Power Automate）の webhook URL を想定する。
SLACK_WEBHOOK_URL / TEAMS_WEBHOOK_URL のうち設定されている方すべてに送る。

Teams は Markdown が描画されるとは限らないので既定では記法を使わない。
描画されると確認できたら TEAMS_MARKDOWN=1 で Markdown 版に切り替える。
"""

import logging
import os
from dataclasses import dataclass, replace

import requests

from src.summarizer import FILTERED_SOURCES, SOURCE_ORDER, Digest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Target:
    """通知先ごとの記法とペイロード形式。"""

    name: str
    env_var: str
    bold: str  # "*{}*" のようなフォーマット文字列
    link: str  # label / url を受けるフォーマット文字列
    newline: str
    extra_payload: dict


# Slack は mrkdwn
SLACK = _Target(
    name="Slack",
    env_var="SLACK_WEBHOOK_URL",
    bold="*{}*",
    link="<{url}|{label}>",
    newline="\n",
    extra_payload={"unfurl_links": False, "unfurl_media": False},
)
# Teams は既定で記法なし。ラベルと URL は行を分ける
TEAMS = _Target(
    name="Teams",
    env_var="TEAMS_WEBHOOK_URL",
    bold="{}",
    link="{label}\n{url}",
    newline="\n",
    extra_payload={},
)
# Markdown 版（改行は行末2スペースで強制）
TEAMS_MD = replace(TEAMS, bold="**{}**", link="[{label}]({url})", newline="  \n")


def _targets() -> tuple[_Target, ...]:
    """環境変数を見て通知先の組み合わせを決める。"""
    markdown = os.environ.get("TEAMS_MARKDOWN", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return (SLACK, TEAMS_MD if markdown else TEAMS)


def _render_source_block(target: _Target, title: str, items: list) -> list[str]:
    """1ソース分のブロックを組み立てる。"""
    if not items:
        return []
    lines = [target.bold.format(title)]
    for a in items:
        lines.append(a.title)
        lines.append(a.url)
    return lines


def _build_text(target: _Target, date_str: str, digest: Digest, notion_url: str) -> str:
    """通知先に合わせたメッセージテキストを構築する。

    Zenn / Qiita / AI トレンドは先頭1件のみ。
    OpenAI / Anthropic / Google AI / Claude Code は全件。
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

    return target.newline.join(parts)


def _post(target: _Target, url: str, text: str, context: str) -> None:
    response = requests.post(url, json={"text": text, **target.extra_payload}, timeout=30)
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
        _post(target, url, _build_text(target, date_str, digest, notion_url), date_str)


def notify_no_articles(date_str: str) -> None:
    """新着記事がない場合の通知を送信する。"""
    text = f"本日（{date_str}）の AI ニュースはありませんでした。"
    for target, url in _webhooks():
        _post(target, url, text, f"no articles for {date_str}")


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
