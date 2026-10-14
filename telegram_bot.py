"""Mavis on Telegram — talk to her from your phone.

No new dependencies (plain HTTP, stdlib only).

Setup:
  1. Message @BotFather on Telegram, create a bot, copy the token.
  2. set TELEGRAM_BOT_TOKEN=<token>   (setx on cmd, or $env: in PowerShell)
  3. Optional: set MAVIS_TELEGRAM_CHAT_ID=<your chat id> to lock the bot to
     just you. (Send any message to the bot, then read the chat id from the
     "chat id ..." log line it prints.)
  4. python telegram_bot.py

The first message from an unknown chat must contain your spoken password
(the same one that unlocks desktop Mavis). After that the chat stays
unlocked for this run.

Commands: /start, /help, /voiceon (Mavis replies with voice notes),
/voiceoff (text replies).
"""
import json
import os
import tempfile
import time
import urllib.parse
import urllib.request

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
LOCKED_CHAT_ID = os.environ.get("MAVIS_TELEGRAM_CHAT_ID", "")
API = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else ""
POLL_TIMEOUT = 50
MAX_REPLY_CHARS = 4000
VOICE_NOTE_CHAR_LIMIT = 1200  # longer replies stay as text

HELP_TEXT = (
    "I'm Mavis. Talk to me like normal.\n\n"
    "Commands:\n"
    "/voiceon - I reply with voice notes\n"
    "/voiceoff - text replies (default)\n"
    "You can also send me voice messages and I'll transcribe them.\n"
    "Ask me to find and send files: \"send me the HCI chapter 3 PDF\"."
)


def _api(method, payload=None, timeout=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + "/" + method, data=data,
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout or POLL_TIMEOUT + 10) as resp:
        return json.loads(resp.read().decode())


def send_message(chat_id, text):
    for i in range(0, max(len(text), 1), MAX_REPLY_CHARS):
        _api("sendMessage", {"chat_id": chat_id,
                             "text": text[i:i + MAX_REPLY_CHARS] or "..."})


def send_voice_note(chat_id, text):
    """Synthesizes a voice note with Mavis's TTS voice and sends it as audio."""
    from core.voice_engine import synthesize_to_file
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    try:
        path = synthesize_to_file(text, tmp.name)
        if not path:
            return False
        from tools.telegram_tools import send_telegram_audio
        send_telegram_audio(TOKEN, chat_id, path)
        return True
    except Exception as e:
        print(f"[Telegram: voice note failed: {e}]")
        return False
    finally:
        try:
            os.remove(tmp.name)
        except Exception:
            pass


def download_telegram_file(file_id):
    """Downloads any Telegram file by file_id. Returns raw bytes or None."""
    info = _api("getFile", {"file_id": file_id}, timeout=30)
    file_path = (info.get("result") or {}).get("file_path")
    if not file_path:
        return None
    url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read()


def transcribe_voice_note(data: bytes):
    """Transcribes a Telegram voice message (ogg/opus) to text.

    Needs ffmpeg installed for the ogg decoding (winget install ffmpeg);
    otherwise returns None and the caller explains.
    """
    try:
        import speech_recognition as sr
    except ImportError:
        return None
    tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
    try:
        tmp.write(data)
        tmp.close()
        recognizer = sr.Recognizer()
        with sr.AudioFile(tmp.name) as source:
            audio = recognizer.record(source)
        return recognizer.recognize_google(audio)
    except Exception as e:
        print(f"[Telegram: voice transcription failed: {e}]")
        return None
    finally:
        try:
            os.remove(tmp.name)
        except Exception:
            pass


def chunked_reply(chat_id, text):
    send_message(chat_id, text or "...")


