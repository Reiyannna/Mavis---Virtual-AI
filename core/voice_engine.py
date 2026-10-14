import os
import asyncio
import edge_tts
import pygame
import speech_recognition as sr
import keyboard
import threading
import time
import queue
import re
import glob
from concurrent.futures import ThreadPoolExecutor
from core.ambient_listener import AmbientListener, SpeakingGate, transcribe_google

# --- speech pipeline tuning ---
_TTS_TIMEOUT = 20      # seconds: never let one TTS request stall longer than this
_TTS_RETRIES = 1       # one retry per chunk, then the chunk is skipped
_MAX_TTS_FAILURES = 2  # abort the whole utterance after this many consecutive chunk failures
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?…])\s+')
_MAX_CHUNK_CHARS = 220

# Offline TTS fallback (pyttsx3): used only when edge-tts is unreachable.
_pyttsx3_lock = threading.Lock()
_pyttsx3_engine = None
_pyttsx3_missing_warned = False

if os.name == 'nt':
    # edge-tts/aiohttp stalls far less on Windows with the selector event loop
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass


def synthesize_to_file(text: str, output_path: str,
                       voice: str = "en-GB-MaisieNeural",
                       timeout: int = 60) -> str | None:
    """Synthesizes text to an mp3 file WITHOUT playback (for voice notes etc).

    Returns output_path on success, None on failure.
    """
    async def _gen():
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)

    try:
        asyncio.run(asyncio.wait_for(_gen(), timeout=timeout))
        return output_path if os.path.exists(output_path) else None
    except Exception as e:
        print(f"[Voice Engine: file synthesis failed: {e}]")
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
        except Exception:
            pass
        return None


