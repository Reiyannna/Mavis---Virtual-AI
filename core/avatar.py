import tkinter as tk
from PIL import Image, ImageTk
import os
import queue

class MavisAvatar:
    def __init__(self, root, command_queue):
        self.root = root
        self.command_queue = command_queue # Connects to main.py
        
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        
        self.trans_color = '#add123'
        self.root.config(bg=self.trans_color)
        self.root.attributes("-transparentcolor", self.trans_color)

        self.label = tk.Label(root, bg=self.trans_color)
        self.label.pack()

        # NEW: The hidden text entry box (appears below the GIF)
        self.text_var = tk.StringVar()
        self.entry = tk.Entry(root, textvariable=self.text_var, font=("Arial", 12), width=25, justify='center')

        self.idle_frames = self.load_frames('assets/mavis_idle.gif')
        self.talking_frames = self.load_frames('assets/mavis_talkingv2.gif')
        
        self.current_frames = self.idle_frames
        self.frame_idx = 0
        self.is_talking = False

        if self.current_frames:
            self.root.update_idletasks()
            img_width = self.current_frames[0].width()
            img_height = self.current_frames[0].height()
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            x = (screen_width // 2) - (img_width // 2)
            y = (screen_height // 2) - (img_height // 2)
            # Removed exact height/width constraint so the window expands when the text box appears
            self.root.geometry(f'+{x}+{y}')
        
        self.label.bind("<ButtonPress-1>", self.start_move)
        self.label.bind("<B1-Motion>", self.do_move)
        self.label.bind("<Button-3>", lambda e: root.quit())
        
        # NEW: Double-click to toggle text box, Enter to send command
        self.label.bind("<Double-Button-1>", self.toggle_textbox)
        self.entry.bind("<Return>", self.send_command)
        
        self.animate()

    def load_frames(self, filename):
        frames = []
        if not os.path.exists(filename):
            return frames
        try:
            img = Image.open(filename)
            for i in range(img.n_frames):
                img.seek(i)
                frames.append(ImageTk.PhotoImage(img.copy().convert('RGBA')))
        except Exception as e:
            print(f"Error loading {filename}: {e}")
        return frames
    
    def animate(self):
        if self.current_frames:
            self.frame_idx = (self.frame_idx + 1) % len(self.current_frames)
            self.label.config(image=self.current_frames[self.frame_idx])
        self.root.after(100, self.animate) 
        
    def start_move(self, event):
        self.x = event.x
        self.y = event.y

    def do_move(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")
        
    def set_state(self, state):
        if state == 'talking':
            self.current_frames = self.talking_frames
        else:
            self.current_frames = self.idle_frames
        self.frame_idx = 0

    # NEW: Toggle visibility of the text box
    def toggle_textbox(self, event=None):
        if self.entry.winfo_ismapped():
            self.entry.pack_forget()
        else:
            self.entry.pack(side="bottom", pady=5)
            self.entry.focus_set()

    # NEW: Send typed text to the queue and hide the box
    def send_command(self, event=None):
        text = self.text_var.get().strip()
        if text:
            self.command_queue.put(text)
        self.text_var.set("")
        self.entry.pack_forget()
        self.root.focus_set()