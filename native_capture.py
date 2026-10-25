"""Small native note/evidence popup. Persistence stays in DumbAPI."""
import json
import tkinter as tk
from datetime import datetime
import urllib.request
import uuid

from launcher import DATA
from snipping import Snipper

BG, FG, DIM, PINK = '#0b0a0f', '#eeedf2', '#a29bab', '#ff4fcd'


def upload(path):
    data = path.read_bytes()
    req = urllib.request.Request('http://127.0.0.1:8783/api/itch-upload', data=data,
        headers={'Authorization': 'Bearer ' + (DATA/'desktop.token').read_text().strip(),
                 'X-File-Name': path.name, 'X-File-Type': 'image/png', 'Content-Type': 'image/png'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=20) as response:
        return json.load(response)['attachment']


class CapturePopup:
    def __init__(self, root, run, api, args, close, row=None, candidates=(), recent=(), open_item=None):
        self.root, self.run, self.api, self.args, self.close_callback = root, run, api, args, close
        self.row, self.jobs, self.busy, self.submission, self.snipper = row, [], False, None, None
        self.window = popup = tk.Toplevel(root)
        popup.title('DumbManager · THAT.' if row else 'DumbManager · Stash an itch')
        popup.configure(bg=BG); popup.attributes('-topmost', True); popup.resizable(False, False)
        width, height = 550, 390 + min(3, len(recent)) * 34
        popup.geometry(f'{width}x{height}+{max(0,(popup.winfo_screenwidth()-width)//2)}+{max(0,(popup.winfo_screenheight()-height)//3)}')
        label = lambda text, color=DIM, **kw: tk.Label(popup, text=text, bg=BG, fg=color, **kw)
        moment = row and row['state']=='needs_description'
        label('THAT. WHAT’S UP?' if moment else 'ADD A RECEIPT' if row else 'STASH AN ITCH', PINK, font=('Consolas', 12)).pack(anchor='w', padx=22, pady=(20, 8))
        context = (args.get('project') or 'unsorted') + (' · moment saved' if moment else ' · open itch' if row else ' · new itch')
        label(context, font=('Consolas', 10)).pack(anchor='w', padx=22, pady=(0, 12))
        self.entry = tk.Entry(popup, bg='#17141d', fg=FG, insertbackground=PINK, relief='flat', font=('Segoe UI', 12))
        self.entry.pack(fill='x', padx=22, ipady=9)
        if row and row['state'] != 'needs_description': self.entry.insert(0, row['title'])
        self.choices = tk.Listbox(popup, bg=BG, fg=DIM, selectbackground='#38213c', selectforeground=FG,
            relief='flat', borderwidth=0, highlightthickness=0, height=3, font=('Segoe UI', 10), exportselection=False)
        self.choices.pack(fill='x', padx=22, pady=8)
        self.status = label('A few words · Enter saves · Tab completes', font=('Consolas', 9), wraplength=500, justify='left')
        self.status.pack(anchor='w', padx=22)
        self.receipts = label('', font=('Consolas', 9)); self.receipts.pack(anchor='w', padx=22, pady=(8, 0))
        buttons = tk.Frame(popup, bg=BG); buttons.pack(fill='x', padx=22, pady=16)
        def button(text, command, primary=False):
            b = tk.Button(buttons, text=text, command=command, bg=PINK if primary else '#211b28', fg=BG if primary else FG,
                          relief='flat', padx=12, pady=8, font=('Consolas', 10))
            b.pack(side='left', padx=(0, 8)); return b
        self.save_button = button('Save it ↵' if row else 'Stash it ↵', self.save, True)
        self.snip_button = button('Snip evidence', self.snip)
        self.close_button = button('Close' if row else 'Cancel', self.close)
        if recent and open_item:
            for item in recent[:3]:
                tk.Button(popup, text='↗ '+item['title'][:65], command=lambda id=item['id']: open_item(id),
                    bg='#211b28', fg=FG, relief='flat', anchor='w').pack(fill='x', padx=22, pady=(0, 6))
        def suggest(_=None):
            typed = self.entry.get().casefold().strip(); self.choices.delete(0, 'end')
            if len(typed) < 2: return
            for value in list(dict.fromkeys(candidates)):
                if value.casefold().startswith(typed) and value.casefold()!=typed:
                    self.choices.insert('end', value)
                    if self.choices.size() == 3: break
        def complete(_=None):
            if self.choices.size():
                selected = self.choices.curselection()
                value = self.choices.get(selected[0] if selected else 0)
                self.entry.delete(0, 'end'); self.entry.insert(0, value); self.choices.delete(0, 'end')
            return 'break'
        self.entry.bind('<KeyRelease>', suggest); self.entry.bind('<Tab>', complete)
        self.entry.bind('<Return>', self.save); self.choices.bind('<Double-Button-1>', complete)
        popup.bind('<Escape>', lambda _: self.close()); popup.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh_receipts(); popup.after(50, self.entry.focus_force)

    def refresh_receipts(self):
        count = len(self.row.get('attachments', [])) if self.row else 0
        count += sum(not job.get('attached') for job in self.jobs)
        self.receipts.configure(text=f'[ ▧ ] {count}/8 receipts' if count else '[ + ] Drag a box to add evidence')

    def lock(self, busy):
        self.busy = busy
        for widget in (self.save_button, self.snip_button, self.close_button):
            widget.configure(state='disabled' if busy else 'normal')
        self.entry.configure(state='disabled' if busy or self.submission else 'normal')

    def close(self):
        if self.busy or self.snipper: return
        # Failed work stays visible for retry; never silently throw away a snip.
        if any(job['path'].exists() for job in self.jobs) or self.submission:
            self.status.configure(text='Unsaved work is kept here. Hit Save to retry before closing.')
            return
        self.window.destroy(); self.close_callback()

    def snip(self):
        if self.busy or self.snipper or self.submission: return
        count = len(self.row.get('attachments', [])) if self.row else 0
        if count + sum(not j.get('attached') for j in self.jobs) >= 8:
            self.status.configure(text='8 receipts max for one itch.'); return
        self.window.withdraw()
        self.root.after(100, self._overlay)

    def _overlay(self):
        try: self.snipper = Snipper(self.root, self._snipped, 'Snip → '+(self.row['title'][:60] if self.row else 'this new itch'))
        except Exception as exc: self._snipped(None, str(exc))

    def _snipped(self, data, error):
        self.snipper = None; self.window.deiconify(); self.window.lift(); self.entry.focus_force()
        if error: self.status.configure(text='Could not snip: '+error); return
        if not data: self.status.configure(text='Snip cancelled. Your note is kept.'); return
        folder = DATA/'native-snips'; folder.mkdir(exist_ok=True)
        path = folder / ('snip-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.png')
        try: path.write_bytes(data)
        except OSError as exc: self.status.configure(text='Could not save snip: '+str(exc)); return
        job = {'path':path}; self.jobs.append(job); self.refresh_receipts()
        self.lock(True); self.status.configure(text='[ ▧ ] Adding receipt…')
        self.run(lambda: self._store(job), self._stored)

    def _store(self, job):
        if not job.get('attachment'): job['attachment'] = upload(job['path'])
        if self.row and not job.get('attached'):
            value = self.api('manager.attach', {'id':self.row['id'], 'attachments':json.dumps([job['attachment']['id']])})
            job['attached'] = True; job['path'].unlink(missing_ok=True)
            return value
        return None

    def _stored(self, value, error):
        if value: self.row = value
        self.lock(False); self.refresh_receipts()
        self.status.configure(text='Snip kept locally. Save to retry adding it.' if error else 'Receipt added. Add a note or keep snipping.')

    def save(self, _=None):
        if self.busy or self.snipper: return 'break'
        title = self.entry.get().strip()
        if len(title)>500: self.status.configure(text='Keep the note under 500 characters.'); return 'break'
        if not self.row and not title and not self.jobs:
            self.status.configure(text='Add a note or snip first.'); return 'break'
        self.lock(True); self.status.configure(text='[ + ] Saving…')
        def work():
            for job in self.jobs:
                value = self._store(job)
                if value: self.row = value
            if self.submission is None:
                if self.row:
                    changes = {'title':title} if title and title!=self.row['title'] else {}
                    self.submission = ('manager.update', {'id':self.row['id'], 'changes':json.dumps(changes),
                        'expected_version':self.row['version'], 'request_key':uuid.uuid4().hex}) if changes else ('manager.get', {'id':self.row['id']})
                else:
                    args = {**self.args, 'title':title, 'attachments':json.dumps([j['attachment']['id'] for j in self.jobs])}
                    self.submission = ('manager.capture', args)
            return self.api(*self.submission)
        def done(value, error):
            self.lock(False)
            if error:
                self.status.configure(text='Save did not confirm. Your work is kept; hit Save to retry.'); return
            for job in self.jobs: job['path'].unlink(missing_ok=True)
            self.submission = None; self.window.destroy(); self.close_callback(value)
        self.run(work, done)
        return 'break'