def main():
    if not TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN environment variable not found.")
        print("Create a bot with @BotFather on Telegram to get one.")
        return

    # Heavy imports here so the module stays importable without AI libraries.
    from core.auth import contains_password
    from core.app import create_stack
    from tools.telegram_tools import configure_telegram, clear_telegram

    # One shared stack: brain + alarms + conscience, headless (no audio/mic).
    stack = create_stack(voice=False, ambient=False, greet=False)
    brain = stack.brain

    # Proactive speech (conscience nudges, alarm announcements) is routed to
    # Telegram as messages instead of laptop-speaker audio. It follows the
    # most recently active authorized chat (or the locked chat, if set).
    peer = {"chat_id": int(LOCKED_CHAT_ID) if LOCKED_CHAT_ID.isdigit() else None}

    class TelegramVoice:
        def __init__(self):
            self.is_muted = False

        def speak(self, text, **kwargs):
            text = (text or "").strip()
            if not text:
                return
            if peer["chat_id"] is not None:
                chunked_reply(peer["chat_id"], text)
            else:
                print(f"Mavis: {text}")  # nobody on Telegram yet: console fallback

        def wait_until_done(self):
            pass

    stack.conscience.voice = TelegramVoice()
    stack.alarms.voice = stack.conscience.voice

    authed = set()
    voice_chats = set()
    if LOCKED_CHAT_ID:
        try:
            authed.add(int(LOCKED_CHAT_ID))
        except ValueError:
            pass

    offset = 0
    me = _api("getMe", timeout=30).get("result", {})
    print(f"[Telegram: listening as @{me.get('username')}] (Ctrl+C to stop)")
    if LOCKED_CHAT_ID:
        print(f"[Telegram: locked to chat id {LOCKED_CHAT_ID}]")

    try:
        while True:
            try:
                updates = _api("getUpdates", {"offset": offset,
                                              "timeout": POLL_TIMEOUT,
                                              "allowed_updates": ["message"]})
            except Exception as e:
                print(f"[Telegram: poll error: {e}]")
                time.sleep(5)
                continue

            for upd in updates.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                chat_id = (msg.get("chat") or {}).get("id")
                if not chat_id:
                    continue
                if LOCKED_CHAT_ID and str(chat_id) != str(LOCKED_CHAT_ID) \
                        and chat_id not in authed:
                    print(f"[Telegram: ignoring chat id {chat_id}]")
                    continue

                # Proactive speech follows the most recently active
                # authorized chat (strangers never become the target).
                if (LOCKED_CHAT_ID and str(chat_id) == str(LOCKED_CHAT_ID)) \
                        or chat_id in authed:
                    peer["chat_id"] = chat_id

                text = msg.get("text", "")
                # --- commands (handled before auth so /start always answers) ---
                if text.startswith("/"):
                    cmd = text.split()[0].split("@")[0].lower()
                    if cmd == "/start" or cmd == "/help":
                        chunked_reply(chat_id, HELP_TEXT)
                    elif cmd == "/voiceon":
                        voice_chats.add(chat_id)
                        chunked_reply(chat_id, "Voice notes on. I'll reply with audio.")
                    elif cmd == "/voiceoff":
                        voice_chats.discard(chat_id)
                        chunked_reply(chat_id, "Voice notes off. Text replies from now on.")
                    else:
                        chunked_reply(chat_id, "Unknown command. Try /help.")
                    continue

                # --- incoming voice message -> transcribe ---
                if not text and msg.get("voice"):
                    print(f"\n[Telegram chat id {chat_id}] <voice message>")
                    data = download_telegram_file(msg["voice"]["file_id"])
                    if not data:
                        chunked_reply(chat_id, "I couldn't download that voice message.")
                        continue
                    text = transcribe_voice_note(data) or ""
                    if not text:
                        chunked_reply(chat_id,
                                      "I got your voice message but couldn't transcribe it. "
                                      "Voice transcription needs ffmpeg installed on the laptop "
                                      "(winget install ffmpeg), or just type it.")
                        continue
                    print(f"[Telegram: transcribed] {text}")

                if not text:
                    continue
                print(f"\n[Telegram chat id {chat_id}] You: {text}")

                # --- auth gate ---
                if chat_id not in authed:
                    if contains_password(text):
                        authed.add(chat_id)
                        brain.is_authenticated = True
                        chunked_reply(chat_id, "Systems unlocked, Rey. What do you need?")
                    else:
                        chunked_reply(chat_id,
                                      "Access denied. Please state authorization "
                                      "to verify your identity.")
                    continue

                # --- brain turn (Telegram file tool active for this turn only) ---
                configure_telegram(TOKEN, chat_id)
                try:
                    reply = brain.process_input(text)
                except Exception as e:
                    reply = f"I encountered a problem processing that. {e}"
                finally:
                    clear_telegram()

                # --- reply: voice note if enabled, else text ---
                if chat_id in voice_chats and reply.strip() \
                        and len(reply) <= VOICE_NOTE_CHAR_LIMIT:
                    if not send_voice_note(chat_id, reply):
                        chunked_reply(chat_id, reply)  # TTS failed -> text fallback
                else:
                    chunked_reply(chat_id, reply)
    except KeyboardInterrupt:
        print("\n[Telegram: stopped.]")


if __name__ == "__main__":
    main()
