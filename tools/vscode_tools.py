import os
import subprocess
import pyperclip
try:
    import pygetwindow as gw
except ImportError:
    gw = None

from core.settings import DOWNLOADS_DIR

def read_clipboard() -> str:
    """Reads the current text or code from the user's clipboard."""
    try:
        content = pyperclip.paste()
        return f"Here is the text the user highlighted and copied:\n\n{content}" if content else "The clipboard is empty."
    except Exception as e:
        return f"Error reading clipboard: {e}"

def get_active_vscode_workspace() -> str:
    """Detects the active VS Code window and locates the project folder path."""
    if not gw:
        return DOWNLOADS_DIR
    
    windows = gw.getWindowsWithTitle('Visual Studio Code')
    if not windows:
        return DOWNLOADS_DIR
    
    # VS Code titles format: "file.py - project_folder - Visual Studio Code"
    title = windows[0].title
    parts = title.split(' - ')
    if len(parts) >= 2:
        folder_name = parts[-2] # Extract the active folder name
        
        # Search for this folder inside the Download directory to get the full path
        for root, dirs, _ in os.walk(DOWNLOADS_DIR):
            if folder_name in dirs:
                return os.path.join(root, folder_name)
    
    return DOWNLOADS_DIR

def scaffold_project(project_name: str, project_type: str = "python") -> str:
    """Scaffolds a new project folder with standard files and opens it in VS Code."""
    workspace = get_active_vscode_workspace()
    
    # Default to Downloads if no specific workspace is found
    if workspace == DOWNLOADS_DIR:
        project_path = os.path.join(DOWNLOADS_DIR, project_name)
    else:
        # Create it next to the currently open project
        project_path = os.path.join(os.path.dirname(workspace), project_name)
        
    os.makedirs(project_path, exist_ok=True)
    
    if project_type.lower() == "flask":
        files = {
            "app.py": "from flask import Flask\n\napp = Flask(__name__)\n\n@app.route('/')\ndef hello():\n    return 'Hello, Mavis!'\n\nif __name__ == '__main__':\n    app.run(debug=True)\n",
            "requirements.txt": "Flask==3.0.0\n"
        }
    else:
        files = {
            "main.py": "def main():\n    print('Hello from Mavis!')\n\nif __name__ == '__main__':\n    main()\n",
            "requirements.txt": ""
        }
        
    for filename, content in files.items():
        with open(os.path.join(project_path, filename), "w") as f:
            f.write(content)
            
    try:
        # Launch VS Code pointing to the new folder
        subprocess.Popen(f'code "{project_path}"', shell=True)
    except Exception:
        pass 
        
    return f"Successfully scaffolded {project_type} project at {project_path}."

def generate_code_file(filename: str, code_content: str) -> str:
    """Generates a new code file in the current active VS Code workspace."""
    workspace = get_active_vscode_workspace()
    file_path = os.path.join(workspace, filename)
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code_content)
        return f"Successfully generated {filename} at {workspace}."
    except Exception as e:
        return f"Failed to generate file: {e}"