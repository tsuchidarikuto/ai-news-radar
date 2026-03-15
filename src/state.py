"""処理済み URL の状態管理モジュール。

2つの状態を管理:
- picked_urls: Notion に書き込んだ記事（永久除外）
- seen_urls: 取得済み記事（公式ブログ等は除外、reselectable ソースは7日間再候補）
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "state.json")

_PURGE_DAYS = 30
_RESELECT_DAYS = 7


def load_state() -> dict:
    """状態ファイルを読み込む。旧形式からの自動マイグレーション付き。"""
    if not os.path.exists(STATE_FILE):
        return {"picked_urls": {}, "seen_urls": {}, "last_checked": None}

    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read state file: %s", e)
        return {"picked_urls": {}, "seen_urls": {}, "last_checked": None}

    # 旧形式 (processed_articles) からのマイグレーション
    if "processed_articles" in state and "picked_urls" not in state:
        state["seen_urls"] = state.pop("processed_articles")
        state["picked_urls"] = {}

    state.setdefault("picked_urls", {})
    state.setdefault("seen_urls", {})
    return state


def save_state(state: dict) -> None:
    """状態ファイルに保存する。"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    logger.info("State saved to %s", STATE_FILE)


def filter_new_articles(articles: list, state: dict) -> list:
    """処理済み URL を除外して新着記事のみを返す。

    - picked_urls: 全ソースで除外（既に Notion に書いた）
    - seen_urls: reselectable=False のソースのみ除外
                 reselectable=True のソースは7日以内なら再候補
    """
    picked = state.get("picked_urls", {})
    seen = state.get("seen_urls", {})
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_RESELECT_DAYS)).strftime("%Y-%m-%d")

    new_articles = []
    for a in articles:
        # 既にピックアップ済み → 除外
        if a.url in picked:
            continue

        # reselectable ソース: 7日以内の seen は再候補にする
        if a.reselectable:
            seen_date = seen.get(a.url)
            if seen_date and seen_date < cutoff:
                continue  # 7日超 → 除外
            new_articles.append(a)
        else:
            # 通常ソース: seen にあれば除外
            if a.url in seen:
                continue
            new_articles.append(a)

    logger.info("Filtered: %d total -> %d new articles", len(articles), len(new_articles))
    return new_articles


def mark_processed(state: dict, all_articles: list, picked_articles: list) -> dict:
    """記事 URL を状態に記録する。

    - picked_articles: picked_urls に追加（Notion に書いた記事）
    - all_articles: seen_urls に追加（全取得記事）
    """
    picked = state.get("picked_urls", {})
    seen = state.get("seen_urls", {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for a in picked_articles:
        picked[a.url] = today

    for a in all_articles:
        if a.url not in seen:
            seen[a.url] = today

    # purge
    purge_cutoff = (datetime.now(timezone.utc) - timedelta(days=_PURGE_DAYS)).strftime("%Y-%m-%d")
    picked = {url: d for url, d in picked.items() if d >= purge_cutoff}
    seen = {url: d for url, d in seen.items() if d >= purge_cutoff}

    state["picked_urls"] = picked
    state["seen_urls"] = seen
    state["last_checked"] = datetime.now(timezone.utc).isoformat()
    return state
