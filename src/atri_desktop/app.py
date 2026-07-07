from __future__ import annotations

import ctypes
import os
import queue
import random
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Callable

from PIL import Image, ImageTk

from .assets import APP_ICON_PATH, DEFAULT_EXPRESSION, EXPRESSIONS, Expression, expression_for_status
from .controller import ActionResult, DesktopPetController, DesktopPetStatus
from .single_instance import acquire_single_instance, release_single_instance


REFRESH_INTERVAL_MS = 10_000
TRANSPARENT_COLOR = "#010203"
PET_SIZE = 96
WINDOWS_APP_ID = "AtriQQBot.DesktopPet"


class DesktopPetApp:
    def __init__(self, root: tk.Tk, controller: DesktopPetController | None = None) -> None:
        self.root = root
        self.controller = controller or DesktopPetController()
        self.results: queue.Queue[tuple[str, ActionResult | DesktopPetStatus | Exception]] = queue.Queue()
        self.busy = False
        self.closing = False
        self.queue_after_id: str | None = None
        self.status_after_id: str | None = None
        self.action_after_id: str | None = None
        self.startup_guard_after_id: str | None = None
        self.exit_redraw_rect: tuple[int, int, int, int] | None = None
        self.destroyed = False
        self.current_status: DesktopPetStatus | None = None
        self.current_expression = DEFAULT_EXPRESSION
        self.drag_offset = (0, 0)
        self.photo: ImageTk.PhotoImage | None = None

        self.message_var = tk.StringVar(value=DEFAULT_EXPRESSION.message)
        self.topmost_var = tk.BooleanVar(value=True)
        self.bubble_visible = tk.BooleanVar(value=True)

        self.root.title("亚托莉桌宠")
        self._set_window_icon()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT_COLOR)
        self._apply_transparency()

        self._build_ui()
        self._build_menu()
        self._place_initially()
        self._schedule_queue_poll()
        self.refresh_status()

    def _apply_transparency(self) -> None:
        try:
            self.root.wm_attributes("-transparentcolor", TRANSPARENT_COLOR)
        except tk.TclError:
            self.root.attributes("-alpha", 0.96)

    def _set_window_icon(self) -> None:
        if not APP_ICON_PATH.exists():
            return
        try:
            self.root.iconbitmap(str(APP_ICON_PATH))
        except tk.TclError:
            return

    def _build_ui(self) -> None:
        self.pet_label = tk.Label(self.root, bg=TRANSPARENT_COLOR, bd=0, highlightthickness=0, cursor="fleur")
        self.pet_label.pack(padx=0, pady=(0, 4))

        self.bubble = tk.Label(
            self.root,
            textvariable=self.message_var,
            bg="#fff7df",
            fg="#3b2b2b",
            bd=1,
            relief="solid",
            padx=10,
            pady=4,
            wraplength=150,
            font=("Microsoft YaHei UI", 8),
        )
        self.bubble.pack(pady=(0, 4))

        for widget in (self.root, self.pet_label, self.bubble):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)
            widget.bind("<ButtonRelease-1>", self._finish_drag)
            widget.bind("<Button-3>", self._show_menu)
            widget.bind("<Double-Button-1>", self._cycle_expression)

        self._set_expression(DEFAULT_EXPRESSION)

    def _build_menu(self) -> None:
        self.menu = tk.Menu(self.root, tearoff=False)
        self.menu.add_command(label="刷新状态", command=self.refresh_status)
        self.menu.add_command(label="启动亚托莉", command=self.start_services)
        self.menu.add_command(label="停止 Atri", command=self.stop_atri)
        self.menu.add_separator()
        self.menu.add_command(label="打开 WebUI", command=self.open_webui)
        self.menu.add_command(label="打开项目目录", command=self.open_project_folder)
        self.menu.add_separator()

        expression_menu = tk.Menu(self.menu, tearoff=False)
        for expression in EXPRESSIONS:
            expression_menu.add_command(
                label=expression.label,
                command=lambda item=expression: self._set_expression(item, item.message),
            )
        self.menu.add_cascade(label="切换表情", menu=expression_menu)
        self.menu.add_checkbutton(label="显示气泡", variable=self.bubble_visible, command=self._sync_bubble)
        self.menu.add_checkbutton(label="窗口置顶", variable=self.topmost_var, command=self._sync_topmost)
        self.menu.add_separator()
        self.menu.add_command(label="状态详情", command=self.show_status_detail)
        self.menu.add_command(label="退出桌宠", command=self.request_close)

    def _place_initially(self) -> None:
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        height = self.root.winfo_reqheight()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max(20, screen_width - width - 80)
        y = max(20, screen_height - height - 100)
        self.root.geometry(f"+{x}+{y}")

    def refresh_status(self) -> None:
        self._run_background("status", self.controller.status)

    def start_services(self) -> None:
        if self.startup_guard_after_id is not None:
            self._say("亚托莉正在启动中，稍等一下。")
            return
        self.startup_guard_after_id = self.root.after(90_000, self._clear_startup_guard)
        self._run_background("start", self.controller.start_services)

    def stop_atri(self) -> None:
        self._run_background("stop", self.controller.stop_atri_service)

    def open_webui(self) -> None:
        self._run_background("webui", self.controller.open_webui)

    def open_project_folder(self) -> None:
        self._run_background("folder", self.controller.open_project_folder)

    def show_status_detail(self) -> None:
        status = self.current_status
        if status is None:
            messagebox.showinfo("亚托莉状态", "状态还在检测中。")
            return
        messagebox.showinfo(
            "亚托莉状态",
            "\n".join(
                [
                    f"Atri 服务：{_state_text(status.atri)}",
                    f"NapCat：{_state_text(status.napcat)}",
                    f"Ollama：{_state_text(status.ollama)}",
                    f"模型：{status.model or '未配置'}",
                    f"OneBot：{status.onebot}",
                    f"WebUI：{status.webui_url}",
                    f"QQ：{status.bot_qq}",
                ]
            ),
        )

    def _sync_topmost(self) -> None:
        self.root.attributes("-topmost", bool(self.topmost_var.get()))

    def _sync_bubble(self) -> None:
        if self.bubble_visible.get():
            self.bubble.pack(pady=(0, 4))
        else:
            self.bubble.pack_forget()

    def _show_menu(self, event: tk.Event) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _start_drag(self, event: tk.Event) -> None:
        self.drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag(self, event: tk.Event) -> None:
        x = event.x_root - self.drag_offset[0]
        y = event.y_root - self.drag_offset[1]
        self.root.geometry(f"+{x}+{y}")

    def _finish_drag(self, event: tk.Event) -> None:
        self._keep_on_screen()

    def _keep_on_screen(self) -> None:
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = min(max(self.root.winfo_x(), 0), max(0, self.root.winfo_screenwidth() - width))
        y = min(max(self.root.winfo_y(), 0), max(0, self.root.winfo_screenheight() - height))
        self.root.geometry(f"+{x}+{y}")

    def _cycle_expression(self, event: tk.Event | None = None) -> None:
        expressions = list(EXPRESSIONS)
        index = expressions.index(self.current_expression) if self.current_expression in expressions else 0
        self._set_expression(expressions[(index + 1) % len(expressions)])

    def _set_expression(self, expression: Expression, message: str | None = None) -> None:
        image = Image.open(expression.path).convert("RGBA")
        image.thumbnail((PET_SIZE, PET_SIZE), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image)
        self.pet_label.configure(image=self.photo)
        self.current_expression = expression
        if message is not None:
            self.message_var.set(message)

    def _run_background(self, name: str, func: Callable[[], ActionResult | DesktopPetStatus]) -> None:
        if self.closing:
            return
        if name != "status":
            if self.busy:
                self._say("上一条命令还在执行，稍等一下。")
                return
            self.busy = True
            self._say("命令执行中...")

        def worker() -> None:
            try:
                self.results.put((name, func()))
            except Exception as exc:
                self.results.put((name, exc))

        threading.Thread(target=worker, daemon=True).start()

    def _schedule_queue_poll(self) -> None:
        if self.closing:
            return
        self._poll_results()
        if not self.closing:
            self.queue_after_id = self.root.after(250, self._schedule_queue_poll)

    def _poll_results(self) -> None:
        while True:
            try:
                name, result = self.results.get_nowait()
            except queue.Empty:
                break
            self._handle_result(name, result)

    def _handle_result(self, name: str, result: ActionResult | DesktopPetStatus | Exception) -> None:
        if self.closing:
            return

        if name != "status":
            self.busy = False

        if isinstance(result, Exception):
            if name == "start":
                self._clear_startup_guard()
            self._set_expression_by_key("cry", f"执行失败：{result}")
            return

        if isinstance(result, DesktopPetStatus):
            self._render_status(result)
            self._schedule_status_refresh()
            return

        if result.ok:
            self._set_expression_by_key("idea", result.message)
        else:
            if name == "start":
                self._clear_startup_guard()
            self._set_expression_by_key("cry", f"{result.message} {result.detail}".strip())
        self.action_after_id = self.root.after(900, self.refresh_status)

    def _schedule_status_refresh(self) -> None:
        if self.closing:
            return
        if self.status_after_id is not None:
            self.root.after_cancel(self.status_after_id)
        self.status_after_id = self.root.after(REFRESH_INTERVAL_MS, self._run_scheduled_status_refresh)

    def _run_scheduled_status_refresh(self) -> None:
        if self.closing:
            return
        self.status_after_id = None
        self.refresh_status()

    def _render_status(self, status: DesktopPetStatus) -> None:
        self.current_status = status
        if status.atri and status.napcat:
            self._clear_startup_guard()
        expression = expression_for_status(status.atri, status.napcat)
        self._set_expression(expression)
        if status.atri and status.napcat:
            self._say(random.choice(("后台连接正常。", "高性能运行中。", "Atri 和 NapCat 都在线。")))
        elif status.atri:
            self._say("Atri 已启动，NapCat 还没连上。")
        else:
            self._say("Atri 未运行。右键可以启动亚托莉。")

    def _set_expression_by_key(self, key: str, message: str) -> None:
        for expression in EXPRESSIONS:
            if expression.key == key:
                self._set_expression(expression, message)
                return
        self._say(message)

    def _say(self, message: str) -> None:
        self.message_var.set(message)

    def _clear_startup_guard(self) -> None:
        if self.startup_guard_after_id is None:
            return
        self._cancel_after("startup_guard_after_id")

    def request_close(self) -> None:
        if self.closing:
            return
        try:
            self.root.after_idle(self.close)
        except (AttributeError, tk.TclError):
            try:
                self.root.after(0, self.close)
            except (AttributeError, tk.TclError):
                self.close()

    def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.busy = False
        self.exit_redraw_rect = self._desktop_rect()

        self._cancel_after("queue_after_id")
        self._cancel_after("status_after_id")
        self._cancel_after("action_after_id")
        self._cancel_after("startup_guard_after_id")

        self._release_menu()

        try:
            self.pet_label.configure(image="", text="")
            self.bubble.pack_forget()
        except (AttributeError, tk.TclError):
            pass
        try:
            self.root.attributes("-topmost", False)
        except (AttributeError, tk.TclError):
            pass
        try:
            self.root.attributes("-alpha", 0.0)
        except (AttributeError, tk.TclError):
            pass
        try:
            self.root.overrideredirect(False)
        except (AttributeError, tk.TclError):
            pass
        try:
            self.root.lower()
        except (AttributeError, tk.TclError):
            pass
        try:
            offscreen_x = self.root.winfo_screenwidth() + 10_000
            offscreen_y = self.root.winfo_screenheight() + 10_000
            self.root.geometry(f"1x1+{offscreen_x}+{offscreen_y}")
            self.root.update_idletasks()
            self.root.update()
        except (AttributeError, tk.TclError):
            pass

        try:
            self.root.withdraw()
            self.root.update_idletasks()
            self.root.update()
        except (AttributeError, tk.TclError):
            pass

        self.destroy()

    def destroy(self) -> None:
        if self.destroyed:
            return
        self.destroyed = True
        redraw_rect = self.exit_redraw_rect or self._desktop_rect()
        try:
            self.root.destroy()
        except (AttributeError, tk.TclError):
            pass
        self._redraw_desktop_region(redraw_rect)

    def _release_menu(self) -> None:
        try:
            self.menu.unpost()
        except (AttributeError, tk.TclError):
            pass
        try:
            self.menu.grab_release()
        except (AttributeError, tk.TclError):
            pass

    def _cancel_after(self, attr_name: str) -> None:
        after_id = getattr(self, attr_name, None)
        if after_id is None:
            return
        try:
            self.root.after_cancel(after_id)
        except tk.TclError:
            pass
        setattr(self, attr_name, None)

    def _window_rect(self) -> tuple[int, int, int, int] | None:
        try:
            self.root.update_idletasks()
            left = self.root.winfo_rootx()
            top = self.root.winfo_rooty()
            right = left + self.root.winfo_width()
            bottom = top + self.root.winfo_height()
        except (AttributeError, tk.TclError):
            return None
        padding = 12
        return (left - padding, top - padding, right + padding, bottom + padding)

    def _desktop_rect(self) -> tuple[int, int, int, int] | None:
        if os.name != "nt":
            return self._window_rect()
        try:
            user32 = ctypes.windll.user32
            left = user32.GetSystemMetrics(76)
            top = user32.GetSystemMetrics(77)
            width = user32.GetSystemMetrics(78)
            height = user32.GetSystemMetrics(79)
        except Exception:
            return self._window_rect()
        if width <= 0 or height <= 0:
            return self._window_rect()
        return (left, top, left + width, top + height)

    def _redraw_desktop_region(self, rect: tuple[int, int, int, int] | None) -> None:
        if os.name != "nt" or rect is None:
            return

        class Rect(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        native_rect = Rect(*rect)
        rect_pointer = ctypes.byref(native_rect)
        redraw_flags = 0x0001 | 0x0004 | 0x0080 | 0x0100 | 0x0400
        try:
            ctypes.windll.user32.InvalidateRect(None, rect_pointer, True)
            ctypes.windll.user32.RedrawWindow(None, rect_pointer, None, redraw_flags)
        except Exception:
            pass


def _state_text(value: bool) -> str:
    return "运行中" if value else "未运行"


def _set_windows_app_id() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    except Exception:
        pass


def main() -> None:
    if not acquire_single_instance():
        return
    _set_windows_app_id()
    root = tk.Tk()
    app: DesktopPetApp | None = None
    try:
        app = DesktopPetApp(root)
        root.mainloop()
    finally:
        if app is not None:
            app.destroy()
        release_single_instance()
