# DumbManager

DumbManager keeps the small things from getting lost: a bug you just saw, a rough idea,
a screenshot, the fix you want to test. Stash an itch, give it a plan, send it to the
right T3 conversation, and decide for yourself when it is actually done.

![DumbManager: catch an itch, make a little progress. Two tiny glyph fish swim in a dark aquarium.](docs/assets/little-world.gif)

**The Windows preview is available.** Download [DumbManager.exe](https://github.com/ChickenStrxps/dumbmanager/releases/download/preview-2f2de9718cf6/DumbManager.exe)
to run the app, or get the [matching source ZIP](https://github.com/ChickenStrxps/dumbmanager/releases/download/preview-2f2de9718cf6/DumbManager-source-2f2de9718cf6.zip).
The executable is unsigned. See [preview status and remaining checks](docs/STATUS.md).

### Get going

On Windows, download **DumbManager.exe** from [Releases](https://github.com/ChickenStrxps/dumbmanager/releases/tag/preview-2f2de9718cf6)
and open it. Microsoft Edge is required; the EXE includes Python.

To run from source instead, install Python 3.14 and Microsoft Edge, extract the
source ZIP, open PowerShell in the extracted folder, then run:

```powershell
py -3.14 run.py
```

Open **Settings → Connections** and choose your existing project folder. Nothing is
connected on first launch. You can stash and review itches without an API key.
The app opens at `http://127.0.0.1:8783`; stop it with `py -3.14 run.py stop`.

Add only the connections you want:

- **Jev:** Settings → Browse. Bring your own TypeSafe key for page decisions and source ranking.
- **Mercury:** Settings → Connections → Fresh ideas. Bring your own Inception key for generated suggestions and copy.
- **T3 Code:** install T3 and reconnect from Connections. Choose the exact destination before sending work or attachments.
- **DumbBridge:** Settings → DumbBridge. Use your own Discord application and bot credentials; it stays off until you enable it.
- **Webhooks:** Settings → Posting. Save your own receiver, preview the card, then choose whether to send it.

Keys stay in your local Windows user storage and are not sent back to the browser.
Provider use is billed by your own accounts. Live provider, Discord and phone flows
still need a clean-machine recheck. FFmpeg is optional for replay; a Cloudflare
Tunnel installation is optional for phone access.

### The loop

Stash a thought or a moment. Add receipts, split a messy list into itches, and keep
the plan with the work. Review a change, ask for another pass, or explicitly accept
it. Research and learning trails keep their sources. Suggested and Inspiration
help with the next idea; Browse and chat keep the work close by.

Completion cards can be still or animated, with editable copy and privacy masks.
Sharing is your action. Saved post links are manual notes, not verified posting proof.

![A small ASCII cat crossing a bridge: capture, plan, review, share.](docs/assets/bridge.gif)

Prefer still images? [Aquarium](docs/assets/little-world.png) · [Bridge](docs/assets/bridge.png).
All setup steps above work without playing either animation.

[Setup details](docs/SETUP.md) · [Build and checks](docs/BUILD.md) · [Contributing](CONTRIBUTING.md)
