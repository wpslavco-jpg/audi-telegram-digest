#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dashboard.py — локальный веб-дашборд для управления Audi Telegram Digest.

Запуск:
    streamlit run dashboard.py

Управляет: источниками (sources.json), критериями отбора и стилем
(instructions/BRIEF.md, instructions/STYLE.md), каналами публикации
(channels.json), очередью постов (pipeline_state.json), логами
и синхронизацией с git.

Поиск и рерайт новостей дашборд не делает — это остаётся за Claude в чате.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "pipeline_state.json"
SOURCES_PATH = BASE_DIR / "sources.json"
CHANNELS_PATH = BASE_DIR / "channels.json"
BRIEF_PATH = BASE_DIR / "instructions" / "BRIEF.md"
STYLE_PATH = BASE_DIR / "instructions" / "STYLE.md"
LOG_PATH = BASE_DIR / "publish_log.txt"
USED_NEWS_PATH = BASE_DIR / "used-news.md"
PUBLISHER_SCRIPT = BASE_DIR / "src" / "telegram_publisher.py"

st.set_page_config(page_title="Audi Digest — панель управления", layout="wide")


# ---------- Общие утилиты ----------

def load_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def save_text(path: Path, content: str):
    path.write_text(content, encoding="utf-8")


def run_git(*args) -> tuple[int, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output.strip()


# ---------- Сайдбар: статус и git ----------

with st.sidebar:
    st.header("Audi Digest")

    state = load_json(STATE_PATH, {"meta": {}, "posts": []})
    posts = state.get("posts", [])
    n_candidate = sum(1 for p in posts if p.get("status") == "candidate")
    n_waiting = sum(1 for p in posts if p.get("status") == "ожидает")
    n_published = sum(1 for p in posts if p.get("status") == "опубликовано")
    n_error = sum(1 for p in posts if p.get("status") == "ошибка")

    c1, c2 = st.columns(2)
    c1.metric("Кандидаты", n_candidate)
    c2.metric("Ожидает", n_waiting)
    c1.metric("Опубликовано", n_published)
    c2.metric("Ошибок", n_error)

    st.divider()
    st.subheader("Git")

    code, status_out = run_git("status", "--short", "--branch")
    st.code(status_out or "(нет изменений)", language=None)

    gcol1, gcol2 = st.columns(2)
    if gcol1.button("⬇️ Pull", width="stretch"):
        code, out = run_git("pull", "origin", "master", "--no-edit")
        if code == 0:
            st.success("Pull выполнен")
        else:
            st.error(out)
        st.rerun()

    if gcol2.button("⬆️ Push", width="stretch"):
        run_git("add", "-A")
        code_c, out_c = run_git(
            "commit", "-m", "Update via dashboard"
        )
        code_p, out_p = run_git("push")
        if code_p == 0:
            st.success("Push выполнен")
        else:
            st.error(out_c + "\n" + out_p)
        st.rerun()

    st.divider()
    st.subheader("Публикация")

    if st.button("▶️ Запустить publisher.py сейчас", width="stretch"):
        result = subprocess.run(
            [sys.executable, str(PUBLISHER_SCRIPT)],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        st.text_area("Вывод", result.stdout + result.stderr, height=150)
        st.rerun()


# ---------- Вкладки ----------

tab_queue, tab_sources, tab_criteria, tab_channels, tab_logs = st.tabs(
    ["📋 Очередь", "🌐 Источники", "📝 Критерии", "📡 Каналы", "📜 Логи"]
)


# --- Очередь ---
with tab_queue:
    st.subheader("Очередь постов")

    if not posts:
        st.info("Постов пока нет.")
    else:
        status_filter = st.multiselect(
            "Фильтр по статусу",
            options=["candidate", "ожидает", "опубликовано", "ошибка"],
            default=["candidate", "ожидает", "ошибка"],
        )

        filtered = [p for p in posts if p.get("status") in status_filter] if status_filter else posts

        for post in filtered:
            status_icon = {
                "candidate": "🕓",
                "ожидает": "⏳",
                "опубликовано": "✅",
                "ошибка": "❌",
            }.get(post.get("status"), "❔")

            with st.expander(f"{status_icon} [{post.get('status')}] {post.get('title', post.get('id'))}"):
                st.markdown(f"**{post.get('hook', '')}**")
                st.write(post.get("body", ""))
                st.caption(
                    f"ID: {post.get('id')} · Источник: {post.get('source')} · "
                    f"[{post.get('linkWord')}]({post.get('linkUrl')})"
                )

                col1, col2, col3 = st.columns(3)
                new_status = col1.selectbox(
                    "Статус",
                    options=["candidate", "ожидает", "опубликовано", "ошибка"],
                    index=["candidate", "ожидает", "опубликовано", "ошибка"].index(
                        post.get("status", "candidate")
                    ),
                    key=f"status_{post['id']}",
                )
                new_slot = col2.text_input("Слот", value=post.get("slot") or "", key=f"slot_{post['id']}")
                new_scheduled = col3.text_input(
                    "scheduledFor (UTC ISO)",
                    value=post.get("scheduledFor") or "",
                    key=f"sched_{post['id']}",
                )

                channels_data = load_json(CHANNELS_PATH, {"channels": [], "defaultChannelId": None})
                channel_ids = [c["id"] for c in channels_data.get("channels", [])]
                current_channel = post.get("channelId") or channels_data.get("defaultChannelId")
                if channel_ids:
                    new_channel = st.selectbox(
                        "Канал публикации",
                        options=channel_ids,
                        index=channel_ids.index(current_channel) if current_channel in channel_ids else 0,
                        key=f"channel_{post['id']}",
                    )
                else:
                    new_channel = None

                bcol1, bcol2 = st.columns(2)
                if bcol1.button("💾 Сохранить", key=f"save_{post['id']}"):
                    post["status"] = new_status
                    post["slot"] = new_slot or None
                    post["scheduledFor"] = new_scheduled or None
                    if new_channel:
                        post["channelId"] = new_channel
                    save_json(STATE_PATH, state)
                    st.success("Сохранено")
                    st.rerun()

                if bcol2.button("🗑️ Удалить", key=f"delete_{post['id']}"):
                    state["posts"] = [p for p in posts if p["id"] != post["id"]]
                    save_json(STATE_PATH, state)
                    st.success("Удалено")
                    st.rerun()


# --- Источники ---
with tab_sources:
    st.subheader("Источники новостей")
    st.caption("Список сайтов, которые Claude проверяет при поиске новостей.")

    sources_data = load_json(SOURCES_PATH, {"sources": [], "blocked": []})

    st.markdown("**Разрешённые источники**")
    sources_df = pd.DataFrame(sources_data.get("sources", []))
    if sources_df.empty:
        sources_df = pd.DataFrame(columns=["url", "priority", "notes"])
    edited_sources = st.data_editor(
        sources_df,
        num_rows="dynamic",
        width="stretch",
        column_config={
            "priority": st.column_config.SelectboxColumn(
                "priority", options=["audi", "fuel", "general"]
            )
        },
        key="sources_editor",
    )

    st.markdown("**Заблокированные источники** (капча/логин — не использовать)")
    blocked_df = pd.DataFrame(sources_data.get("blocked", []))
    if blocked_df.empty:
        blocked_df = pd.DataFrame(columns=["url", "reason"])
    edited_blocked = st.data_editor(
        blocked_df, num_rows="dynamic", width="stretch", key="blocked_editor"
    )

    if st.button("💾 Сохранить источники"):
        save_json(
            SOURCES_PATH,
            {
                "sources": edited_sources.fillna("").to_dict("records"),
                "blocked": edited_blocked.fillna("").to_dict("records"),
            },
        )
        st.success("Сохранено в sources.json")


# --- Критерии ---
with tab_criteria:
    st.subheader("Критерии отбора и стиль")

    brief_col, style_col = st.columns(2)

    with brief_col:
        st.markdown("**instructions/BRIEF.md** — что искать и в каком приоритете")
        brief_text = st.text_area(
            "BRIEF.md", value=load_text(BRIEF_PATH), height=500, key="brief_editor",
            label_visibility="collapsed",
        )
        if st.button("💾 Сохранить BRIEF.md"):
            save_text(BRIEF_PATH, brief_text)
            st.success("Сохранено")

    with style_col:
        st.markdown("**instructions/STYLE.md** — как писать пост")
        style_text = st.text_area(
            "STYLE.md", value=load_text(STYLE_PATH), height=500, key="style_editor",
            label_visibility="collapsed",
        )
        if st.button("💾 Сохранить STYLE.md"):
            save_text(STYLE_PATH, style_text)
            st.success("Сохранено")


# --- Каналы ---
with tab_channels:
    st.subheader("Каналы публикации в Telegram")

    channels_data = load_json(CHANNELS_PATH, {"channels": [], "defaultChannelId": None})
    channels_df = pd.DataFrame(channels_data.get("channels", []))
    if channels_df.empty:
        channels_df = pd.DataFrame(columns=["id", "name", "chatId", "messageThreadId"])

    edited_channels = st.data_editor(
        channels_df, num_rows="dynamic", width="stretch", key="channels_editor"
    )

    channel_ids = [c for c in edited_channels["id"].tolist() if c]
    default_id = st.selectbox(
        "Канал по умолчанию",
        options=channel_ids,
        index=channel_ids.index(channels_data.get("defaultChannelId"))
        if channels_data.get("defaultChannelId") in channel_ids
        else 0,
    ) if channel_ids else None

    if st.button("💾 Сохранить каналы"):
        records = edited_channels.fillna("").to_dict("records")
        for r in records:
            if r.get("messageThreadId") == "":
                r["messageThreadId"] = None
            elif r.get("messageThreadId") is not None:
                try:
                    r["messageThreadId"] = int(r["messageThreadId"])
                except (ValueError, TypeError):
                    pass
        save_json(CHANNELS_PATH, {"channels": records, "defaultChannelId": default_id})
        st.success("Сохранено в channels.json")


# --- Логи ---
with tab_logs:
    st.subheader("Логи публикации")
    n_lines = st.slider("Сколько последних строк показать", 10, 200, 50)
    log_text = load_text(LOG_PATH)
    lines = log_text.splitlines()[-n_lines:]
    st.code("\n".join(lines) or "(лог пуст)", language=None)

    st.subheader("used-news.md (дедупликация)")
    st.text(load_text(USED_NEWS_PATH) or "(пусто)")