class MavisVoice:
    def __init__(self, voice="en-GB-MaisieNeural"):
        self.voice = voice
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = 3.0
        pygame.mixer.init()

        self.stop_speaking = False
        self.is_muted = False  # Mute state tracker

        keyboard.on_press_key("space", self._interrupt_audio)
        keyboard.add_hotkey("ctrl+m", self._toggle_mute)  # Hotkey to toggle mute

        # --- Ambient (always-on) mode ---
        self.ambient_paused = False
        self._gate = SpeakingGate(pygame.mixer.music.get_busy, tail_seconds=2.0)
        self._ambient = None
        keyboard.add_hotkey("ctrl+shift+l", self.toggle_ambient_pause)

        # --- Speech pipeline: speak() only enqueues; one daemon thread owns
        # --- pygame and plays sentence-by-sentence so the first audio starts
        # --- in seconds instead of after the whole reply is synthesized.
        self._speak_queue = queue.Queue()
        self._tts_pool = ThreadPoolExecutor(max_workers=2,
                                            thread_name_prefix="mavis-tts")
        self._job_counter = 0
        self._speaker_thread = threading.Thread(target=self._speaker_loop,
                                                name="mavis-speaker",
                                                daemon=True)
        self._speaker_thread.start()

    def is_speaking(self):
        """True while Mavis is talking (plus a short tail), used to ignore her own echo."""
        return self._gate.is_speaking()

    def set_ambient_paused(self, paused):
        self.ambient_paused = paused
        state = "PAUSED (not listening)" if paused else "ACTIVE (listening)"
        print(f"\n[System: Ambient listening is now {state}]")

    def toggle_ambient_pause(self, event=None):
        self.set_ambient_paused(not self.ambient_paused)

    def start_ambient(self, on_text):
        """Starts non-blocking background capture; each transcribed phrase goes to on_text(str)."""
        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 1.0  # split phrases quickly (the command recognizer waits 3s)
        microphone = sr.Microphone()
        with microphone as source:
            recognizer.adjust_for_ambient_noise(source, duration=1)
        self._ambient = AmbientListener(
            transcribe_google, self._gate, lambda: self.ambient_paused, on_text)
        self._ambient.start(recognizer, microphone, phrase_time_limit=12)

    def stop_ambient(self):
        if self._ambient:
            self._ambient.stop()
            self._ambient = None

    def _toggle_mute(self, event=None):
        """Toggles the voice on and off instantly when 'M' is pressed."""
        self.is_muted = not self.is_muted
        state = "MUTED (Text Only)" if self.is_muted else "UNMUTED (Voice Active)"
        print(f"\n[System: Mavis Audio is now {state}]")

    def _interrupt_audio(self, event=None):
        """Immediately stops the TTS audio playback."""
        if pygame.mixer.music.get_busy():
            print("\n[System: Audio interrupted by User]")
            pygame.mixer.music.stop()
            self.stop_speaking = True

    async def _generate_audio(self, text, output_file):
        communicate = edge_tts.Communicate(text, self.voice)
        await communicate.save(output_file)

    # ------------------------------------------------------------------
    # speech pipeline
    # ------------------------------------------------------------------

    def speak(self, text, force_speak=False):
        """Prints immediately and queues the audio. Returns at once; the
        speaker thread synthesizes sentence-by-sentence in the background.
        force_speak allows alarms to bypass the mute toggle."""
        print(f"Mavis: {text}")

        # If muted and this isn't a forced alarm, skip the audio entirely
        if self.is_muted and not force_speak:
            return
        if not (text or "").strip():
            return
        self._speak_queue.put((text, force_speak))

    def wait_until_done(self):
        """Blocks until queued speech has finished playing. Used by the
        controller so the avatar 'talking' state still tracks real speech."""
        self._speak_queue.join()
        while pygame.mixer.music.get_busy():
            if self.stop_speaking:
                break
            time.sleep(0.05)

    def _speaker_loop(self):
        """Owns pygame. Plays queued utterances one at a time, forever."""
        while True:
            text, _force_speak = self._speak_queue.get()
            try:
                self._speak_job(text)
            except Exception as e:
                print(f"[Voice Engine Error: {e}]")
            finally:
                self._gate.mark_speech_end()
                self._speak_queue.task_done()

    @staticmethod
    def _split_sentences(text):
        parts = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
        chunks = []
        for s in parts:
            while len(s) > _MAX_CHUNK_CHARS:
                cut = s.rfind(',', 0, _MAX_CHUNK_CHARS)
                if cut <= 80:
                    cut = s.rfind(' ', 0, _MAX_CHUNK_CHARS)
                if cut <= 80:
                    cut = _MAX_CHUNK_CHARS
                chunks.append(s[:cut].strip())
                s = s[cut:].strip()
            if s:
                chunks.append(s)
        return chunks

    def _generate_chunk(self, text, job_id, index):
        """Synthesizes one sentence to mp3 with a hard timeout. Returns the
        file path, or None if it failed / was interrupted."""
        path = f"temp_mavis_voice_{job_id}_{index}.mp3"
        for attempt in range(_TTS_RETRIES + 1):
            if self.stop_speaking:
                return None
            try:
                asyncio.run(asyncio.wait_for(
                    self._generate_audio(text, path), timeout=_TTS_TIMEOUT))
                return path
            except Exception as e:
                print(f"[Voice Engine: TTS chunk {index} failed "
                      f"(attempt {attempt + 1}): {e}]")
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass
        # edge-tts is unreachable: fall back to the offline voice
        return self._generate_chunk_offline(text, job_id, index)

    def _generate_chunk_offline(self, text, job_id, index):
        """Offline fallback via pyttsx3 (free, no network). Returns a wav path
        or None. Install with: pip install pyttsx3"""
        global _pyttsx3_engine, _pyttsx3_missing_warned
        try:
            import pyttsx3
        except ImportError:
            if not _pyttsx3_missing_warned:
                _pyttsx3_missing_warned = True
                print("[Voice Engine: edge-tts unreachable and pyttsx3 is not "
                      "installed. Run: pip install pyttsx3")
                print(" for an offline fallback voice.]")
            return None
        path = f"temp_mavis_voice_{job_id}_{index}_offline.wav"
        try:
            with _pyttsx3_lock:
                if _pyttsx3_engine is None:
                    _pyttsx3_engine = pyttsx3.init()
                    _pyttsx3_engine.setProperty('rate', 175)
                _pyttsx3_engine.save_to_file(text, path)
                _pyttsx3_engine.runAndWait()
            if os.path.exists(path) and not self.stop_speaking:
                print(f"[Voice Engine: chunk {index} spoken with offline voice.]")
                return path
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
            return None
        except Exception as e:
            print(f"[Voice Engine: offline TTS failed: {e}]")
            return None

    def _speak_job(self, text):
        """Plays one utterance: each sentence is synthesized (with the next
        one pre-generating while the current plays) and spoken as soon as
        it is ready."""
        self._job_counter += 1
        job_id = self._job_counter
        self.stop_speaking = False
        chunks = self._split_sentences(text)
        if not chunks:
            return

        clock = pygame.time.Clock()
        produced = []
        produced_lock = threading.Lock()
        futures = {}
        job_done = threading.Event()

        def gen_task(i):
            if self.stop_speaking or job_done.is_set():
                return None
            path = self._generate_chunk(chunks[i], job_id, i)
            if path:
                if job_done.is_set():
                    # job already finished; delete instead of leaking
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                    return None
                with produced_lock:
                    produced.append(path)
            return path

        def ensure(i):
            if i < len(chunks) and i not in futures and not self.stop_speaking:
                futures[i] = self._tts_pool.submit(gen_task, i)

        try:
            ensure(0)
            failures = 0
            i = 0
            while i < len(chunks):
                if self.stop_speaking:
                    break
                ensure(i + 1)  # synthesize the next sentence while this one plays
                path = futures[i].result()
                if not path:
                    failures += 1
                    if failures >= _MAX_TTS_FAILURES:
                        print("[Voice Engine: too many TTS failures, "
                              "skipping the rest of this utterance.]")
                        break
                    i += 1
                    continue
                failures = 0
                try:
                    pygame.mixer.music.load(path)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():
                        if self.stop_speaking:
                            pygame.mixer.music.stop()
                            break
                        clock.tick(10)
                finally:
                    try:
                        pygame.mixer.music.unload()
                    except Exception:
                        pass
                i += 1
        finally:
            job_done.set()
            for fut in futures.values():
                fut.cancel()
            # sweep by name pattern too, so late-finishing chunks can't leak
            with produced_lock:
                leftovers = list(produced)
            for f in leftovers + glob.glob(f"temp_mavis_voice_{job_id}_*.mp3"):
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except Exception:
                    pass

    def listen_for_wake_word(self, wake_word="mavis"):
        if pygame.mixer.music.get_busy():
            time.sleep(1)
            return False

        with sr.Microphone() as source:
            print(f"Waiting for wake word: '{wake_word}'...")
            self.recognizer.adjust_for_ambient_noise(source, duration=1)
            try:
                audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=3)
                text = self.recognizer.recognize_google(audio).lower()
                if wake_word in text:
                    return True
            except (sr.WaitTimeoutError, sr.UnknownValueError):
                pass
            except sr.RequestError:
                print("Network error. STT service unreachable.")
        return False

    def listen_command(self):
        with sr.Microphone() as source:
            print("Listening for command...")
            try:
                audio = self.recognizer.listen(source, timeout=None, phrase_time_limit=None)
                command = self.recognizer.recognize_google(audio)
                print(f"You: {command}")
                return command
            except sr.UnknownValueError:
                print("[System: Unrecognized background noise ignored.]")
                return None
            except sr.WaitTimeoutError:
                return None
