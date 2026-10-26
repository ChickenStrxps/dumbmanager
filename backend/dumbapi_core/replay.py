"""Opt-in, selected-window compressed frame ring. Idle means no capture process."""
import ctypes
import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from .common import APIError, atomic_json, read_json

MIB = 1024 ** 2
OWNER = "DumbManager.replay.v1"


class Replay:
    def __init__(self, data):
        self.root = Path(data).resolve() / "media"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.ring = deque()
        self.ring_bytes = 0
        self.events = []
        self.begin_at = None
        self.process = None
        self.window = None
        self.error = ""
        self.last_frame = 0
        self.cleanup()

    def windows(self):
        if os.name != "nt":
            return {"items": [], "note": "Window replay requires Windows and FFmpeg."}
        from ctypes import wintypes
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user.IsWindowVisible.argtypes = [wintypes.HWND]
        user.IsIconic.argtypes = [wintypes.HWND]
        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        rows = []
        def visit(hwnd, _):
            if user.IsWindowVisible(hwnd) and not user.IsIconic(hwnd):
                size = user.GetWindowTextLengthW(hwnd)
                if size:
                    title = ctypes.create_unicode_buffer(min(size + 1, 1000))
                    user.GetWindowTextW(hwnd, title, len(title))
                    if title.value and title.value not in {"Program Manager"}:
                        rows.append({"hwnd": str(hwnd), "title": title.value})
            return True
        user.EnumWindows(callback(visit), 0)
        return {"items": rows[:100]}

    def status(self):
        with self.lock:
            self.cleanup()
            armed = bool(self.process and self.process.poll() is None)
            return {"armed": armed, "window": self.window, "buffer_seconds": round(min(6, time.monotonic() - self.ring[0][0]), 1) if self.ring else 0,
                    "buffer_bytes": self.ring_bytes, "pending": len(self.events), "error": self.error,
                    "frames_per_second": 10, "max_size": "640x360", "idle_capture_processes": 0 if not armed else 1,
                    "note": "Selected window only; no audio. Minimized, protected or GPU surfaces may be blank. Check the frameboard before relying on it."}

    def arm(self, hwnd):
        if not isinstance(hwnd, str) or not hwnd.isdecimal():
            raise APIError("Choose a listed test window.")
        window = next((w for w in self.windows()["items"] if w["hwnd"] == hwnd), None)
        if not window:
            raise APIError("That window is unavailable or minimized.")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise APIError("FFmpeg is required for optional replay; capture works without replay.", "unavailable", 503)
        self.disarm()
        with self.lock:
            self.window, self.error = window, ""
            self.last_frame = time.monotonic()
            argv = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "gdigrab", "-framerate", "10", "-draw_mouse", "0",
                    "-i", "hwnd=" + hwnd, "-an", "-vf", "scale=640:360:force_original_aspect_ratio=decrease", "-threads", "1", "-q:v", "7", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"]
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.process = process
            threading.Thread(target=self.read, args=(process,), daemon=True).start()
            threading.Thread(target=self.watch, args=(process,), daemon=True).start()
        return self.status()

    def disarm(self):
        with self.lock:
            process, self.process = self.process, None
            pending, self.events = self.events, []
            self.ring.clear()
            self.ring_bytes = 0
            self.begin_at = None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        for event in pending:
            event["truncated"] = True
            threading.Thread(target=self.save, args=(event,), daemon=True).start()
        return self.status()

    def begin(self):
        with self.lock:
            if self.process and self.process.poll() is None and self.begin_at is None:
                self.begin_at = time.monotonic()
        return self.status()

    def finish(self, id):
        if not re.fullmatch(r"[a-f0-9]{32}", id):
            raise APIError("Invalid itch id.")
        with self.lock:
            if not self.process or self.process.poll() is not None or len(self.events) >= 4:
                return
            stamp = time.monotonic()
            start = max(stamp - 24, (self.begin_at or stamp) - 6)
            self.begin_at = None
            # The ring always holds six seconds. During capture, a pending event accumulates frames below.
            active = next((e for e in self.events if e.get("id") is None), None)
            if active:
                active.update(id=id, end=stamp + 6)
            else:
                frames = [(t, data) for t, data in self.ring if t >= start]
                self.events.append({"id": id, "start": start, "end": stamp + 6, "frames": frames, "bytes": sum(len(d) for _, d in frames), "truncated": False})

    def read(self, process):
        buffer = bytearray()
        try:
            while process.poll() is None:
                block = process.stdout.read1(65536)
                if not block:
                    break
                buffer.extend(block)
                if len(buffer) > 2 * MIB:
                    raise RuntimeError("Unexpected oversized capture frame.")
                while (end := buffer.find(b"\xff\xd9")) != -1:
                    start = buffer.find(b"\xff\xd8")
                    frame = bytes(buffer[start:end + 2]) if 0 <= start < end else None
                    del buffer[:end + 2]
                    if frame:
                        self.add_frame(time.monotonic(), frame)
        except (OSError, RuntimeError) as exc:
            with self.lock:
                self.error = str(exc)
        finally:
            process.stdout.close()
            with self.lock:
                if self.process is process:
                    self.error = self.error or "The selected-window capture stopped. Re-arm after checking the window."

    def add_frame(self, stamp, frame):
        ready = []
        with self.lock:
            self.last_frame = stamp
            self.ring.append((stamp, frame))
            self.ring_bytes += len(frame)
            while self.ring and (stamp - self.ring[0][0] > 6 or self.ring_bytes > 32 * MIB):
                self.ring_bytes -= len(self.ring.popleft()[1])
            if self.begin_at is not None and not any(e.get("id") is None for e in self.events) and len(self.events) < 4:
                frames = list(self.ring)
                self.events.append({"id": None, "start": self.begin_at - 6, "end": self.begin_at + 18,
                                    "frames": frames[:-1], "bytes": sum(len(d) for _, d in frames[:-1]), "truncated": False})
            for event in list(self.events):
                if stamp > event["end"]:
                    self.events.remove(event)
                    if event["id"]:
                        ready.append(event)
                    else:
                        self.begin_at = None
                    continue
                if event["bytes"] + len(frame) <= 20 * MIB and sum(e["bytes"] for e in self.events) + len(frame) <= 32 * MIB:
                    event["frames"].append((stamp, frame))
                    event["bytes"] += len(frame)
                else:
                    event["truncated"] = True
        for event in ready:
            threading.Thread(target=self.save, args=(event,), daemon=True).start()

    def watch(self, process):
        while process.poll() is None:
            time.sleep(1)
            with self.lock:
                if self.process is not process:
                    return
                stale = time.monotonic() - self.last_frame > 5
            if stale:
                with self.lock:
                    self.error = "No frames arrived for five seconds. Replay paused; choose a visible supported window."
                self.disarm()
                return

    def directory(self, id):
        if not isinstance(id, str) or not re.fullmatch(r"[a-f0-9]{32}", id):
            raise APIError("Invalid replay id.")
        path = self.root / id
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(self.root):
            raise APIError("Invalid replay path.")
        return path

    def save(self, event):
        if not event.get("id") or not event["frames"]:
            return
        with self.lock:
            self.cleanup(reserve=event["bytes"])
            if self.usage() + event["bytes"] > 256 * MIB:
                self.error = "Temporary replay budget is full. Delete or unpin a frameboard."
                return
            path = self.directory(event["id"])
            if path.exists():
                return
            path.mkdir()
            frames = []
            start = event["frames"][0][0]
            for index, (stamp, frame) in enumerate(event["frames"]):
                (path / f"{index:04d}.jpg").write_bytes(frame)
                frames.append(round(stamp - start, 3))
            atomic_json(path / "index.json", {"owner": OWNER, "id": event["id"], "created": time.time(), "keep": False,
                        "frames": frames, "bytes": event["bytes"], "truncated": event["truncated"], "window": self.window,
                        "duration": frames[-1], "format": "jpeg-frameboard", "audio": False,
                        "saved_at_seconds": max(0, round(event["end"] - 6 - start, 3))})

    def usage(self, kept=False):
        total = 0
        for index in self.root.glob("*/index.json"):
            try:
                data = read_json(index)
                if data.get("owner") == OWNER and (not kept or data.get("keep")):
                    total += data["bytes"]
            except (OSError, ValueError, KeyError):
                continue
        return total

    def cleanup(self, reserve=0):
        rows = []
        for index in self.root.glob("*/index.json"):
            try:
                row = read_json(index)
                if row.get("owner") == OWNER and not row.get("keep"):
                    rows.append(row)
            except (OSError, ValueError):
                continue
        for row in sorted(rows, key=lambda r: r["created"]):
            if time.time() - row["created"] > 86400 or self.usage() + reserve > 256 * MIB:
                try:
                    self.delete(row["id"])
                except APIError:
                    continue

    def item(self, id):
        self.cleanup()
        path = self.directory(id) / "index.json"
        if not path.is_file():
            return {"available": False, "pending": any(e["id"] == id for e in self.events)}
        return {"available": True, **read_json(path)}

    def keep(self, id, keep=True):
        with self.lock:
            row = self.item(id)
            if not row["available"]:
                raise APIError("This frameboard is unavailable.")
            if keep and not row["keep"] and self.usage(kept=True) + row["bytes"] > 128 * MIB:
                raise APIError("Kept replay budget is 128 MiB. Unpin/delete an earlier board first.")
            row.pop("available", None)
            row["keep"] = bool(keep)
            atomic_json(self.directory(id) / "index.json", row)
            return row

    def delete(self, id):
        with self.lock:
            path = self.directory(id)
            if not path.is_dir():
                return {"deleted": False}
            index = path / "index.json"
            if not index.is_file() or read_json(index).get("owner") != OWNER:
                raise APIError("This is not an owned replay directory.")
            # No recursive deletion: only exact, generated JPEG names and the owned manifest.
            files = list(path.iterdir())
            if any(p.is_symlink() or not p.is_file() or (p.name != "index.json" and not re.fullmatch(r"\d{4}\.jpg", p.name)) for p in files):
                raise APIError("Unexpected replay files; automatic cleanup skipped this directory.")
            for file in files:
                file.unlink()
            path.rmdir()
            return {"deleted": True}

    def frame(self, id, index=0):
        row = self.item(id)
        if not row["available"] or not isinstance(index, int) or not 0 <= index < len(row["frames"]):
            raise APIError("Frame unavailable.", "not_found", 404)
        return (self.directory(id) / f"{index:04d}.jpg").read_bytes()
