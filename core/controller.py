import os
import queue
import re

from core.ambient_router import AmbientRouter, BackgroundBuffer

EXIT_CMDS = {"exit", "goodbye"}
MUTE_CMDS = {"mute", "silence", "be quiet"}
UNMUTE_CMDS = {"unmute", "speak", "voice on"}
LOCK_CMDS = {"lockdown", "quit"}
SLEEP_CMDS = {"go to sleep", "sleep", "dismissed"}
PAUSE_CMDS = {"stop listening", "pause listening"}
RESUME_CMDS = {"resume listening", "start listening"}


class MavisController:
    """Routes ambient speech: wake-word utterances run as commands, everything else is buffered."""

    def __init__(self, voice, brain, avatar, alarms, router, buffer,
                 text_queue, typed_queue, exit_fn=lambda: os._exit(0)):
        self.voice, self.brain, self.avatar, self.alarms = voice, brain, avatar, alarms
        self.router, self.buffer = router, buffer
        self.text_queue, self.typed_queue = text_queue, typed_queue
        self._exit = exit_fn

    def _say(self, text):
        self.avatar.set_state("talking")
        try:
            self.voice.speak(text)
            # speak() returns immediately (audio plays in the background);
            # keep the 'talking' state until she has actually finished.
            self.voice.wait_until_done()
        finally:
            self.avatar.set_state("idle")

    @staticmethod
    def _split_sentences(text):
        """Splits text into sentences, keeping each sentence's punctuation."""
        parts = re.split(r'([.!?…]+["\'\s]*)', text)
        sents = []
        i = 0
        while i < len(parts):
            sent = (parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")).strip()
            if sent:
                sents.append(sent)
            i += 2
        return sents

    def _respond(self, command):
        """Streams the brain's answer: each finished sentence is spoken as
        soon as it arrives instead of waiting for the whole reply."""
        self.avatar.set_state("talking")
        buf = [""]
        streamed = [False]
        spoken = set()  # normalized sentences already said this turn
        try:
            def say_unique(text):
                # Speak each sentence at most once per turn. The model
                # sometimes re-narrates a paragraph it already said
                # (e.g. a startup briefing), possibly with slight
                # rewording of one line, so dedup is per sentence —
                # not just for exact consecutive repeats.
                fresh = []
                for sent in self._split_sentences(text):
                    norm = " ".join(sent.lower().split())
                    if norm and norm not in spoken:
                        spoken.add(norm)
                        fresh.append(sent)
                if fresh:
                    self.voice.speak(" ".join(fresh))

            def on_chunk(t):
                clean = self.brain._sanitize_output(t)
                if not clean:
                    return
                streamed[0] = True
                buf[0] += clean
                text = buf[0]
                end = -1
                for m in re.finditer(r'[.!?…][\s"\']', text):
                    end = m.end()
                if end > 0:
                    sentence = text[:end].strip()
                    buf[0] = text[end:].strip()
                    if sentence:
                        say_unique(sentence)
            reply = self.brain.process_input(command, on_text_chunk=on_chunk)
            tail = self.brain._sanitize_output(buf[0]).strip()
            if tail:
                say_unique(tail)
            elif not streamed[0] and (reply or "").strip():
                # nothing streamed (short/denied reply): speak it whole
                say_unique(reply)
            self.voice.wait_until_done()
        finally:
            self.avatar.set_state("idle")

    def _handle_command(self, command, typed=False):
        print(f"You (Typed): {command}" if typed else f"You: {command}")
        cmd = command.strip().lower().strip(".,!?")
        # Tell the alarm/conscience threads not to talk over us while we handle this.
        self.alarms.set_conversing(True)
        try:
            if cmd in EXIT_CMDS:
                self._say("Shutting down systems. Goodbye, Rey.")
                self._exit()
            elif cmd in MUTE_CMDS:
                self.voice.is_muted = True
                print("[System: Mavis Audio is now MUTED (Text Only)]")
            elif cmd in UNMUTE_CMDS:
                self.voice.is_muted = False
                print("[System: Mavis Audio is now UNMUTED (Voice Active)]")
            elif cmd in LOCK_CMDS:
                self.brain.is_authenticated = False
                self._say("Lockdown initiated. Please state authorization.")
                print("Mavis: Lockdown initiated. Please state authorization to verify your identity.\n")
            elif cmd in SLEEP_CMDS:
                self._say("Standing by.")
            elif cmd in PAUSE_CMDS:
                self.voice.set_ambient_paused(True)
                self._say("Ambient listening paused.")
            elif cmd in RESUME_CMDS:
                self.voice.set_ambient_paused(False)
                self._say("Ambient listening resumed.")
            else:
                self._respond(command)
                # Let the conversation continue for a few seconds without repeating her name.
                self.router.open_followup()
        finally:
            self.alarms.set_conversing(False)

    def step(self, timeout=0.2):
        """Handle at most one item. Returns what happened, or None if idle."""
        self.router.set_paused(self.voice.ambient_paused)

        try:
            typed = self.typed_queue.get_nowait()
        except queue.Empty:
            typed = None
        if typed:
            self._handle_command(typed, typed=True)
            return "typed"

        try:
            text = self.text_queue.get(timeout=timeout)
        except queue.Empty:
            return None

        route = self.router.route(text)
        if route.kind == "command":
            self._handle_command(route.text)
        elif route.kind == "wake_only":
            self._say("Yes?")
            # Restart the window now that she has finished speaking (TTS can take seconds).
            self.router.open_followup()
        elif route.kind == "background" and self.brain.is_authenticated:
            # Only record background speech once the user has unlocked Mavis.
            self.buffer.add(route.text)
        return route.kind


def run_mavis_backend(avatar_app, command_queue):
    """Legacy entry point: builds the stack via core.app and pumps the controller."""
    import os
    from core.app import create_stack

    stack = create_stack(avatar=avatar_app, typed_queue=command_queue,
                         voice=True, ambient=True, greet=True)
    while True:
        try:
            stack.controller.step()
        except KeyboardInterrupt:
            print("\nExiting Mavis system...")
            os._exit(0)
        except Exception as e:
            print(f"System Error: {e}")
