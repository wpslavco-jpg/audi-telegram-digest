#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telegram_publisher.py

Отправляет посты со статусом "ожидает" (и подошедшим временем) из pipeline_state.json
в Telegram через Bot API c использованием MarkdownV2 формата.

Токен читается из telegram_token.txt в момент выполнения (не хардкодится, не логируется).
После успешной отправки: обновляет статус на "опубликовано" и добавляет запись в used-news.md.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_PATH = BASE_DIR / "pipeline_state.json"
TOKEN_PATH = BASE_DIR / "telegram_token.txt"
USED_NEWS_PATH = BASE_DIR / "used-news.md"
LOG_PATH = BASE_DIR / "publish_log.txt"

TELEGRAM_CHAT_ID = "@audi_maniya"
MESSAGE_THREAD_ID = 1050


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    console_msg = line.encode("ascii", errors="replace").decode("ascii")
    print(console_msg)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_token() -> str:
    """Токен берётся из переменной окружения (GitHub Actions secret) или,
    если её нет, из локального файла telegram_token.txt (ручной запуск)."""
    env_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if env_token:
        return env_token.strip()
    with open(TOKEN_PATH, "r", encoding="utf-8") as f:
        return f.read().strip()


def escape_markdown_v2(text: str) -> str:
    """Экранирует спецсимволы для MarkdownV2 формата Telegram."""
    escape_chars = "_*[]()~`>#+-=|{}.!"
    for char in escape_chars:
        text = text.replace(char, f"\\{char}")
    return text


def escape_markdown_v2_url(url: str) -> str:
    """Экранирует URL внутри inline-ссылки MarkdownV2: там нужно
    экранировать только \\ и ) (по спецификации Telegram), а не
    весь набор спецсимволов — иначе сломается сам адрес."""
    return url.replace("\\", "\\\\").replace(")", "\\)")


def build_markdown_v2(post: dict) -> str:
    """Форматирует пост в MarkdownV2 сообщение для Telegram."""
    hook = escape_markdown_v2(post.get("hook", "").strip())
    body = escape_markdown_v2(post.get("body", "").strip())
    link_word = escape_markdown_v2(post.get("linkWord", ""))
    link_url = escape_markdown_v2_url(post.get("linkUrl", ""))

    link_part = f"[{link_word}]({link_url})" if link_word and link_url else ""

    message = f"{hook}\n\n{body}"
    if link_part:
        message += f"\n\n{link_part}"

    return message


def send_message(token: str, text: str):
    """Отправляет сообщение через Telegram Bot API с MarkdownV2."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "message_thread_id": MESSAGE_THREAD_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
    }

    def _post(body):
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        return _post(payload), None
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        try:
            fallback = dict(payload)
            fallback.pop("parse_mode", None)
            result = _post(fallback)
            return result, f"markdownv2_failed_fallback_plain: {err_body}"
        except urllib.error.HTTPError as e2:
            err_body2 = e2.read().decode("utf-8", errors="replace")
            return None, err_body2
    except Exception as e:
        return None, str(e)


def add_to_used_news(post: dict):
    """Добавляет опубликованный пост в used-news.md, если его ещё нет."""
    link_url = post.get("linkUrl", "")

    if USED_NEWS_PATH.exists():
        with open(USED_NEWS_PATH, "r", encoding="utf-8") as f:
            if link_url in f.read():
                return

    try:
        published_at = datetime.fromisoformat(
            post["publishedAtSource"].replace("Z", "+00:00")
        )
        date_str = published_at.strftime("%d.%m.%Y %H:%M")
    except (ValueError, KeyError, TypeError):
        date_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    title = post.get("title", "Unknown")
    link_word = post.get("linkWord", "")

    entry = f"- {title} ({link_word}) | {link_url} | {date_str}"

    with open(USED_NEWS_PATH, "a", encoding="utf-8") as f:
        f.write(entry + "\n")


def main():
    if not os.environ.get("TELEGRAM_BOT_TOKEN") and not TOKEN_PATH.exists():
        log(f"ОШИБКА: нет ни переменной TELEGRAM_BOT_TOKEN, ни файла {TOKEN_PATH.name}.")
        sys.exit(0)
    if not STATE_PATH.exists():
        log("ОШИБКА: не найден pipeline_state.json.")
        sys.exit(0)

    token = read_token()
    state = load_json(STATE_PATH)

    now = datetime.now(timezone.utc)
    due = []

    for post in state.get("posts", []):
        if post.get("status") != "ожидает":
            continue
        scheduled_for = post.get("scheduledFor")
        if not scheduled_for:
            continue
        try:
            sched_dt = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00"))
        except ValueError:
            log(f"Пропускаю {post.get('id')}: не смог разобрать scheduledFor={scheduled_for!r}")
            continue
        if sched_dt <= now:
            due.append(post)

    if not due:
        log("Нечего публиковать (очередь пуста или время ещё не подошло).")
        return

    log(f"Найдено к отправке: {len(due)}")
    changed = False

    for post in due:
        text = build_markdown_v2(post)
        result, err = send_message(token, text)

        if result and result.get("ok"):
            post["status"] = "опубликовано"
            post["sentAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            post["telegramMessageId"] = result.get("result", {}).get("message_id")
            post["error"] = None if not err else err
            changed = True

            add_to_used_news(post)

            log(f"OK: {post.get('id')} -> message_id={post['telegramMessageId']}" + (f" ({err})" if err else ""))
        else:
            post["status"] = "ошибка"
            post["error"] = err or "unknown error"
            changed = True
            log(f"ОШИБКА при отправке {post.get('id')}: {err}")

        time.sleep(1.5)

    if changed:
        state.setdefault("meta", {})["lastPublishAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        save_json(STATE_PATH, state)
        log("pipeline_state.json обновлён.")


if __name__ == "__main__":
    main()
