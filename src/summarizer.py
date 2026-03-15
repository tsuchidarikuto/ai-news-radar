"""Gemini API を使用したソース別ダイジェスト生成モジュール。"""

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError

from src.feeds import Article
from src.prompts import (
    CLAUDE_CODE_PROMPT,
    SLACK_SUMMARY_PROMPT,
    TECH_SOURCE_PROMPT,
    TREND_PROMPT,
)

logger = logging.getLogger(__name__)

_client: genai.Client | None = None

_FALLBACK_MODEL = "gemini-2.5-flash"
_MAX_ARTICLES_PER_SOURCE = 20
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0

# ソース表示順
SOURCE_ORDER = ["OpenAI", "Anthropic", "Google AI", "Claude Code", "Zenn", "Qiita"]


@dataclass
class PickedArticle:
    """ピックアップされた記事。"""

    title: str
    url: str
    description: str
    source: str = ""


@dataclass
class Digest:
    """ソース別ダイジェスト（ルールベースで結合）。"""

    trends: list[PickedArticle]
    picks: dict[str, PickedArticle]
    all_sources: list[Article] = field(default_factory=list)


def _get_client() -> genai.Client:
    """Gemini クライアントを取得する（シングルトン）。"""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable is not set")
        _client = genai.Client(api_key=api_key)
    return _client


def _get_model() -> str:
    return os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash-lite"


def _call_model(
    client: genai.Client, model_name: str, content: str, system_prompt: str
) -> str:
    """指定モデルで generate_content を呼び出す。503 フォールバック + 429 リトライ付き。"""
    for attempt in range(_MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=content,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                ),
            )
            return response.text.strip()
        except ServerError as e:
            if e.code == 503 and model_name != _FALLBACK_MODEL:
                logger.warning(
                    "Model %s returned 503, falling back to %s",
                    model_name,
                    _FALLBACK_MODEL,
                )
                return _call_model(client, _FALLBACK_MODEL, content, system_prompt)
            raise
        except ClientError as e:
            if e.code == 429 and attempt < _MAX_RETRIES - 1:
                delay = _RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    "Rate limited (429), retrying in %.1fs (%d/%d)",
                    delay,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                time.sleep(delay)
                continue
            raise
    raise RuntimeError("Max retries exceeded")


def _parse_json(raw_text: str) -> Any:
    """Gemini のレスポンスから JSON をパースする。"""
    text = raw_text
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse JSON: %s", raw_text[:500])
        return None


def _articles_to_json(
    articles: list[Article], include_description: bool = True
) -> str:
    """記事リストを JSON 文字列に変換する。"""
    items = []
    for a in articles[:_MAX_ARTICLES_PER_SOURCE]:
        item: dict[str, str] = {"title": a.title, "url": a.url}
        if include_description and a.description:
            item["description"] = a.description
        items.append(item)
    return json.dumps(items, ensure_ascii=False)


def summarize_source(articles: list[Article], source: str) -> PickedArticle | None:
    """一つのテックソースから最も注目すべき記事を1本ピックアップする。"""
    if not articles:
        return None

    client = _get_client()
    model = _get_model()

    prompt = CLAUDE_CODE_PROMPT if source == "Claude Code" else TECH_SOURCE_PROMPT
    content = f"以下は {source} の記事です:\n{_articles_to_json(articles)}"

    logger.info("Summarizing %s (%d articles)", source, len(articles))
    raw = _call_model(client, model, content, prompt)
    data = _parse_json(raw)

    if not data:
        return None

    return PickedArticle(
        title=data.get("title", ""),
        url=data.get("url", ""),
        description=data.get("description", ""),
        source=source,
    )


def summarize_trends(articles: list[Article]) -> list[PickedArticle]:
    """Google Alerts からトレンド記事を3本ピックアップする。"""
    if not articles:
        return []

    client = _get_client()
    model = _get_model()

    # Google Alerts は title のみ渡す（トークン節約）
    content = _articles_to_json(articles, include_description=False)

    logger.info("Summarizing trends (%d articles)", len(articles))
    raw = _call_model(client, model, content, TREND_PROMPT)
    data = _parse_json(raw)

    if not data or not isinstance(data, list):
        return []

    return [
        PickedArticle(
            title=t.get("title", ""),
            url=t.get("url", ""),
            description=t.get("description", ""),
        )
        for t in data
    ]


def summarize_by_source(articles: list[Article]) -> Digest:
    """全記事をソース別に分割し、それぞれ Gemini で要約する。"""
    by_source: dict[str, list[Article]] = defaultdict(list)
    trend_articles: list[Article] = []

    for a in articles:
        if a.category == "trend":
            trend_articles.append(a)
        else:
            by_source[a.source].append(a)

    # トレンド（Google Alerts）
    trends: list[PickedArticle] = []
    try:
        trends = summarize_trends(trend_articles)
    except Exception:
        logger.error("Failed to summarize trends", exc_info=True)

    # テックソース別
    picks: dict[str, PickedArticle] = {}
    for source in SOURCE_ORDER:
        if source not in by_source:
            continue
        try:
            pick = summarize_source(by_source[source], source)
            if pick:
                picks[source] = pick
        except Exception:
            logger.error("Failed to summarize %s", source, exc_info=True)

    return Digest(trends=trends, picks=picks, all_sources=articles)


def build_digest_text(digest: Digest) -> str:
    """Digest をテキストに変換する（Slack summary 用）。"""
    parts: list[str] = []

    if digest.trends:
        parts.append("## AI トレンド")
        for t in digest.trends:
            parts.append(f"- {t.title}: {t.description}")

    for source in SOURCE_ORDER:
        pick = digest.picks.get(source)
        if not pick:
            continue
        parts.append(f"\n## {source}: {pick.title}")
        parts.append(pick.description)

    return "\n".join(parts)


def generate_slack_summary(digest: Digest) -> str:
    """ダイジェスト全体から Slack 用の3行概要を生成する。"""
    text = build_digest_text(digest)
    if not text:
        return ""

    client = _get_client()
    model = _get_model()

    logger.info("Generating Slack summary")
    raw = _call_model(client, model, text, SLACK_SUMMARY_PROMPT)
    data = _parse_json(raw)

    if not data:
        return ""

    return data.get("summary", "")
