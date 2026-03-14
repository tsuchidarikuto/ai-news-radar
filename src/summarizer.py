"""Gemini API を使用したダイジェスト生成モジュール。"""

import json
import logging
import os
from dataclasses import dataclass

from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError

from src.feeds import Article
from src.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_client: genai.Client | None = None

_FALLBACK_MODEL = "gemini-2.5-flash"


@dataclass
class DigestSource:
    """ダイジェストに含まれるソース記事。"""

    title: str
    url: str
    source: str


@dataclass
class Digest:
    """生成されたダイジェスト。"""

    text: str
    sources: list[DigestSource]


def _get_client() -> genai.Client:
    """Gemini クライアントを取得する（シングルトン）。"""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable is not set")
        _client = genai.Client(api_key=api_key)
    return _client


def _call_model(client: genai.Client, model_name: str, content: str) -> str:
    """指定モデルで generate_content を呼び出し、レスポンステキストを返す。"""
    response = client.models.generate_content(
        model=model_name,
        contents=content,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
        ),
    )
    return response.text.strip()


def _build_input(articles: list[Article]) -> str:
    """記事リストを Gemini に渡す入力テキストに変換する。"""
    items = []
    for a in articles:
        items.append({
            "title": a.title,
            "url": a.url,
            "source": a.source,
            "description": a.description,
        })
    return json.dumps(items, ensure_ascii=False)


def _parse_response(raw_text: str) -> Digest:
    """Gemini のレスポンス JSON を Digest にパースする。"""
    text = raw_text
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse Gemini response as JSON: %s", raw_text)
        return Digest(text="", sources=[])

    digest_text = data.get("digest", "")
    sources = []
    for s in data.get("sources", []):
        sources.append(DigestSource(
            title=s.get("title", ""),
            url=s.get("url", ""),
            source=s.get("source", ""),
        ))

    return Digest(text=digest_text, sources=sources)


def generate_digest(articles: list[Article]) -> Digest:
    """記事リストからダイジェストを生成する。

    Args:
        articles: 新着記事のリスト。

    Returns:
        生成されたダイジェスト。記事が0件の場合は空のダイジェスト。
    """
    if not articles:
        return Digest(text="", sources=[])

    model_name = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash-lite"
    logger.info("Using Gemini model: %s", model_name)
    logger.info("Input articles: %d", len(articles))

    client = _get_client()
    content = _build_input(articles)

    try:
        raw_text = _call_model(client, model_name, content)
    except ServerError as e:
        if e.code == 503 and model_name != _FALLBACK_MODEL:
            logger.warning(
                "Gemini model %s returned 503. Falling back to %s.",
                model_name,
                _FALLBACK_MODEL,
            )
            raw_text = _call_model(client, _FALLBACK_MODEL, content)
        else:
            raise
    except ClientError as e:
        if e.code == 429:
            logger.warning(
                "Gemini API rate limit exceeded (429). Detail: %s",
                e.message,
            )
            raise
        raise

    logger.debug("Gemini response: %s", raw_text)
    return _parse_response(raw_text)
