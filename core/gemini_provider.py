"""Gemini backend for Mavis, behind the neutral provider interface.

The brain only depends on:
  - send_message_stream(message) -> yields Chunk(text, function_calls)
      message is either a str (user text) or a list of
      {"name": tool_name, "result": result_text} (tool responses).
  - generate_one_shot(prompt) -> str
  - history_len() -> int
  - trim_history(keep_last) -> None
"""
from google import genai
from google.genai import types


class Chunk:
    def __init__(self, text="", function_calls=None):
        self.text = text or ""
        self.function_calls = function_calls or []


class Call:
    def __init__(self, name, args):
        self.name = name
        self.args = args or {}


def _safe_text(response):
    """Concatenates text parts manually instead of using response.text,
    which logs a noisy SDK warning whenever function calls are present."""
    try:
        parts = []
        for cand in getattr(response, "candidates", []) or []:
            content = getattr(cand, "content", None)
            for part in getattr(content, "parts", []) or []:
                t = getattr(part, "text", None)
                if t:
                    parts.append(t)
        return "".join(parts)
    except Exception:
        return ""


class GeminiChat:
    def __init__(self, api_key, model_id, system_prompt, tools):
        self.client = genai.Client(api_key=api_key)
        self.model_id = model_id
        self.system_prompt = system_prompt
        self.tools = tools
        self._new_chat()

    def _new_chat(self, history=None):
        self.chat = self.client.chats.create(
            model=self.model_id,
            config=types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                temperature=0.7,
                tools=self.tools,
            ),
            history=history,
        )

    def send_message_stream(self, message):
        if isinstance(message, str):
            content = message
        else:
            content = [
                types.Part.from_function_response(
                    name=m["name"], response={"result": m["result"]}
                )
                for m in message
            ]
        stream_fn = getattr(self.chat, "send_message_stream", None)
        if stream_fn is None:
            # older SDK: fall back to a single non-streamed call
            resp = self.chat.send_message(content)
            yield Chunk(
                _safe_text(resp),
                [Call(fc.name, fc.args or {}) for fc in resp.function_calls or []],
            )
            return
        for ch in stream_fn(content):
            calls = [Call(fc.name, fc.args or {}) for fc in ch.function_calls or []]
            yield Chunk(_safe_text(ch), calls)

    def generate_one_shot(self, prompt):
        response = self.client.models.generate_content(
            model=self.model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
        return _safe_text(response)

    def generate_text_one_shot(self, prompt):
        """Stateless plain-text call: no tools, no JSON forcing. For background
        judgments (like conscience ticks) that don't need function calling."""
        response = self.client.models.generate_content(
            model=self.model_id,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2),
        )
        return _safe_text(response)

    def history_len(self):
        try:
            return len(self.chat.get_history())
        except Exception:
            return 0

    def trim_history(self, keep_last):
        history = self.chat.get_history()
        if len(history) <= keep_last:
            return
        print("\n[System: trimming oldest conversation history to stay within context limits...]")
        cutoff_index = len(history) - keep_last
        while cutoff_index > 0:
            content = history[cutoff_index]
            if content.role == 'user':
                has_func_resp = False
                if hasattr(content, 'parts') and content.parts:
                    for part in content.parts:
                        if getattr(part, 'function_response', None) is not None:
                            has_func_resp = True
                            break
                if not has_func_resp:
                    break
            cutoff_index -= 1
        self._new_chat(history=history[cutoff_index:])
