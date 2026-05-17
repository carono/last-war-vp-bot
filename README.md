# Last War Bot (v2)

Автоматизация PC-клиента игры Last War. Гибрид компьютерного зрения и LLM: быстрый CV для рутины (template matching, OCR), VLM/LLM — для классификации экранов, планирования сценариев и распознавания незнакомых ситуаций.

Поддерживаются как локальные модели (через [Ollama](https://ollama.com)), так и облачные сервисы с OpenAI-совместимым API (OpenAI, Anthropic, Groq, Together, OpenRouter, локальный llama.cpp-server и т.п.). Выбор провайдера — через переменные окружения.

**Статус:** активная переработка. Старая Lua/UOPilot-версия — на ветке `master`, документация перенесена в [`docs/legacy-ru/`](docs/legacy-ru/) и [`docs/legacy-en/`](docs/legacy-en/) как референс по фичам.

## Установка

См. [`docs/install/`](docs/install/README.md) — пошаговые инструкции для Windows: Python, Ollama, сам бот.

## Архитектура

См. [`docs/architecture.md`](docs/architecture.md).

## Запуск smoke-теста

После установки (`docs/install/`):

```powershell
.venv\Scripts\activate
python -m lastwar_bot
```

Скрипт проверит соединение с выбранным LLM-провайдером и выведет короткий ответ модели.
