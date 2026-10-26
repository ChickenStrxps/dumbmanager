# Running from source

Use Windows 10 or 11, Python 3.14 with Tcl/Tk, and installed Microsoft Edge.
There are no required pip packages or npm build for the app itself. Git is needed
for Git tools. T3 Code is a separate optional install, with its normal local CLI
pairing. Node is not needed to run the app.

Run `py -3.14 run.py` from the extracted source root. For a quiet host without
shortcuts, use `py -3.14 run.py --no-open --no-native`. `status` and `stop` inspect
or stop only this distribution on port 8783. The optional API daemon uses 8781,
and the optional phone gateway uses 8784.

The default state folders are `%LOCALAPPDATA%/DumbManagerCommunity` and
`%LOCALAPPDATA%/DumbAPICommunity`. They are created at runtime and are never part
of a source archive. No existing installation is migrated or connected. Removing
the source or executable keeps those folders; delete them yourself only when you
want to remove your records and saved connections. Back up your records first.

Choose a project in Settings → Connections. Source tools see only that selected
folder. Clearing the selection removes source access but keeps itches. Other
workspaces can be selected later. This preview does not import account records,
T3 threads, invitations, settings or project samples.

Local stashing, plans, feedback, research briefs and review need no provider key.
TypeSafe/Jev and Inception/Mercury are optional paid connections using your own
keys. Set Jev through Browse's connection form and Mercury through Fresh ideas.
The underlying encrypted stores reject unsupported credential persistence outside
Windows. Missing keys use local paths or show an unavailable state.

DumbBridge needs your own Discord developer application, application ID, bot
token and chosen channel/guild. Command registration and connection are explicit
actions. A configured token is not proof of a working Discord session. Completion
webhooks likewise require your receiver and a reviewed send action.

Replay needs a separately installed FFmpeg. Phone access optionally uses an
installed `cloudflared`; no tunnel starts just by launching the desktop host.
Browser logins/challenges and provider quotas remain the user's responsibility.
