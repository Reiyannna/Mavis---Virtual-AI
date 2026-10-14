import os
import sys
import subprocess
import json
import uuid
from datetime import datetime
from pypdf import PdfReader
from docx import Document

from core.settings import DOWNLOADS_DIR, BRAIN_DIR, ALARM_FILE, MEMORY_FILE, ensure_brain_dir

def _is_safe_path(path: str) -> bool:
    """Security check to restrict actions to the Download directory."""
    return os.path.abspath(path).startswith(os.path.abspath(DOWNLOADS_DIR))


def list_download_files(subfolder: str = "") -> str:
    """Lists files and folders inside the Download directory or a specified subfolder."""
    target_dir = os.path.join(DOWNLOADS_DIR, subfolder) if subfolder else DOWNLOADS_DIR
    
    if not _is_safe_path(target_dir):
        return "Access denied: Path lies outside the Download directory."
    if not os.path.exists(target_dir):
        return f"Folder '{subfolder}' does not exist in the Download directory."
        
    try:
        items = []
        for root, _, files in os.walk(target_dir):
            rel_root = os.path.relpath(root, DOWNLOADS_DIR)
            prefix = "" if rel_root == "." else f"[{rel_root}] "
            for file in files:
                items.append(f"{prefix}{file}")
                
        if not items:
            return "No files found in the specified location."
        return "Files found:\n" + "\n".join(items[:40])
    except Exception as e:
        return f"Error listing files: {e}"
    

def search_download_files(keyword: str) -> str:
    """Searches for files matching a keyword across the Download folder and all subfolders."""
    try:
        matches = []
        for root, _, files in os.walk(DOWNLOADS_DIR):
            for file in files:
                if keyword.lower() in file.lower():
                    rel_path = os.path.relpath(os.path.join(root, file), DOWNLOADS_DIR)
                    matches.append(rel_path)
                    
        if not matches:
            return f"No files matching '{keyword}' were found."
        return f"Found matching files: {', '.join(matches)}"
    except Exception as e:
        return f"Error searching files: {e}"
    

