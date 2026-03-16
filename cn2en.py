# -*- coding: utf-8 -*-
"""
CN2EN-Translator - Chinese to English Translation Tool
Python Implementation
Hotkeys: F8 to toggle translation mode, Esc to exit translation mode
"""

import threading
import time
import urllib.parse
import json
import tkinter as tk
from tkinter import ttk, messagebox
import ctypes

import pystray
from pystray import MenuItem as Item
from PIL import Image, ImageDraw
import pyperclip
import requests
from pynput import keyboard


def get_screen_size():
    """Get screen size using ctypes"""
    user32 = ctypes.windll.user32
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def get_mouse_position():
    """Get current mouse position using ctypes"""
    w = ctypes.windll.user32
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    pt = POINT()
    w.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


class TranslatorApp:
    def __init__(self):
        self.is_translating = False
        self.original_text = ""
        self.translated_text = ""
        self.clipboard_check_interval = 0.2  # seconds
        self.clipboard_monitor_timer = None
        self.last_clipboard_content = ""

        # Create tray icon
        self.icon = None
        self.setup_tray_icon()

        # Create tooltip window (hidden initially)
        self.tooltip = None
        self.create_tooltip_window()

        # Input buffer for direct keyboard input
        self.input_buffer = ""
        self.input_timeout = 1.0  # seconds
        self._input_timer = None

        # Start clipboard monitoring thread
        self.monitor_clipboard_thread = None
        self.running = True

    def setup_tray_icon(self):
        """Create system tray icon"""
        # Create icons
        self.icon_idle = self.create_colored_icon((128, 128, 128))  # Gray
        self.icon_active = self.create_colored_icon((0, 200, 0))     # Green

        # Create menu
        menu = (
            Item('显示窗口', self.show_window),
            Item('退出', self.exit_app)
        )

        # Create tray icon
        self.icon = pystray.Icon(
            "CN2EN-Translator",
            self.icon_idle,
            "CN2EN-Translator (等待中)",
            menu
        )

    def create_colored_icon(self, color):
        """Create a colored square icon"""
        size = (64, 64)
        image = Image.new('RGB', size, color)
        draw = ImageDraw.Draw(image)

        # Add a simple border
        draw.rectangle([4, 4, 59, 59], outline='white', width=2)

        return image

    def create_tooltip_window(self):
        """Create tooltip window for displaying translations"""
        self.tooltip = tk.Tk()
        self.tooltip.withdraw()  # Hide initially
        self.tooltip.overrideredirect(True)  # No window decorations
        self.tooltip.attributes('-topmost', True)  # Always on top

        # Create styling
        style = ttk.Style()
        style.configure('Translation.TFrame', background='#ffffcc')
        style.configure('Translation.TLabel', background='#ffffcc', font=('Microsoft YaHei', 10))

        # Main frame
        self.frame = ttk.Frame(self.tooltip, style='Translation.TFrame', padding=10)
        self.frame.pack(fill=tk.BOTH, expand=True)

        # Labels
        self.original_label = ttk.Label(self.frame, text='', style='Translation.TLabel', wraplength=400)
        self.original_label.pack(anchor=tk.W, pady=(0, 5))

        self.translated_label = ttk.Label(self.frame, text='', style='Translation.TLabel', wraplength=400)
        self.translated_label.pack(anchor=tk.W, pady=(0, 5))

        self.hint_label = ttk.Label(self.frame, text='按 F8 替换 | Esc 退出', style='Translation.TLabel', foreground='gray')
        self.hint_label.pack(anchor=tk.W)

    def toggle_translation_mode(self):
        """Toggle translation mode on/off"""
        if self.is_translating:
            # If already translating and we have translation, replace text first
            if self.translated_text:
                self.replace_text()
            self.exit_translation_mode()
        else:
            self.enter_translation_mode()

    def enter_translation_mode(self):
        """Enter translation mode"""
        self.is_translating = True
        self.original_text = ""
        self.translated_text = ""
        self.last_clipboard_content = ""
        self.input_buffer = ""  # Clear input buffer

        # Clear clipboard to capture new content
        pyperclip.copy("")

        # Update tray icon to green
        if self.icon:
            self.icon.icon = self.icon_active
            self.icon.title = "CN2EN-Translator (翻译模式)"

        # Show notification via tooltip
        self.show_tooltip("翻译模式已开启", "请输入中文内容")

        # Start clipboard monitoring
        self.start_clipboard_monitor()

    def exit_translation_mode(self):
        """Exit translation mode"""
        self.is_translating = False

        # Stop clipboard monitoring
        self.stop_clipboard_monitor()

        # Cancel input timer
        if self._input_timer:
            self._input_timer.cancel()
            self._input_timer = None

        # Hide tooltip
        self.hide_tooltip()

        # Update tray icon to gray
        if self.icon:
            self.icon.icon = self.icon_idle
            self.icon.title = "CN2EN-Translator (等待中)"

        # Show notification
        self.show_tooltip("翻译模式已关闭", "")

    def start_clipboard_monitor(self):
        """Start monitoring clipboard for changes"""
        self.running = True
        self.monitor_clipboard_thread = threading.Thread(target=self.monitor_clipboard, daemon=True)
        self.monitor_clipboard_thread.start()

    def stop_clipboard_monitor(self):
        """Stop monitoring clipboard"""
        self.running = False

    def monitor_clipboard(self):
        """Monitor clipboard for Chinese text"""
        while self.running and self.is_translating:
            try:
                # Get clipboard content
                clip_content = pyperclip.paste()

                # Check if there's new content (non-empty and different from original)
                if clip_content and clip_content != self.last_clipboard_content:
                    self.last_clipboard_content = clip_content

                    # Check if contains Chinese characters
                    if self.has_chinese_char(clip_content):
                        self.original_text = clip_content
                        # Show "translating" status
                        self.show_translating()
                        # Translate
                        self.translate_text(self.original_text)

                time.sleep(self.clipboard_check_interval)
            except Exception as e:
                print(f"Clipboard monitor error: {e}")
                time.sleep(self.clipboard_check_interval)

    def has_chinese_char(self, text):
        """Check if text contains Chinese characters"""
        for char in text:
            # Unicode range for Chinese characters: 0x4E00 - 0x9FFF
            if '\u4e00' <= char <= '\u9fff':
                return True
        return False

    def add_input_char(self, char):
        """Add input character to buffer"""
        self.input_buffer += char
        # Reset timeout timer
        if self._input_timer:
            self._input_timer.cancel()
        self._input_timer = threading.Timer(self.input_timeout, self.process_input_buffer)
        self._input_timer.start()

    def process_input_buffer(self):
        """Process input buffer after timeout"""
        if self.input_buffer and self.has_chinese_char(self.input_buffer):
            self.original_text = self.input_buffer
            self.show_translating()
            self.translate_text(self.original_text)
        self.input_buffer = ""

    def show_translating(self):
        """Show 'translating' message"""
        # Get mouse position
        try:
            x, y = get_mouse_position()
            self._show_tooltip_at("翻译中...", "", x + 20, y + 20)
        except:
            self._show_tooltip("翻译中...", "")

    def translate_text(self, text):
        """Call MyMemory API to translate text (free, no API key needed)"""
        try:
            # MyMemory API - free translation service
            url = "https://api.mymemory.translated.net/get"
            params = {
                'q': text,
                'langpair': 'zh-CN|en'
            }

            print(f"Translating: {text}")  # Debug
            response = requests.get(url, params=params, timeout=10)
            print(f"Response status: {response.status_code}")  # Debug
            print(f"Response text: {response.text[:200]}")  # Debug

            # Check response status
            if response.status_code != 200:
                self.show_tooltip(f"翻译失败: HTTP {response.status_code}", "")
                threading.Timer(3, self.hide_tooltip).start()
                return

            # Parse JSON
            result = response.json()

            if result.get('responseStatus') == 200:
                self.translated_text = result.get('responseData', {}).get('translatedText', '')
                if self.translated_text:
                    # Show translation result
                    self.show_translation_result()
                else:
                    self.show_tooltip("翻译失败: 无结果", "")
                    threading.Timer(3, self.hide_tooltip).start()
            else:
                error_msg = result.get('responseDetails', '翻译失败')
                self.show_tooltip(f"翻译失败: {error_msg}", "")
                threading.Timer(3, self.hide_tooltip).start()

        except requests.exceptions.Timeout:
            self.show_tooltip("翻译失败: 请求超时", "")
            threading.Timer(3, self.hide_tooltip).start()
        except requests.exceptions.RequestException as e:
            print(f"Request exception: {e}")  # Debug
            self.show_tooltip(f"翻译失败: 网络错误", "")
            threading.Timer(3, self.hide_tooltip).start()
        except Exception as e:
            print(f"Exception: {e}")  # Debug
            self.show_tooltip(f"翻译失败: {str(e)}", "")
            threading.Timer(3, self.hide_tooltip).start()

    def show_translation_result(self):
        """Show translation result in tooltip"""
        try:
            x, y = get_mouse_position()
            self._show_tooltip_at(
                f"原文: {self.original_text}",
                f"英文: {self.translated_text}",
                x + 20, y + 20
            )
        except:
            self._show_tooltip(
                f"原文: {self.original_text}",
                f"英文: {self.translated_text}"
            )

    def show_tooltip(self, original_msg, translated_msg):
        """Show tooltip at center of screen (thread-safe)"""
        self.tooltip.after(0, lambda: self._show_tooltip(original_msg, translated_msg))

    def _show_tooltip(self, original_msg, translated_msg):
        """Internal method to show tooltip"""
        try:
            screen_width, screen_height = get_screen_size()
            x = int(screen_width / 2 - 250)
            y = int(screen_height / 2 - 100)
            self.tooltip.geometry(f'500x200+{x}+{y}')
            self.original_label.config(text=original_msg)
            self.translated_label.config(text=translated_msg)
            self.tooltip.deiconify()
        except Exception as e:
            print(f"Show tooltip error: {e}")

    def show_tooltip_at(self, original_msg, translated_msg, x, y):
        """Show tooltip at specific position (thread-safe)"""
        self.tooltip.after(0, lambda: self._show_tooltip_at(original_msg, translated_msg, x, y))

    def _show_tooltip_at(self, original_msg, translated_msg, x, y):
        """Internal method to show tooltip at position"""
        try:
            screen_width, screen_height = get_screen_size()

            # Adjust if going off screen
            if x + 500 > screen_width:
                x = screen_width - 510
            if y + 200 > screen_height:
                y = screen_height - 210

            self.tooltip.geometry(f'500x200+{x}+{y}')
            self.original_label.config(text=original_msg)
            self.translated_label.config(text=translated_msg)
            self.tooltip.deiconify()
        except Exception as e:
            print(f"Show tooltip at error: {e}")

    def hide_tooltip(self):
        """Hide tooltip window (thread-safe)"""
        try:
            self.tooltip.after(0, self.tooltip.withdraw)
        except:
            pass

    def replace_text(self):
        """Replace original text with translated text"""
        if not self.translated_text:
            self.show_tooltip("无翻译结果", "请先输入中文内容")
            return

        # Copy translation to clipboard
        pyperclip.copy(self.translated_text)

        # Simulate Ctrl+V to paste
        from pynput.keyboard import Controller, Key
        keyboard_controller = Controller()
        keyboard_controller.press(Key.ctrl_l)
        keyboard_controller.press('v')
        keyboard_controller.release('v')
        keyboard_controller.release(Key.ctrl_l)

        # Show confirmation
        self.show_tooltip("替换成功", "已将中文替换为英文")

        # Reset state
        self.original_text = ""
        self.translated_text = ""
        self.last_clipboard_content = ""

        # Auto-hide after 2 seconds
        threading.Timer(2, self.hide_tooltip).start()

    def show_window(self):
        """Show main window (info dialog)"""
        info = """CN2EN-Translator 正在后台运行

快捷键:
- F8: 开始/结束翻译
- Esc: 退出翻译模式

按 F8 开始使用"""
        # Use tkinter messagebox for thread-safe display
        self.tooltip.after(0, lambda: messagebox.showinfo("CN2EN-Translator", info))

    def exit_app(self):
        """Exit the application"""
        self.running = False
        if self.icon:
            self.icon.stop()
        try:
            self.tooltip.after(0, self.tooltip.destroy)
        except:
            pass
        import sys
        sys.exit()

    def run(self):
        """Run the tray icon (blocking)"""
        # Run tray icon
        self.icon.run_detached()


