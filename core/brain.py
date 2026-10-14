import json
import os
import threading
import time

# Centralized imports from tools/registry.py
from tools.registry import MAVIS_TOOLS_LIST, MAVIS_TOOL_MAP
from core.prompts import MAVIS_SYSTEM_PROMPT
from core.auth import contains_password

# Zero-cost option: MAVIS_LLM_PROVIDER=ollama runs the brain on a local model
# (needs Ollama installed + a pulled model). Default stays Gemini.
PROVIDER = os.environ.get("MAVIS_LLM_PROVIDER", "gemini").lower()

# Tool results are capped before going back to the model so one giant
# Gmail/Drive dump can't flood her context or burn the free-tier quota.
_MAX_TOOL_RESULT_CHARS = 6000
_MAX_TOOL_ROUNDS = 5


def _identity_key(tool_name, args):
    """Semantic idempotency key for side-effecting tools.

    Two calls with the same identity in one turn are the same action, even if
    the args differ slightly (e.g. a different caption on a resend). Returns
    None for tools where every call is distinct.
    """
    try:
        if tool_name == "send_telegram_file":
            from tools.telegram_tools import resolve_send_path
            raw = args.get("file_path", "") or ""
            path = resolve_send_path(raw) or raw
            return ("send_telegram_file",
                    os.path.normcase(os.path.abspath(str(path).strip())))
        if tool_name in ("send_email", "create_email_draft"):
            to = args.get("to", "")
            if isinstance(to, (list, tuple)):
                to = ",".join(to)
            return ("email_out", str(to).strip().lower(),
                    str(args.get("subject", "")).strip().lower())
        if tool_name == "reply_to_message":
            return ("reply", str(args.get("message_id", "")).strip())
        if tool_name == "forward_message":
            return ("forward", str(args.get("message_id", "")).strip(),
                    str(args.get("to", "")).strip().lower())
        if tool_name in ("send_draft", "send_email_draft"):
            return ("send_draft", str(args.get("draft_id", "")).strip())
        if tool_name == "create_calendar_event":
            return ("create_event", str(args.get("summary", "")).strip().lower(),
                    str(args.get("start_time", "")).strip())
        if tool_name == "create_event":
            return ("create_event", str(args.get("summary", "")).strip().lower(),
                    str(args.get("start", "")).strip())
    except Exception:
        return None
    return None


