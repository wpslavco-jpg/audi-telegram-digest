# Audi Telegram Digest

Бот, который собирает автомобильные новости, переписывает их по стилю
и публикует в Telegram-канал/группу. Всё управление — через обычный
текст в Claude Code, без Cowork и без ручного запуска скриптов на своём
компьютере.

## Как это работает

1. В чате: «Найди новости» — ищу по `instructions/BRIEF.md`, проверяю
   дубли по `used-news.md`, пишу тексты по `instructions/STYLE.md`,
   сохраняю в `pipeline_state.json` со статусом `candidate`.
2. Ты проверяешь тексты, просишь правки при необходимости.
3. «Запланируй пост X на 14:30» — статус меняется на `ожидает`,
   выставляется `scheduledFor` в UTC.
4. Изменения пушатся в этот репозиторий.
5. GitHub Actions (`.github/workflows/publish.yml`) раз в час проверяет
   очередь и отправляет всё, чьё время уже наступило — независимо от
   того, включён ли компьютер.

Полный список команд — в [COMMANDS.md](COMMANDS.md).

## Структура

```
instructions/BRIEF.md   — какие новости брать и в каком приоритете
instructions/STYLE.md   — как писать пост (структура, тон, ссылка)
src/telegram_publisher.py — скрипт отправки в Telegram
pipeline_state.json     — очередь постов и их статусы
used-news.md            — история публикаций (дедупликация)
publish_log.txt         — лог отправлений
.github/workflows/publish.yml — облачный запуск раз в час
```

## Токен бота

Локально — файл `telegram_token.txt` (в `.gitignore`, никогда не коммитится).
В облаке — GitHub Secret `TELEGRAM_BOT_TOKEN`, скрипт сам выбирает источник.
