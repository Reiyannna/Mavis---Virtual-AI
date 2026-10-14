import os
import threading
import time
import json
import random
from core.settings import ALARM_FILE, ensure_brain_dir
from datetime import datetime

class AlarmManager:
    def __init__(self, voice):
        self.voice = voice
        self.is_conversing = False
        ensure_brain_dir()
        self.alarm_file = ALARM_FILE
        
    def start_monitor(self):
        """Starts the background alarm thread."""
        thread = threading.Thread(target=self._monitor_loop, daemon=True)
        thread.start()
        
    def set_conversing(self, state: bool):
        """Updates the conversation state so Mavis knows if she can interrupt."""
        self.is_conversing = state
        
    def _monitor_loop(self):
        """Background loop that checks for due alarms every 10 seconds."""
        intros = [
            "Hey Rey, sorry to interrupt, but ",
            "Just a quick heads up, Rey. ",
            "Excuse me Rey, I have a reminder for you: ",
            "Rey, your alarm is going off. "
        ]
        
        while True:
            time.sleep(5) # Check slightly faster
            if self.is_conversing:
                continue
                
            if not os.path.exists(self.alarm_file):
                continue
                
            try:
                with open(self.alarm_file, "r") as f:
                    alarms = json.load(f)
                    
                now = datetime.now()
                updated_alarms = []
                triggered = []
                
                for a in alarms:
                    alarm_time = datetime.strptime(a["time"], "%Y-%m-%d %H:%M:%S")
                    if now >= alarm_time:
                        triggered.append(a)
                    else:
                        updated_alarms.append(a)
                        
                if triggered:
                    # Save the list back without the triggered alarms
                    with open(self.alarm_file, "w") as f:
                        json.dump(updated_alarms, f, indent=4)
                        
                    for a in triggered:
                        while self.is_conversing:
                            time.sleep(2)
                        print(f"\n[System: Triggering Alarm ID {a['id']}]")
                        self.voice.speak(random.choice(intros) + a["message"], force_speak=True)
            except Exception as e:
                print(f"\n[Alarm Monitor Error: {e}]")