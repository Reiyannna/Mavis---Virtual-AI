# main.py
"""Desktop entry point: tkinter avatar + full voice stack in a backend thread."""
import os
import queue
import threading
import tkinter as tk

from core.app import create_stack
from core.avatar import MavisAvatar


def _backend_loop(stack):
    while True:
        try:
            stack.controller.step()
        except KeyboardInterrupt:
            print("\nExiting Mavis system...")
            os._exit(0)
        except Exception as e:
            print(f"System Error: {e}")


if __name__ == "__main__":
    provider = os.environ.get("MAVIS_LLM_PROVIDER", "gemini").lower()
    if provider != "ollama" and not os.environ.get("GEMINI_API_KEY"):
        print("Error: GEMINI_API_KEY environment variable not found.")
        print("Or set MAVIS_LLM_PROVIDER=ollama to use a local model instead.")
        exit(1)

    cmd_queue = queue.Queue()
    root = tk.Tk()
    app = MavisAvatar(root, cmd_queue)

    stack = create_stack(avatar=app, typed_queue=cmd_queue,
                         voice=True, ambient=True, greet=True)

    backend_thread = threading.Thread(target=_backend_loop, args=(stack,),
                                      daemon=True)
    backend_thread.start()

    root.mainloop()
