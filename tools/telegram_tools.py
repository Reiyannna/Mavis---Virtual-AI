"""Telegram-only tools for Mavis.

These are registered globally so the brain knows they exist, but they only
work inside a Telegram chat session: telegram_bot.py calls configure_telegram()
before each brain turn and clear_telegram() after. Outside Telegram (e.g. the
desktop app) the tools politely report they are unavailable.
"""
import json
import mimetypes
import os
import urllib.request
import uuid

from core.settings import DOWNLOADS_DIR

_bot_token = None
_chat_id = None

# Telegram bots can send documents up to 50 MB.
_MAX_FILE_BYTES = 50 * 1024 * 1024


def configure_telegram(token: str, chat_id: int) -> None:
    global _bot_token, _chat_id
    _bot_token, _chat_id = token, chat_id


def clear_telegram() -> None:
    global _bot_token, _chat_id
    _bot_token, _chat_id = None, None


def _multipart_post(url: str, fields: dict, file_field: str,
                    file_path: str, timeout: int = 120) -> dict:
    """POSTs multipart/form-data with one file, stdlib only."""
    boundary = uuid.uuid4().hex
    chunks = []
    for name, value in fields.items():
        chunks.append(
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f'{value}\r\n'.encode()
        )
    filename = os.path.basename(file_path)
    ctype, _ = mimetypes.guess_type(file_path)
    chunks.append(
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f'Content-Type: {ctype or "application/octet-stream"}\r\n\r\n'.encode()
    )
    with open(file_path, "rb") as f:
        chunks.append(f.read())
    chunks.append(f'\r\n--{boundary}--\r\n'.encode())
    data = b"".join(chunks)
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def send_telegram_document(token: str, chat_id: int, file_path: str,
                           caption: str = None) -> dict:
    fields = {"chat_id": str(chat_id)}
    if caption:
        fields["caption"] = caption[:1024]
    return _multipart_post(
        f"https://api.telegram.org/bot{token}/sendDocument",
        fields, "document", file_path,
    )


def send_telegram_audio(token: str, chat_id: int, file_path: str,
                        caption: str = None) -> dict:
    """Sends an audio file (voice-note style reply)."""
    fields = {"chat_id": str(chat_id)}
    if caption:
        fields["caption"] = caption[:1024]
    return _multipart_post(
        f"https://api.telegram.org/bot{token}/sendAudio",
        fields, "audio", file_path,
    )


def resolve_send_path(file_path: str) -> str | None:
    """Resolves a brain-supplied path: absolute as-is, otherwise relative to Download."""
    p = os.path.expanduser(file_path or "")
    if not p:
        return None
    if not os.path.isabs(p):
        p = os.path.join(DOWNLOADS_DIR, p)
    return p if os.path.isfile(p) else None


def send_telegram_file(file_path: str, caption: str = None) -> str:
    """Sends a local file (PDF, image, document, anything) to the user via Telegram.

    file_path can be absolute, or relative to the Download folder (as returned
    by search_download_files). Only works inside a Telegram chat session.
    """
    if not _bot_token or not _chat_id:
        return ("Telegram file sending is only available inside a Telegram "
                "chat session.")
    resolved = resolve_send_path(file_path)
    if not resolved:
        return (f"File not found: '{file_path}'. Use search_download_files "
                "to locate it first.")
    if os.path.getsize(resolved) > _MAX_FILE_BYTES:
        return (f"'{os.path.basename(resolved)}' is over Telegram's 50MB "
                "bot limit and cannot be sent.")
    try:
        send_telegram_document(_bot_token, _chat_id, resolved, caption)
        return f"Sent '{os.path.basename(resolved)}' to you via Telegram."
    except Exception as e:
        return f"Failed to send file via Telegram: {e}"


__all__ = ["configure_telegram", "clear_telegram", "send_telegram_file",
           "send_telegram_document", "send_telegram_audio", "resolve_send_path"]
