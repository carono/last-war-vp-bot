# 3. Установка бота

Предполагается, что [Python 3.12](01-python.md) уже установлен. **Ollama на этом этапе не обязательна** — бот стартует в dev-режиме с заглушкой (`stub`), которая отдаёт canned-ответы. Реальный провайдер (Ollama / cloud) подключается позже одной правкой в `.env`.

## Получение исходников

```powershell
cd $HOME
git clone https://github.com/carono/last-war-vp-bot.git
cd last-war-vp-bot
git checkout v2
```

(Если репозиторий уже клонирован — `cd` в его папку и `git checkout v2`.)

## Виртуальное окружение и зависимости

В корне репозитория:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

Последняя команда (`pip install -e .`) подключает сам пакет `lastwar_bot` из `src/` в editable-режиме. Без неё `python -m lastwar_bot` ругается `No module named lastwar_bot`.

> Если PowerShell ругается на блокировку скриптов при `Activate.ps1` — выполни один раз: `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`.

## Smoke-тест (без внешних моделей)

Без `.env` бот сразу работает в режиме `stub`:

```powershell
python -m lastwar_bot
```

Ожидаемый вывод:

```
LLM provider:    stub
Vision provider: stub
LLM reply: "[stub LLM] prompt='Reply with exactly: ok'; reply: ok"
```

Это подтверждает, что пакет установлен, конфиг читается, фабрика провайдеров работает.

## Подключение реальной модели

Когда дойдём до интеграции — копируешь шаблон `.env`:

```powershell
copy .env.example .env
notepad .env
```

### Вариант А: Ollama локально

Установить [Ollama](02-ollama.md) и в `.env`:

```ini
LLM_PROVIDER=ollama
VISION_PROVIDER=ollama
OLLAMA_LLM_MODEL=qwen2.5:7b-instruct-q4_K_M
OLLAMA_VISION_MODEL=qwen2-vl:2b
```

### Вариант Б: облачный провайдер (OpenAI / Anthropic-compat / Groq / OpenRouter / …)

```ini
LLM_PROVIDER=openai_compat
VISION_PROVIDER=openai_compat
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_LLM_MODEL=gpt-4o-mini
OPENAI_VISION_MODEL=gpt-4o-mini
```

Для Groq / Together / OpenRouter / Anthropic / локального `llama.cpp`-сервера меняется `OPENAI_BASE_URL` и имя модели; ключ — соответствующий сервису.

### Вариант В: смешать

Например, текстовый LLM — облачный, зрение — локальное Ollama:

```ini
LLM_PROVIDER=openai_compat
VISION_PROVIDER=ollama
```

## Типичные проблемы

- **`No module named lastwar_bot`** — не выполнил `pip install -e .` в активированном `.venv`.
- **`ConnectError: All connection attempts failed`** при `LLM_PROVIDER=ollama` — Ollama не запущен или не установлен. Проверь иконку в трее или перейди на `stub` / `openai_compat`.
- **`401 Unauthorized`** при `openai_compat` — неверный или отсутствующий `OPENAI_API_KEY`.
- **`model "..." not found`** в Ollama — модель не была загружена через `ollama pull <name>`.
- **`Activate.ps1 cannot be loaded because running scripts is disabled`** — `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`.
