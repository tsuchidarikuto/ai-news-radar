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
from src.prompts import FILTER_AND_SUMMARIZE_PROMPT, SUMMARIZE_PROMPT

logger = logging.getLogger(__name__)

_client: genai.Client | None = None

_FALLBACK_MODEL = "gemini-2.5-flash-lite"
_MAX_ARTICLES_PER_SOURCE = 20
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 5.0
_INTER_CALL_DELAY = 12.0  # RPM 制限対策（free tier: flash=5RPM, flash-lite=10RPM）

# ソース表示順
SOURCE_ORDER = ["Zenn", "Qiita", "OpenAI", "Anthropic", "Google AI", "Claude Code"]

# LLM フィルタを掛けるテックソース（tech 系のうち絞り込む対象）
FILTERED_SOURCES = {"Zenn", "Qiita"}


@dataclass
class Digest:
    """フィルタ後のダイジェスト。"""

    kept_by_source: dict[str, list[Article]]
    kept_trends: list[Article]
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
    return os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite-preview"


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
        pass
    # JSON 文字列内の生改行をエスケープしてリトライ
    try:
        import re
        fixed = re.sub(r'(?<=": ")(.*?)(?="[,}])', lambda m: m.group(0).replace("\n", "\\n"), text, flags=re.DOTALL)
        return json.loads(fixed)
    except (json.JSONDecodeError, Exception):
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


def _parse_items(raw: str) -> list[dict]:
    """Gemini の {"items": [...]} レスポンスを dict リストに変換する。"""
    data = _parse_json(raw)
    if not isinstance(data, dict):
        return []
    items = data.get("items")
    if not isinstance(items, list):
        return []
    return [i for i in items if isinstance(i, dict)]


def _apply_summary(article: Article, summary: Any) -> None:
    """Gemini 要約で article.description を上書きする（空文字・非 str は無視）。"""
    if isinstance(summary, str) and summary.strip():
        article.description = summary.strip()


def filter_and_summarize(articles: list[Article], label: str) -> list[Article]:
    """Gemini で記事を選別し、残す記事に 1 文要約を付与する。

    要約は article.description を上書きする形で埋め込む。
    失敗・該当なしの場合は空リストを返す。
    """
    if not articles:
        return []

    client = _get_client()
    model = _get_model()
    content = _articles_to_json(articles)

    logger.info("Filter+summarize %s (%d articles)", label, len(articles))
    try:
        raw = _call_model(client, model, content, FILTER_AND_SUMMARIZE_PROMPT)
    except Exception:
        logger.error("Failed to filter+summarize %s", label, exc_info=True)
        return []

    url_to_article = {a.url: a for a in articles}
    result: list[Article] = []
    seen: set[str] = set()
    for item in _parse_items(raw):
        url = item.get("url")
        if not isinstance(url, str) or url in seen:
            continue
        article = url_to_article.get(url)
        if article is None:
            continue
        _apply_summary(article, item.get("summary"))
        result.append(article)
        seen.add(url)

    logger.info("Kept %d/%d for %s", len(result), len(articles), label)
    return result


def summarize_articles(articles: list[Article], label: str) -> list[Article]:
    """全記事に 1 文要約を付与して返す。

    Gemini 呼出が失敗した場合は元の description を残したまま全件返す。
    """
    if not articles:
        return []

    client = _get_client()
    model = _get_model()
    content = _articles_to_json(articles)

    logger.info("Summarize %s (%d articles)", label, len(articles))
    try:
        raw = _call_model(client, model, content, SUMMARIZE_PROMPT)
    except Exception:
        logger.error("Failed to summarize %s", label, exc_info=True)
        return articles

    url_to_summary: dict[str, str] = {}
    for item in _parse_items(raw):
        url = item.get("url")
        summary = item.get("summary")
        if isinstance(url, str) and isinstance(summary, str) and summary.strip():
            url_to_summary[url] = summary.strip()

    for a in articles:
        summary = url_to_summary.get(a.url)
        if summary:
            a.description = summary

    logger.info("Summarized %d/%d for %s", len(url_to_summary), len(articles), label)
    return articles


def build_digest(articles: list[Article]) -> Digest:
    """記事を trend / tech に振り分け、Gemini で選別＋要約する。"""
    by_source: dict[str, list[Article]] = defaultdict(list)
    trend_articles: list[Article] = []

    for a in articles:
        if a.category == "trend":
            trend_articles.append(a)
        else:
            by_source[a.source].append(a)

    # AI トレンド（Google Alerts）: 選別＋要約
    kept_trends = filter_and_summarize(trend_articles, "AI トレンド")

    # テックソース別: 選別対象は filter+summarize、その他は summarize のみ
    kept_by_source: dict[str, list[Article]] = {}
    for source in SOURCE_ORDER:
        src_articles = by_source.get(source) or []
        if not src_articles:
            continue

        capped = src_articles[:_MAX_ARTICLES_PER_SOURCE]
        time.sleep(_INTER_CALL_DELAY)
        if source in FILTERED_SOURCES:
            kept = filter_and_summarize(capped, source)
        else:
            kept = summarize_articles(capped, source)

        if kept:
            kept_by_source[source] = kept

    return Digest(
        kept_by_source=kept_by_source,
        kept_trends=kept_trends,
        all_sources=articles,
    )
