"""Windows-only shortcuts and compact capture. Domain logic stays in DumbAPI."""
import ctypes
import json
import os
import queue
import threading
import time
import tkinter as tk
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
import uuid
import webbrowser
import hashlib

from launcher import DATA, ROOT, request
from hotkeys import Hotkeys
from native_control import write_json
from native_capture import CapturePopup


def main():
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    identity = hashlib.sha256(str(DATA.resolve()).casefold().encode()).hexdigest()[:16]
    mutex = kernel.CreateMutexW(None, False, "Local\\DumbManager.Native.v2."+identity)
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(mutex)
        return
    user.GetForegroundWindow.restype = wintypes.HWND
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.IsWindow.argtypes = [wintypes.HWND]
    user.GetParent.argtypes = [wintypes.HWND]
    user.GetParent.restype = wintypes.HWND
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    # Screen coordinates and GDI pixels must agree on mixed-DPI monitors.
    try:
        user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    root.withdraw()
    tasks, results = queue.Queue(), queue.Queue()
    cache = {"itches": [], "contexts": []}
    ui = {"popup": None, "foreground": None, "saved": False}
    hotkeys = Hotkeys().start()
    atomic_path = DATA / "native-status.json"
    native_state = {"version": 2, "pid": os.getpid(), "thread_id": hotkeys.thread_id,
                    "bindings": hotkeys.bindings, "shortcut_conflicts": hotkeys.conflicts,
                    "test_until": 0, "test_id": "", "test_hits": [], "last_event": None}
    def publish():
        try:
            if hotkeys.thread.is_alive():
                write_json(atomic_path, {**native_state, "heartbeat": time.time()})
            else:
                atomic_path.unlink(missing_ok=True)
                if not ui['popup']: root.after(0, root.destroy)
        except OSError:
            # A short Windows sharing violation must never stop heartbeat/poll.
            pass
    def heartbeat():
        try:
            publish()
        finally:
            root.after(2000, heartbeat)
    def worker():
        while True:
            fn, callback = tasks.get()
            try:
                value, error = fn(), None
            except Exception as exc:
                value, error = None, str(exc)
            results.put((callback, value, error))
    threading.Thread(target=worker, daemon=True).start()
    def run(fn, callback=lambda *_: None):
        tasks.put((fn, callback))
    def api(name, args):
        return request("/api/call", {"name": name, "args": args})
    def current():
        return next((c for c in cache["contexts"] if c["id"] == cache.get("active_context")), None)
    def payload(title="", moment=False):
        ctx = current() or {}
        return {"title": title, "moment": moment, "project": ctx.get("project", "unsorted"),
                "context_id": ctx.get("id", ""), "use_active": False,
                "context_snapshot": json.dumps(ctx),
                "event_at": datetime.now(timezone.utc).isoformat(), "request_key": uuid.uuid4().hex}
    def persist_pending(args):
        path = DATA / ("native-pending-" + args["request_key"] + ".json")
        # Small durable retry queue; never silently drop a failed shortcut capture.
        if len(list(DATA.glob("native-pending-*.json"))) >= 32:
            return False
        path.write_text(json.dumps(args), encoding="utf-8")
        return True
    def sync_pending():
        for path in list(DATA.glob("native-pending-*.json"))[:32]:
            try:
                api("manager.capture", json.loads(path.read_text(encoding="utf-8")))
                path.unlink()
            except Exception:
                break
    def close_popup(value=None):
        ui['popup'] = None
        if value:
            run(lambda: api('manager.state', {}), update_cache)
        hwnd = ui['foreground']
        if hwnd and user.IsWindow(hwnd):
            user.SetForegroundWindow(hwnd)
    def capture_popup(drawer=False, row=None, snip=False, args=None):
        popup = ui['popup']
        if popup:
            popup.window.lift()
            if snip: popup.snip()
            return
        ui['foreground'] = user.GetForegroundWindow()
        ctx = current() or {}
        candidates = list(ctx.get('candidates', []))
        recent = [r for r in cache['itches'] if r['state'] not in {'resolved','archived'}]
        candidates += [r['title'] for r in recent if r['project']==ctx.get('project')]
        def open_item(id):
            webbrowser.open('http://127.0.0.1:8783/#itch='+id)
            ui['popup'].close()
        ui['popup'] = CapturePopup(root, run, api, args or payload(), close_popup,
                                  row=row, candidates=candidates, recent=recent[:3] if drawer else (), open_item=open_item)
        if snip: root.after(120, ui['popup'].snip)
        if not row: run(lambda: request('/api/replay', {'action':'begin'}))
    def snip_evidence(itch_id=''):
        if ui['popup']:
            if itch_id and (ui['popup'].row or {}).get('id') != itch_id:
                notify('Finish the open note first, then snip for the other itch.')
                return
            ui['popup'].snip()
            return
        def target():
            value = {'id':itch_id} if itch_id else request('/api/cook', {'action':'evidence_target'})
            return api('manager.get', {'id':value['id']}) if value.get('id') else None
        def done(value,error):
            if error: notify('Could not open that itch. Open its popup and try again.'); return
            args = payload()
            if value: args.update(project=value['project'], context_id=value.get('context_id',''))
            capture_popup(row=value, snip=True, args=args)
        run(target, done)
    def update_cache(value, error):
        if value:
            cache.update(value)
    def refresh():
        run(lambda: api("manager.state", {}), update_cache)
        run(sync_pending)
        root.after(10000, refresh)
    def mark():
        if ui['popup']:
            ui['popup'].window.lift()
            ui['popup'].entry.focus_force()
            return
        args = payload(moment=True)
        def done(value, error):
            if error:
                saved = persist_pending(args)
                notify('Moment kept locally · details after reconnect' if saved else 'Could not save · retry queue full')
            else:
                cache['itches'].insert(0, value)
                capture_popup(row=value, args=args)
        run(lambda: api('manager.capture', args), done)
    def notify(text):
        # A short acknowledgement without taking keyboard focus.
        toast = tk.Toplevel(root)
        toast.withdraw()
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        tk.Label(toast, text=text, bg="#21221d", fg="#e6bb65", font=("Consolas", 10), padx=18, pady=12).pack()
        toast.update_idletasks()
        toast.geometry(f"+{toast.winfo_screenwidth()-toast.winfo_reqwidth()-30}+{toast.winfo_screenheight()-100}")
        toast.update_idletasks()
        hwnd = user.GetParent(toast.winfo_id())
        user.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
        toast.after(1600, toast.destroy)
    def commands():
        root.after(250, commands)
        command_path = DATA / "native-command.json"
        try:
            command = json.loads(command_path.read_text(encoding="utf-8"))
            command_path.unlink(missing_ok=True)
            if 0 <= time.time() - command.get('at', 0) < 10:
                action = command.get('action')
                native_state['command_id'] = command['id']
                if action == 'test':
                    native_state.update(test_id=command['id'], test_until=time.time()+15, test_hits=[])
                elif action == 'capture': capture_popup()
                elif action == 'moment': mark()
                elif action == 'snip': snip_evidence(command.get('itch_id',''))
                publish()
        except (OSError, ValueError, TypeError, KeyError):
            pass
    def poll():
        # Schedule first so a failed UI callback cannot disable global keys.
        root.after(35, poll)
        while True:
            try:
                id = hotkeys.events.get_nowait()
            except queue.Empty:
                break
            testing = time.time() < native_state["test_until"]
            native_state["last_event"] = {"id": id, "at": datetime.now(timezone.utc).isoformat(), "testing": testing}
            if testing:
                if id not in native_state["test_hits"]:
                    native_state["test_hits"].append(id)
                if len(native_state['test_hits']) == len(native_state['bindings']):
                    native_state['test_until'] = 0
                publish()
                continue
            publish()
            if id == 1:
                capture_popup()
            elif id == 2:
                mark()
            elif id == 3:
                capture_popup(drawer=True)
            elif id == 5:
                snip_evidence()
            elif id == 4:
                run(lambda: request('/api/cook', {'action': 'send'}),
                    lambda value, error: notify('Open an itch popup and pick its T3 thread first.' if error else '[ + ] Let it cook. Check the itch popup for delivery.'))
        while True:
            try:
                callback, value, error = results.get_nowait()
            except queue.Empty:
                break
            try:
                callback(value, error)
            except tk.TclError:
                pass
    health_failures = 0
    def alive(value, error):
        nonlocal health_failures
        health_failures = health_failures + 1 if error else 0
        if health_failures >= 3 and not ui['popup']:
            root.destroy()
    def health():
        run(request, alive)
        root.after(5000, health)
    refresh()
    health()
    heartbeat()
    commands()
    poll()
    try:
        root.mainloop()
    finally:
        hotkeys.stop()
        kernel.CloseHandle(mutex)
        atomic_path.unlink(missing_ok=True)


if __name__ == "__main__" and os.name == "nt":
    main()