def read_file(filename: str) -> str:
    """Reads text from .txt, .pdf, .docx, .py, .md, or .json files in Download or subfolders."""
    target_path = None
    
    for root, _, files in os.walk(DOWNLOADS_DIR):
        if filename in files or os.path.relpath(os.path.join(root, filename), DOWNLOADS_DIR) == filename:
            target_path = os.path.join(root, filename)
            break
            
    if not target_path or not _is_safe_path(target_path) or not os.path.exists(target_path):
        return f"Could not find file '{filename}' in the Download directory."

    ext = os.path.splitext(target_path)[1].lower()
    try:
        if ext in ['.txt', '.md', '.py', '.json', '.csv']:
            with open(target_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        elif ext == '.pdf':
            reader = PdfReader(target_path)
            content = "\n".join([page.extract_text() or "" for page in reader.pages])
        elif ext == '.docx':
            doc = Document(target_path)
            content = "\n".join([p.text for p in doc.paragraphs])
        else:
            return f"Unsupported file type '{ext}'."

        if len(content) > 5000:
            return content[:5000] + "\n... [Content truncated for length]"
        return content if content.strip() else "The file appears to be empty."
    except Exception as e:
        return f"Error reading file '{filename}': {e}"
    

def create_note(filename: str, content: str) -> str:
    """Creates a text file (.txt) in the Download folder with the provided content."""
    if not filename.endswith('.txt'):
        filename += '.txt'
    file_path = os.path.join(DOWNLOADS_DIR, filename)
    
    if not _is_safe_path(file_path):
        return "Access denied: Cannot write outside Download directory."

    if content:
        content = content.replace('\\n', '\n')
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully created note '{filename}' in Download folder."
    except Exception as e:
        return f"Error creating note: {e}"
    

def run_local_script(script_name: str, folder_name: str = "") -> str:
    """Launches a local Python script in a dedicated visible CMD terminal window."""
    if not script_name.endswith('.py'):
        script_name += '.py'
        
    script_path = None
    target_filename = os.path.basename(script_name)
    
    for root, dirs, files in os.walk(DOWNLOADS_DIR):
        if 'mavis_project' in root:
            continue
            
        if target_filename in files:
            candidate_path = os.path.join(root, target_filename)
            
            # If a specific folder (e.g., 'To_do_today_tasks') is required, skip mismatched folders
            if folder_name and folder_name.lower() not in root.lower():
                continue
                
            if os.path.dirname(script_name).lower() in root.lower() or not script_path:
                script_path = candidate_path
            
    if not script_path or not _is_safe_path(script_path):
        return f"Could not find Python script '{script_name}' inside '{folder_name}'."

    try:
        script_dir = os.path.dirname(script_path)
        
        cmd_command = f'start "" cmd /k ""{sys.executable}" "{script_path}""'
        subprocess.Popen(cmd_command, shell=True, cwd=script_dir)
        
        return f"Successfully opened new terminal window in '{script_dir}' and executed '{target_filename}'."
    except Exception as e:
        return f"Failed to launch script '{script_name}': {e}"
    

def get_current_time_and_date() -> str:
    """Returns the current local time, day of the week, and date."""
    now = datetime.now()
    return now.strftime("Today is %A, %B %d, %Y. The current time is %I:%M %p.")


#MEMORY ----OBSIDIAN
def _existing_memory_entries():
    """Reads the hub memory file as a list of entry texts (for dedup)."""
    import re
    if not os.path.exists(MEMORY_FILE):
        return []
    entries = []
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^- \*\*\[.*?\]\*\*: (.*)$", line.strip())
            if m:
                entries.append(m.group(1))
    return entries


def _is_duplicate_memory(new_text: str, existing: list, threshold: float = 0.82) -> bool:
    """True when new_text is essentially already remembered."""
    import difflib
    new_low = new_text.lower().strip()
    if not new_low:
        return True
    for old in existing:
        if difflib.SequenceMatcher(None, new_low, old.lower().strip()).ratio() >= threshold:
            return True
    return False


def save_obsidian_memory(memory_text: str) -> str:
    """Saves important facts, instructions, or context to Mavis's permanent Obsidian memory.

    Skips near-duplicates. [[person-x]] / [[topic-y]] wikilinks in the text are
    linked into the knowledge graph automatically.
    """
    ensure_brain_dir()
    from datetime import datetime
    from core.memory_graph import MemoryGraph

    if _is_duplicate_memory(memory_text, _existing_memory_entries()):
        return "Already remembered - a very similar memory exists, not duplicating."

    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n- **[{timestamp}]**: {memory_text}")
        linked = MemoryGraph().absorb_explicit_memory(memory_text, timestamp)
        suffix = ""
        if linked:
            suffix = " Linked into graph: " + ", ".join(f"[[{s}]]" for s in linked) + "."
        return f"Successfully saved to Obsidian memory: '{memory_text}'." + suffix
    except Exception as e:
        return f"Failed to save memory: {e}"

def read_obsidian_memory() -> str:
    """Reads all saved long-term memories from the Obsidian vault."""
    if not os.path.exists(MEMORY_FILE):
        return "No permanent memories have been saved yet."
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            # If the file gets massive, only return the most recent 5000 characters
            if len(content) > 5000:
                return "... [Earlier memories truncated] ...\n" + content[-5000:]
            return content
    except Exception as e:
        return f"Failed to read memory: {e}"

def rewrite_obsidian_memory(new_text: str) -> str:
    """Overwrites the entire Obsidian memory file. Used to delete past events by saving only valid, future memories."""
    ensure_brain_dir()
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            f.write(new_text)
        return "Successfully rewrote Obsidian memory to remove outdated facts."
    except Exception as e:
        return f"Failed to rewrite memory: {e}"

def _memory_snippet(text: str, terms: list, window: int = 280) -> str:
    low = text.lower()
    hits = [low.find(t) for t in terms if t in low]
    start = max(0, (min(hits) if hits else 0) - 80)
    snippet = text[start:start + window].strip()
    snippet = " ".join(snippet.split())
    return ("..." if start > 0 else "") + snippet


def search_memory(query: str, max_results: int = 5) -> str:
    """Searches Mavis's Obsidian vault (saved memories, people/topic notes, daily logs)
    for past context relevant to a query. Use this BEFORE answering when the request
    touches past facts, preferences, people, or earlier conversations."""
    import re
    terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2]
    if not terms:
        return "Give me a keyword or two to search her memory for."
    if not os.path.isdir(BRAIN_DIR):
        return "No memories saved yet."
    hits = []
    for root, _, files in os.walk(BRAIN_DIR):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            path = os.path.join(root, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except Exception:
                continue
            low = text.lower()
            score = sum(low.count(t) for t in terms)
            # the hub memory file holds the deliberate long-term memories: rank it up
            if os.path.abspath(path) == os.path.abspath(MEMORY_FILE):
                score *= 2
            if score > 0:
                hits.append((score, os.path.relpath(path, BRAIN_DIR), text))
    if not hits:
        return f"No memories found matching '{query}'."
    hits.sort(key=lambda h: h[0], reverse=True)
    out = []
    for score, rel, text in hits[:max(1, max_results)]:
        links = sorted(set(re.findall(r"\[\[([^\]]+)\]\]", text)))[:8]
        link_str = ", ".join(f"[[{l}]]" for l in links) if links else "none"
        out.append(f"[{rel}] (relevance {score})\n{_memory_snippet(text, terms)}\nlinks: {link_str}")
    return "\n\n---\n\n".join(out)

#ALARMS --- NOTIFIERS
def set_alarm(time_string: str, message: str) -> str:
    ensure_brain_dir()
    """Sets a reminder. time_string accepts natural language like 'in 10 minutes' or 'tomorrow at 5pm'."""
    import dateparser
    import json
    from datetime import datetime
    import os
    
    # Parses the natural language into an exact future date
    parsed_time = dateparser.parse(time_string, settings={'PREFER_DATES_FROM': 'future'})
    
    if not parsed_time:
        return f"Failed to understand the time format: {time_string}"
        
    alarm_file = ALARM_FILE
    
    alarms = []
    if os.path.exists(alarm_file):
        try:
            with open(alarm_file, "r") as f:
                alarms = json.load(f)
        except:
            pass
            
    alarm_id = str(len(alarms) + 1)
    alarms.append({
        "id": alarm_id,
        "time": parsed_time.strftime("%Y-%m-%d %H:%M:%S"),
        "message": message
    })
    
    with open(alarm_file, "w") as f:
        json.dump(alarms, f, indent=4)
        
    return f"Successfully set alarm for {parsed_time.strftime('%Y-%m-%d %I:%M %p')}. Message: {message}"

def check_alarms() -> str:
    """Lists all currently active alarms."""
    import json
    import os
    alarm_file = ALARM_FILE
    if not os.path.exists(alarm_file):
        return "You have no active alarms set."
    with open(alarm_file, "r") as f:
        alarms = json.load(f)
    if not alarms:
        return "You have no active alarms set."
    
    res = ["Active Alarms:"]
    for a in alarms:
        res.append(f"- ID {a['id']}: {a['time']} -> {a['message']}")
    return "\n".join(res)
    
def delete_alarm(alarm_id: str) -> str:
    """Deletes a specific alarm by its ID."""
    import json
    import os
    alarm_file = ALARM_FILE
    if not os.path.exists(alarm_file):
        return "No alarms exist."
    with open(alarm_file, "r") as f:
        alarms = json.load(f)
        
    new_alarms = [a for a in alarms if str(a['id']) != str(alarm_id)]
    if len(alarms) == len(new_alarms):
        return f"No alarm found with ID {alarm_id}."
        
    with open(alarm_file, "w") as f:
        json.dump(new_alarms, f, indent=4)
    return f"Alarm {alarm_id} has been permanently deleted."