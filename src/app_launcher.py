"""
Application launcher utilities for Qwen3-VL Computer Control System.

Provides cross-compatible application launching:
- Launch apps via Start menu search
- Open URLs in default/specific browser
- Open files with default application
- Run commands via Run dialog (Win+R)

Uses a combination of subprocess and Windows APIs.
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Optional

import pyautogui


def launch_app_via_start_menu(app_name: str, wait_seconds: float = 2.0) -> bool:
    """
    Launch an application by searching in the Start menu.
    
    This simulates: Win key -> type app name -> Enter
    
    Args:
        app_name: Name of the application to search for
        wait_seconds: Time to wait for Start menu to open
    
    Returns:
        True if the sequence was executed (doesn't guarantee app launched)
    """
    try:
        # Press Windows key to open Start menu
        pyautogui.press('win')
        time.sleep(0.5)
        
        # Type the app name
        pyautogui.write(app_name, interval=0.05)
        time.sleep(wait_seconds)
        
        # Press Enter to launch
        pyautogui.press('enter')
        
        return True
    except Exception:
        return False


def launch_app_via_run_dialog(command: str, wait_seconds: float = 0.5) -> bool:
    """
    Launch an application via the Run dialog (Win+R).
    
    Args:
        command: Command to run (e.g., "notepad", "calc", "cmd")
        wait_seconds: Time to wait for Run dialog to open
    
    Returns:
        True if the sequence was executed
    """
    try:
        # Win+R to open Run dialog
        pyautogui.hotkey('win', 'r')
        time.sleep(wait_seconds)
        
        # Type the command
        pyautogui.write(command, interval=0.02)
        time.sleep(0.2)
        
        # Press Enter to run
        pyautogui.press('enter')
        
        return True
    except Exception:
        return False


def launch_app(name: str, method: str = "start_menu") -> bool:
    """
    Launch an application by name.
    
    Args:
        name: Application name or command
        method: Launch method - "start_menu" (default), "run_dialog", or "subprocess"
    
    Returns:
        True if launch was attempted
    """
    command = name.strip()
    
    if method == "start_menu":
        # Special handling for URI-style commands (e.g., "spotify:")
        # If it's a URI, startfile is actually very reliable and bypasses UI
        if ":" in command and " " not in command:
            try:
                os.startfile(command)
                return True
            except Exception:
                pass
        return launch_app_via_start_menu(name)
    elif method == "run_dialog":
        return launch_app_via_run_dialog(command)
    elif method == "subprocess":
        try:
            subprocess.Popen(command, shell=True)
            return True
        except Exception:
            return False
    
    return False


def open_url(url: str, browser: Optional[str] = None) -> bool:
    """
    Open a URL in the default or specified browser.
    
    Args:
        url: URL to open
        browser: Optional browser name ("chrome", "firefox", "edge")
                If None, uses default browser
    
    Returns:
        True if URL was opened
    """
    try:
        if browser is None:
            # Use default browser via os.startfile (Windows)
            os.startfile(url)
            return True
        
        # Map browser names to executable patterns
        browser_commands = {
            "chrome": "chrome",
            "google chrome": "chrome",
            "firefox": "firefox",
            "mozilla firefox": "firefox",
            "edge": "msedge",
            "microsoft edge": "msedge",
        }
        
        browser_cmd = browser_commands.get(browser.lower(), browser)
        
        # Launch browser with URL
        subprocess.Popen([browser_cmd, url], shell=True)
        return True
        
    except Exception:
        return False


def open_file(file_path: str) -> bool:
    """
    Open a file with its default application.
    
    Args:
        file_path: Path to the file
    
    Returns:
        True if file was opened
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return False
        
        os.startfile(str(path))
        return True
    except Exception:
        return False


def open_folder(folder_path: str) -> bool:
    """
    Open a folder in File Explorer.
    
    Args:
        folder_path: Path to the folder
    
    Returns:
        True if folder was opened
    """
    try:
        path = Path(folder_path)
        if not path.exists():
            return False
        
        subprocess.Popen(['explorer', str(path)])
        return True
    except Exception:
        return False


def run_command_prompt(command: Optional[str] = None, keep_open: bool = True) -> bool:
    """
    Open Command Prompt, optionally running a command.
    
    Args:
        command: Optional command to run
        keep_open: Keep window open after command (/K vs /C)
    
    Returns:
        True if opened
    """
    try:
        if command:
            flag = "/K" if keep_open else "/C"
            subprocess.Popen(['cmd', flag, command])
        else:
            subprocess.Popen(['cmd'])
        return True
    except Exception:
        return False


def run_powershell(command: Optional[str] = None, keep_open: bool = True) -> bool:
    """
    Open PowerShell, optionally running a command.
    
    Args:
        command: Optional command to run
        keep_open: Keep window open after command
    
    Returns:
        True if opened
    """
    try:
        if command:
            flag = "-NoExit" if keep_open else ""
            args = ['powershell', flag, '-Command', command] if flag else ['powershell', '-Command', command]
            subprocess.Popen([a for a in args if a])
        else:
            subprocess.Popen(['powershell'])
        return True
    except Exception:
        return False


def take_screenshot_to_file(filepath: str) -> bool:
    """
    Take a screenshot and save it to a file.
    
    Uses Windows Snipping Tool or fallback to PyAutoGUI.
    
    Args:
        filepath: Where to save the screenshot
    
    Returns:
        True if screenshot was saved
    """
    try:
        screenshot = pyautogui.screenshot()
        screenshot.save(filepath)
        return True
    except Exception:
        return False