def on_press(key, app):
    """Handle key press events"""
    try:
        # F8 key
        if key == keyboard.Key.f8:
            app.toggle_translation_mode()
        # Escape key
        elif key == keyboard.Key.esc:
            if app.is_translating:
                app.exit_translation_mode()
        # Capture Chinese character input during translation mode
        elif app.is_translating:
            try:
                char = key.char
                if char and app.has_chinese_char(char):
                    # Collect typed Chinese text
                    app.add_input_char(char)
            except AttributeError:
                # Functional keys don't have char attribute
                pass
    except Exception as e:
        print(f"Key press error: {e}")


def main():
    """Main entry point"""
    # Create application instance
    app = TranslatorApp()

    # Show startup message after a short delay to ensure tkinter is ready
    def show_startup():
        info = """CN2EN-Translator 已启动

快捷键:
- F8: 开始/结束翻译
- Esc: 退出翻译模式

按 F8 开始使用"""
        messagebox.showinfo("CN2EN-Translator", info)

    # Schedule startup message
    app.tooltip.after(100, show_startup)

    # Create keyboard listener
    def make_handler(app_instance):
        def handler(key):
            on_press(key, app_instance)
        return handler

    # Run keyboard listener in a separate thread
    listener_thread = threading.Thread(target=lambda: keyboard.Listener(on_press=make_handler(app)).start(), daemon=True)
    listener_thread.start()

    # Run tray icon in a separate thread
    icon_thread = threading.Thread(target=app.run, daemon=True)
    icon_thread.start()

    # Run tkinter main loop (this must be in main thread)
    app.tooltip.mainloop()


if __name__ == "__main__":
    main()
