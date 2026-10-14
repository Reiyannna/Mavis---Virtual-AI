# Mavis

A Jarvis-like desktop AI assistant at **zero cost** — no paid APIs or subscriptions.
Voice-driven, proactive (a "conscience" that watches your schedule and nudges you),
with full Gmail / Calendar / Drive access and a Telegram bot for remote control.

## Setup

Requires Python 3.10+.

```bash
pip install -r requirements.txt
```

### Environment variables

| Variable | Required | What it does |
|---|---|---|
| `GEMINI_API_KEY` | yes (or Ollama) | Brain. Get one free at Google AI Studio |
| `TELEGRAM_BOT_TOKEN` | for Telegram | From `@BotFather` on Telegram |
| `MAVIS_TELEGRAM_CHAT_ID` | optional | Lock the Telegram bot to your chat only |
| `MAVIS_LLM_PROVIDER` | optional | `gemini` (default) or `ollama` for local models |
| `MAVIS_SLIM_CONSCIENCE` | optional | Set to `1` for the cheaper toolless conscience ticks |

### Google access (Gmail / Calendar / Drive)

1. Create a project in Google Cloud Console, enable the Gmail, Calendar and
   Drive APIs, and download the OAuth client as `config/credentials.json`.
   (`config/` is gitignored — your secrets never touch the repo.)
2. Run once and complete the browser consent. `config/token.json` is created
   automatically.

## Running

```bash
python main.py          # desktop app (voice + avatar GUI)
python telegram_bot.py  # Telegram bot (message it; first message must contain your spoken password)
```

## Layout

- `core/` — brain, voice engine, controller, conscience, alarms, memory
- `tools/` — 90+ tool functions (Gmail, Calendar, Drive, local files, Telegram, contacts…)
- `main.py` / `telegram_bot.py` — the two front ends

## Notes

- The spoken password list lives in `core/auth.py`. Keep this repo **private**
  unless you move it to an environment variable.
- The conscience ticks every 10 minutes (one cheap AI call) and announces
  meetings starting within 15 minutes. It never repeats a nudge within 3 hours.
