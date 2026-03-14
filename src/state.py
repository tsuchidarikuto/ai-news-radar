"""処理済み URL の状態管理モジュール。"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "state.json")

_PURGE_DAYS = 30


def load_state() -> dict:
    """状態ファイルを読み込む。"""
    if not os.path.exists(STATE_FILE):
        return {"processed_articles": {}, "last_checked": None}

    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read state file: %s", e)
        return {"processed_articles": {}, "last_checked": None}


def save_state(state: dict) -> None:
    """状態ファイルに保存する。"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    logger.info("State saved to %s", STATE_FILE)


def filter_new_articles(articles: list, state: dict) -> list:
    """処理済み URL を除外して新着記事のみを返す。"""
    processed = state.get("processed_articles", {})
    new_articles = [a for a in articles if a.url not in processed]
    logger.info("Filtered: %d total -> %d new articles", len(articles), len(new_articles))
    return new_articles


def mark_processed(state: dict, articles: list) -> dict:
    """記事 URL を処理済みとしてマークし、古いエントリを purge する。"""
    processed = state.get("processed_articles", {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for article in articles:
        processed[article.url] = today

    # 30日超のエントリを purge
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_PURGE_DAYS)).strftime("%Y-%m-%d")
    processed = {url: date for url, date in processed.items() if date >= cutoff}

    state["processed_articles"] = processed
    state["last_checked"] = datetime.now(timezone.utc).isoformat()
    return state
