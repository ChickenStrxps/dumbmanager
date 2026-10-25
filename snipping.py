"""One-shot Windows region capture. No recorder, clipboard, or image dependency."""
import ctypes
from ctypes import wintypes
import struct
import tkinter as tk
import zlib


def bounds():
    user = ctypes.WinDLL('user32', use_last_error=True)
    return tuple(user.GetSystemMetrics(n) for n in (76, 77, 78, 79))


def region(start, end, desktop):
    """Normalize reverse drags and clip to a possibly negative-origin desktop."""
    dx, dy, dw, dh = desktop
    left, right = sorted((start[0], end[0]))
    top, bottom = sorted((start[1], end[1]))
    left, right = max(dx, left), min(dx + dw, right)
    top, bottom = max(dy, top), min(dy + dh, bottom)
    w, h = right - left, bottom - top
    if w < 8 or h < 8:
        raise ValueError('Drag a larger box. Esc cancels.')
    if w * h > 16_000_000:
        raise ValueError('Pick a smaller area, up to 16 million pixels.')
    return left, top, w, h


def png(width, height, bgra):
    def chunk(kind, value):
        return struct.pack('!I', len(value)) + kind + value + struct.pack('!I', zlib.crc32(kind + value))
    if len(bgra) != width * height * 4:
        raise ValueError('Incomplete capture.')
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
    rows = b''.join(b'\0' + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    data = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!IIBBBBB', width, height, 8, 2, 0, 0, 0))
    data += chunk(b'IDAT', zlib.compress(rows, 3)) + chunk(b'IEND', b'')
    if len(data) > 10 * 1024 * 1024:
        raise ValueError('Capture exceeds 10 MiB. Pick a smaller area.')
    return data


def capture(box):
    left, top, width, height = box
    user = ctypes.WinDLL('user32', use_last_error=True)
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    user.GetDC.argtypes = [wintypes.HWND]; user.GetDC.restype = wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]; gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi.CreateDIBSection.restype = wintypes.HANDLE
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]; gdi.SelectObject.restype = wintypes.HANDLE
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]; gdi.DeleteDC.argtypes = [wintypes.HDC]
    gdi.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    screen = user.GetDC(None); memory = gdi.CreateCompatibleDC(screen)
    bitmap = old = None
    try:
        if not screen or not memory:
            raise RuntimeError('Windows could not open the screen capture.')
        header = ctypes.create_string_buffer(struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0))
        bits = ctypes.c_void_p()
        bitmap = gdi.CreateDIBSection(screen, header, 0, ctypes.byref(bits), None, 0)
        if not bitmap or not bits.value:
            raise ctypes.WinError(ctypes.get_last_error())
        old = gdi.SelectObject(memory, bitmap)
        if not gdi.BitBlt(memory, 0, 0, width, height, screen, left, top, 0x40CC0020):
            raise ctypes.WinError(ctypes.get_last_error())
        gdi.GdiFlush()
        return png(width, height, ctypes.string_at(bits, width * height * 4))
    finally:
        if old: gdi.SelectObject(memory, old)
        if bitmap: gdi.DeleteObject(bitmap)
        if memory: gdi.DeleteDC(memory)
        if screen: user.ReleaseDC(None, screen)


class Snipper:
    def __init__(self, root, done, title='Drag a box for this itch', capture_fn=capture):
        self.root, self.done, self.capture_fn = root, done, capture_fn
        self.desktop = bounds()
        x, y, width, height = self.desktop
        self.window = tk.Toplevel(root)
        self.window.withdraw(); self.window.overrideredirect(True)
        self.window.attributes('-topmost', True); self.window.attributes('-alpha', .28)
        self.window.geometry(f'{width}x{height}+0+0')
        self.canvas = tk.Canvas(self.window, bg='#08080b', highlightthickness=0, cursor='crosshair')
        self.canvas.pack(fill='both', expand=True)
        self.canvas.create_text(width // 2, 38, text=title + '  ·  Esc cancels', fill='#ffffff', font=('Consolas', 14))
        self.start = None; self.rectangle = None; self.finished = False
        self.canvas.bind('<ButtonPress-1>', self.begin)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.window.bind('<Escape>', lambda _: self.finish())
        self.window.protocol('WM_DELETE_WINDOW', self.finish)
        self.window.deiconify(); self.window.update_idletasks()
        # Tk's negative geometry offsets mean "from the right", not absolute
        # virtual-desktop coordinates. Position the wrapper with Win32 instead.
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.GetParent.argtypes = [wintypes.HWND]; user.GetParent.restype = wintypes.HWND
        user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user.SetWindowPos(user.GetParent(self.window.winfo_id()), wintypes.HWND(-1), x, y, width, height, 0x0040)
        self.window.lift(); self.window.grab_set(); self.window.focus_force()

    def begin(self, event):
        self.start = (event.x_root, event.y_root)
        if self.rectangle: self.canvas.delete(self.rectangle)
        self.rectangle = self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline='#ff4fcd', width=3)

    def drag(self, event):
        if self.start:
            x, y, _, _ = self.desktop
            self.canvas.coords(self.rectangle, self.start[0]-x, self.start[1]-y, event.x_root-x, event.y_root-y)

    def release(self, event):
        if not self.start: return
        try: box = region(self.start, (event.x_root, event.y_root), self.desktop)
        except ValueError as exc:
            self.canvas.create_text(20, 70, anchor='w', text=str(exc), fill='white', font=('Consolas', 12))
            self.start = None
            return
        self.finish(box)

    def finish(self, box=None):
        if self.finished: return
        self.finished = True
        self.window.grab_release(); self.window.destroy()
        # Allow the compositor to remove the overlay before reading pixels.
        def collect():
            if not box: return self.done(None, None)
            try: data, error = self.capture_fn(box), None
            except Exception as exc: data, error = None, str(exc)
            self.done(data, error)
        self.root.after(100, collect)
