# 3. Установка бота

Предполагается, что [Python 3.12](01-python.md) уже установлен. Ollama опционально — если планируешь использовать только облачные модели, пропусти шаги, относящиеся к Ollama.

## Получение исходников

```powershell
cd $HOME
git clone https://github.com/carono/last-war-vp-bot.git
cd last-war-vp-bot
git checkout v2
```

(Если репозиторий уже клонирован — `cd` в его папку и `git checkout v2`.)

## Виртуальное окружение

В корне репозитория:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Первая установка тянет OpenCV/NumPy/Pillow — несколько минут. После активации в начале строки приглашения появляется `(.venv)`.

> Если PowerShell ругается на блокировку скриптов при `Activate.ps1` — выполни один раз: `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`.

## Конфигурация `.env`

```powershell
copy .env.example .env
notepad .env
```

В файле задаются два провайдера независимо: для LLM (планирование) и для зрения. По умолчанию оба — `ollama`.

### Вариант А: всё локально через Ollama

Достаточно убедиться, что имена моделей в `.env` совпадают с теми, что ты загрузил через `ollama pull`:

```ini
LLM_PROVIDER=ollama
VISION_PROVIDER=ollama

OLLAMA_LLM_MODEL=qwen2.5:7b-instruct-q4_K_M
OLLAMA_VISION_MODEL=qwen2-vl:2b
```

### Вариант Б: облачный провайдер (OpenAI, Anthropic-compat, Groq, OpenRouter, …)

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

Текстовый LLM — облачный (для качества планирования), зрение — локальное (для скорости и приватности):

```ini
LLM_PROVIDER=openai_compat
VISION_PROVIDER=ollama
```

## Smoke-тест

```powershell
python -m lastwar_bot
```

Ожидаемый вывод:

```
LLM provider:    ollama
Vision provider: ollama
LLM reply: 'ok'
```

Если так — стек установлен правильно: Python видит зависимости, конфиг читается, провайдер отвечает.

## Типичные проблемы

- **`ConnectError: All connection attempts failed`** при `LLM_PROVIDER=ollama` — Ollama не запущен. Открой трей и убедись, что демон активен, или перезапусти `Ollama.exe`.
- **`401 Unauthorized`** при `openai_compat` — неверный или отсутствующий `OPENAI_API_KEY`.
- **`model "..." not found`** в Ollama — модель не была загружена через `ollama pull <name>`.
- **`ModuleNotFoundError: lastwar_bot`** — забыл активировать `.venv` или установить зависимости в текущее окружение.

## Дальше

Этот шаг подтвердил, что мост Python ↔ модель работает. Следующие итерации добавят захват окна Last War, классификатор экранов и каталог скиллов.
