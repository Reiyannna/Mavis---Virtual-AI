"""Ollama backend for Mavis — the zero-cost local brain.

No new dependencies: talks to Ollama over plain HTTP (http://localhost:11434
by default). Tool schemas are generated from the Python tool functions'
signatures and docstrings.

Setup on Rey's machine:
  1. Install Ollama from https://ollama.com and run it.
  2. Pull a tool-capable model, e.g.:  ollama pull qwen2.5:7b
  3. set MAVIS_LLM_PROVIDER=ollama   (and optionally OLLAMA_MODEL=qwen2.5:7b)

Implements the same neutral interface as gemini_provider.GeminiChat.
"""
import inspect
import json
import os
import urllib.request
import urllib.error

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


class Chunk:
    def __init__(self, text="", function_calls=None):
        self.text = text or ""
        self.function_calls = function_calls or []


class Call:
    def __init__(self, name, args):
        self.name = name
        self.args = args or {}


def schema_for_tool(fn):
    """Builds an OpenAI-style function schema from a Python tool function."""
    sig = inspect.signature(fn)
    properties = {}
    required = []
    for name, param in sig.parameters.items():
        ann = param.annotation if param.annotation is not inspect.Parameter.empty else str
        properties[name] = {"type": _TYPE_MAP.get(ann, "string")}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    doc = (fn.__doc__ or "").strip().split("\n")[0]
    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": doc,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


class OllamaChat:
    def __init__(self, system_prompt, tools):
        self.model = OLLAMA_MODEL
        self.tool_schemas = [schema_for_tool(t) for t in tools]
        self.messages = [{"role": "system", "content": system_prompt}]
        self._check_connection()

    # -- plumbing ------------------------------------------------------

    def _check_connection(self):
        try:
            req = urllib.request.Request(
                OLLAMA_HOST + "/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            raise RuntimeError(
                f"Cannot reach Ollama at {OLLAMA_HOST} ({e}). "
                "Is Ollama installed and running? Unset MAVIS_LLM_PROVIDER "
                "to fall back to Gemini."
            )
        models = [m.get("name", "") for m in data.get("models", [])]
        if not any(self.model in m or m in self.model for m in models):
            print(f"[System: Ollama model '{self.model}' not found locally. "
                  f"Run: ollama pull {self.model}]")

    def _post_chat(self, stream):
        payload = {
            "model": self.model,
            "messages": self.messages,
            "tools": self.tool_schemas,
            "stream": stream,
        }
        req = urllib.request.Request(
            OLLAMA_HOST + "/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return urllib.request.urlopen(req, timeout=600)

    # -- provider interface --------------------------------------------

    def send_message_stream(self, message):
        if isinstance(message, str):
            self.messages.append({"role": "user", "content": message})
        else:
            for m in message:
                self.messages.append({
                    "role": "tool",
                    "content": m["result"],
                    "name": m["name"],
                })
        calls = []
        try:
            with self._post_chat(stream=True) as resp:
                for raw in resp:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    msg = obj.get("message", {})
                    content = msg.get("content") or ""
                    if content:
                        yield Chunk(content, [])
                    for tc in msg.get("tool_calls") or []:
                        fn = tc.get("function", {}) or {}
                        args = fn.get("arguments") or {}
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                args = {}
                        calls.append(Call(fn.get("name"), args))
                    if obj.get("done"):
                        break
        except urllib.error.URLError as e:
            raise RuntimeError(f"Ollama request failed: {e}")
        # record what the assistant said/did this turn
        self.messages.append({"role": "assistant", "content": ""})
        if calls:
            yield Chunk("", calls)

    def generate_one_shot(self, prompt):
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        req = urllib.request.Request(
            OLLAMA_HOST + "/api/generate",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode()).get("response", "")

    def generate_text_one_shot(self, prompt):
        """Stateless plain-text call: no tools. For background judgments."""
        return self.generate_one_shot(prompt)

    def history_len(self):
        return len(self.messages)

    def trim_history(self, keep_last):
        # keep the system prompt + the most recent messages
        if len(self.messages) <= keep_last + 1:
            return
        print("\n[System: trimming oldest conversation history to stay within context limits...]")
        self.messages = [self.messages[0]] + self.messages[-keep_last:]
