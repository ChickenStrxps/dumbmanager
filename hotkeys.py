"""Own the Win32 message queue separately from Tk's event loop."""
import ctypes
from ctypes import wintypes
import queue
import threading

HOTKEYS = {1: (0x49, "Ctrl+Alt+I"), 2: (0x4D, "Ctrl+Alt+M"), 3: (0x44, "Ctrl+Alt+D"), 4: (0x43, "Ctrl+Alt+C"), 5: (0x53, "Ctrl+Alt+S")}


class Hotkeys:
    def __init__(self, keys=None):
        self.keys = HOTKEYS if keys is None else keys
        self.events = queue.Queue()
        self.ready = threading.Event()
        self.bindings, self.conflicts = {}, []
        self.thread_id, self.error = 0, ""
        self.thread = threading.Thread(target=self._listen, daemon=True)

    def start(self):
        self.thread.start()
        if not self.ready.wait(3):
            raise RuntimeError("Windows shortcuts took too long to start.")
        if self.error:
            raise RuntimeError(self.error)
        return self

    def _listen(self):
        user = ctypes.WinDLL("user32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        user.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user.GetMessageW.restype = wintypes.BOOL
        self.thread_id = kernel.GetCurrentThreadId()
        registered = []
        try:
            # Register and consume messages on this same thread. Tk must never
            # consume WM_HOTKEY before an after() callback gets to peek at it.
            for id, (key, label) in self.keys.items():
                options = [(0x4003,label),(0x4006,label.replace('Ctrl+Alt+','Ctrl+Shift+')),
                           (0x4007,label.replace('Ctrl+Alt+','Ctrl+Alt+Shift+'))]
                for modifiers, assigned in options:
                    if user.RegisterHotKey(None, id, modifiers, key):
                        self.bindings[str(id)] = assigned
                        registered.append(id)
                        break
                else:
                    self.conflicts.append(label)
            self.ready.set()
            message = wintypes.MSG()
            while True:
                result = user.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                if result == 0:
                    break
                if message.message == 0x0312 and str(message.wParam) in self.bindings:
                    self.events.put(int(message.wParam))
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.ready.set()
            for id in registered:
                user.UnregisterHotKey(None, id)

    def stop(self):
        if self.thread.is_alive():
            user = ctypes.WinDLL("user32", use_last_error=True)
            user.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
            self.thread.join(3)
