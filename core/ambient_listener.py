# core/ambient_listener.py
"""Always-on microphone capture that feeds transcribed text to the controller."""
import time


class SpeakingGate:
    """True while Mavis is talking and for a short tail afterwards, so she never transcribes herself."""

    def __init__(self, busy_fn, tail_seconds: float = 2.0, clock=time.monotonic):
        self._busy_fn = busy_fn
        self._tail = tail_seconds
        self._clock = clock
        self._last_speech = None

    def mark_speech_end(self) -> None:
        self._last_speech = self._clock()

    def is_speaking(self) -> bool:
        if self._busy_fn():
            self._last_speech = self._clock()
            return True
        return self._last_speech is not None and (self._clock() - self._last_speech) < self._tail


def transcribe_google(recognizer, audio):
    """The one place Google STT is called; swap this function to change engines."""
    import speech_recognition as sr
    try:
        return recognizer.recognize_google(audio)
    except sr.UnknownValueError:
        return None
    except sr.RequestError:
        print("\n[Ambient: STT service unreachable.]")
        return None


class AmbientListener:
    def __init__(self, transcribe, gate, is_paused, on_text):
        self._transcribe = transcribe
        self._gate = gate
        self._is_paused = is_paused
        self._on_text = on_text
        self._stop_fn = None

    def handle_audio(self, recognizer, audio) -> None:
        """Callback for listen_in_background. Runs on the recognizer's own thread."""
        # Checked before transcribing so paused/echo audio is never sent to the STT service.
        if self._gate.is_speaking() or self._is_paused():
            return
        try:
            text = self._transcribe(recognizer, audio)
        except Exception as e:
            print(f"\n[Ambient STT error: {e}]")
            return
        if text and text.strip():
            self._on_text(text.strip())

    def start(self, recognizer, microphone, phrase_time_limit: float = 12) -> None:
        self._stop_fn = recognizer.listen_in_background(
            microphone, self.handle_audio, phrase_time_limit=phrase_time_limit)

    def stop(self) -> None:
        if self._stop_fn:
            self._stop_fn(wait_for_stop=False)
            self._stop_fn = None
