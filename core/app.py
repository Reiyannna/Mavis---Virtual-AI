"""Application factory: builds Mavis's core stack in exactly one place.

Both front-ends (desktop main.py and telegram_bot.py) come through here,
so brain / voice / monitors / controller wiring never gets copy-pasted
into a second or third entry point.
"""
import queue
from types import SimpleNamespace


class NullVoice:
    """Headless voice: prints instead of speaking. For front-ends with no audio."""

    is_muted = True
    ambient_paused = True  # no microphone in headless mode

    def speak(self, text, force_speak=False):
        print(f"Mavis: {text}")

    def wait_until_done(self):
        pass

    def is_speaking(self):
        return False

    def set_ambient_paused(self, paused):
        pass

    def start_ambient(self, on_text):
        pass

    def stop_ambient(self):
        pass


class NullAvatar:
    def set_state(self, state):
        pass


def create_stack(avatar=None, voice=True, ambient=True, greet=True,
                 typed_queue=None):
    """Builds and wires the full Mavis stack.

    avatar      - GUI avatar object (None = headless)
    voice       - True for real TTS/STT, False for print-only NullVoice
    ambient     - start the always-on microphone listener
    greet       - speak the "System online" greeting
    typed_queue - queue for typed commands (a fresh one is made if omitted)

    Returns a SimpleNamespace with: voice, brain, alarms, conscience,
    router, buffer, evaluator, controller, text_queue, typed_queue.
    """
    # Heavy imports live here so this module stays importable anywhere.
    from core.brain import MavisBrain
    from core.alarm_monitor import AlarmManager
    from core.conscience_monitor import ConscienceManager
    from core.ambient_router import AmbientRouter, BackgroundBuffer
    from core.memory_graph import MemoryGraph
    from core.batch_evaluator import BatchEvaluator
    from core.controller import MavisController

    print("Initializing Mavis Master System...")

    brain = MavisBrain()
    if voice:
        from core.voice_engine import MavisVoice
        voice_obj = MavisVoice()
    else:
        voice_obj = NullVoice()
    avatar_obj = avatar or NullAvatar()

    alarms = AlarmManager(voice_obj)
    alarms.start_monitor()

    conscience = ConscienceManager(voice_obj, brain, alarms)
    conscience.start_monitor()

    router = AmbientRouter()
    buffer = BackgroundBuffer()
    evaluator = BatchEvaluator(MemoryGraph(), buffer, brain.evaluate_batch)
    evaluator.start()

    text_queue = queue.Queue()
    controller = MavisController(
        voice_obj, brain, avatar_obj, alarms, router, buffer,
        text_queue,
        typed_queue if typed_queue is not None else queue.Queue(),
    )

    if greet:
        avatar_obj.set_state("talking")
        voice_obj.speak("System online. Awaiting authorization.")
        voice_obj.wait_until_done()
        avatar_obj.set_state("idle")
        print("\nMavis: Please state authorization to verify your identity.")

    if ambient:
        voice_obj.start_ambient(text_queue.put)
        print("[System: Ambient listening ACTIVE. Say 'Mavis' to give a command. "
              "Ctrl+Shift+L pauses listening.]")

    return SimpleNamespace(
        voice=voice_obj,
        brain=brain,
        alarms=alarms,
        conscience=conscience,
        router=router,
        buffer=buffer,
        evaluator=evaluator,
        controller=controller,
        text_queue=text_queue,
        typed_queue=controller.typed_queue,
    )