class MavisBrain:
    def __init__(self):
        self.is_authenticated = False
        self.teacher_mode = False
        self.system_prompt = MAVIS_SYSTEM_PROMPT
        self.model_id = 'gemini-3.5-flash-lite'

        # One live chat is shared by the user, the conscience thread and alarms: serialize it.
        self._chat_lock = threading.RLock()
        # Background batch analysis is stateless and has its own lock.
        self._eval_lock = threading.Lock()

        if PROVIDER == "ollama":
            from core.ollama_provider import OllamaChat
            self.chat = OllamaChat(self.system_prompt, MAVIS_TOOLS_LIST)
            print(f"[System: Brain provider = Ollama local model]")
        else:
            from core.gemini_provider import GeminiChat
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY environment variable not found.")
            self.chat = GeminiChat(api_key, self.model_id,
                                   self.system_prompt, MAVIS_TOOLS_LIST)
            print(f"[System: Brain provider = Gemini ({self.model_id})]")

    def _trim_memory(self):
        # Tool-call rounds grow history several entries per turn, so the
        # limits are generous: trim only when truly large.
        if self.chat.history_len() > 80:
            self.chat.trim_history(40)

    def _sanitize_output(self, text: str) -> str:
        """Strips out Markdown formatting symbols so they are never printed or spoken."""
        if not text:
            return ""
        return text.replace('*', '').replace('#', '').replace('`', '')

    @staticmethod
    def _truncate_tool_result(tool_name: str, result) -> str:
        text = result if isinstance(result, str) else str(result)
        if len(text) > _MAX_TOOL_RESULT_CHARS:
            return (text[:_MAX_TOOL_RESULT_CHARS]
                    + f"\n...[truncated {len(text) - _MAX_TOOL_RESULT_CHARS} chars "
                    f"of {tool_name} output]")
        return text

    def process_input(self, text: str, on_text_chunk=None) -> str:
        """on_text_chunk, when given, receives the final answer text so the
        caller can speak it sentence by sentence. Text from intermediate
        tool-call rounds is never delivered (the model tends to narrate a
        partial answer before its tools finish, then repeat it) — so the
        spoken answer is always exactly one clean pass."""
        if not self.is_authenticated:
            if contains_password(text):
                self.is_authenticated = True

                # --- TEACHER MODE TOGGLE ---
                if "enter teacher mode" in text.lower():
                    self.teacher_mode = True
                    return "Teacher Mode activated. I will now guide you using Socratic questions instead of giving direct answers."
                if "exit teacher mode" in text.lower():
                    self.teacher_mode = False
                    return "Teacher Mode disabled. I am back to providing direct answers and code generation."

                # Inject Teacher Mode instructions if active
                if self.teacher_mode:
                    text = "TEACHER MODE ACTIVE: Do not give me the direct code fix or answer. Act as a programming tutor. Read my code, point out where I should look, and ask me a guiding question so I can figure out the bug or concept myself. Here is my query: " + text

                # STRICT STARTUP ROUTINE
                text = (
                    "System Command: User 'Rey' has successfully authenticated. Execute these steps strictly: "
                    "1. Use get_current_time_and_date to ground yourself in the present. "
                    "2. Use check_alarms to see my active laptop alarms. "
                    "3. Use get_today_calendar_events and get_unread_emails. "
                    "4. Finally, speak your welcome greeting: read the actual snippets of my unread emails, state my active laptop alarms, and summarize today's calendar. Do NOT read from Obsidian memory."
                )
                print("\n[System: User authenticated. Running startup checks and memory pruning...]")
            else:
                return "Access denied. Please state authorization to verify your identity."

        return self._converse(text, on_text_chunk=on_text_chunk)

    def _converse(self, text: str, on_text_chunk=None) -> str:
        with self._chat_lock:
            return self._converse_locked(text, on_text_chunk=on_text_chunk)

    def _converse_locked(self, text: str, on_text_chunk=None) -> str:
        self._trim_memory()
        max_retries = 3
        backoff_seconds = 2

        pending = text  # str on round 1, then a list of tool-response dicts
        seen_calls = {}  # (tool_name, args_json) -> result; dedupes repeats per turn
        seen_idem = {}  # semantic identity -> result; stops double-sends/creates
        for _round in range(_MAX_TOOL_ROUNDS):
            stream = None
            for attempt in range(max_retries):
                try:
                    stream = self.chat.send_message_stream(pending)
                    # pull the first item now so connection errors surface here
                    stream = self._peekable(stream)
                    break
                except Exception as e:
                    err_msg = str(e)
                    if ("503" in err_msg or "UNAVAILABLE" in err_msg) and attempt < max_retries - 1:
                        time.sleep(backoff_seconds)
                        backoff_seconds *= 2
                        continue
                    return f"I encountered a problem processing that. {e}"
            if stream is None:
                return "I encountered a problem processing that."

            text_parts = []
            calls = []
            try:
                for chunk in stream:
                    if chunk.text:
                        text_parts.append(chunk.text)
                    for fc in chunk.function_calls or []:
                        calls.append(fc)
            except Exception as e:
                print(f"\n[System: response stream interrupted: {e}]")

            if not calls:
                # Final round: this is the actual answer. Voice it now,
                # exactly once. Chunks are delivered together so the
                # caller still splits them into spoken sentences.
                full = "".join(text_parts)
                if on_text_chunk and full:
                    try:
                        on_text_chunk(full)
                    except Exception:
                        pass
                return self._sanitize_output(full)

            # Intermediate round: the model often narrates a partial answer
            # ("Here is your update for today...") while its tool calls are
            # still in flight, then says it all again in the final round.
            # Never voice intermediate text — the [System: executing tool]
            # lines below already show progress on the console.

            # Execute EVERY requested tool call (not just the first one),
            # then feed all results back for the next round.
            # Exact-duplicate calls within one turn are NOT re-executed: the
            # earlier result is reused, so the model cannot burn API quota by
            # firing the same read two or three times in a row.
            responses = []
            for fc in calls:
                tool_name = fc.name
                args = fc.args or {}
                try:
                    dup_key = (tool_name,
                               json.dumps(args, sort_keys=True, default=str))
                except Exception:
                    dup_key = None
                idem_key = _identity_key(tool_name, args)
                if idem_key is not None and idem_key in seen_idem:
                    # Same side-effect already done this turn (maybe with
                    # slightly different args): do NOT do it twice.
                    tool_result = (seen_idem[idem_key] +
                                   " [Note: this was already completed earlier "
                                   "in this turn - it was not repeated.]")
                    print(f"\n[System: suppressing repeat {tool_name} "
                          f"(already done this turn)]")
                elif dup_key is not None and dup_key in seen_calls:
                    tool_result = seen_calls[dup_key]
                    print(f"\n[System: reusing earlier result for duplicate "
                          f"{tool_name} call]")
                else:
                    print(f"\n[System: Mavis is executing local tool -> {tool_name}]")
                    if tool_name in MAVIS_TOOL_MAP:
                        try:
                            tool_result = MAVIS_TOOL_MAP[tool_name](**args)
                        except Exception as e:
                            tool_result = f"Error executing tool: {e}"
                    else:
                        tool_result = f"Tool '{tool_name}' not found."
                    if dup_key is not None:
                        seen_calls[dup_key] = tool_result
                    if idem_key is not None:
                        seen_idem[idem_key] = tool_result
                responses.append({
                    "name": tool_name,
                    "result": self._truncate_tool_result(tool_name, tool_result),
                })
            pending = responses

        return "I ran into too many tool steps on that one. Could you ask it in a simpler way?"

    @staticmethod
    def _peekable(stream):
        """Wraps a generator so the first item is fetched eagerly (surfacing
        connection errors inside the retry loop) while staying iterable."""
        it = iter(stream)
        first = next(it)

        def gen():
            yield first
            yield from it

        return gen()

    def think(self, prompt: str) -> str:
        """One-shot, stateless, TOOLLESS judgment call. Never touches the live chat.
        For background decisions (conscience ticks) where the context is already
        in the prompt and function calling would just burn tokens."""
        with self._eval_lock:
            try:
                return self.chat.generate_text_one_shot(prompt) or ""
            except Exception as e:
                print(f"[System: background think failed: {e}]")
                return ""

    def evaluate_batch(self, prompt: str) -> str:
        """One-shot, stateless call used for background analysis. Never touches the live chat."""
        with self._eval_lock:
            try:
                return self.chat.generate_one_shot(prompt) or ""
            except Exception as e:
                print(f"[System: background evaluation failed: {e}]")
                return ""
