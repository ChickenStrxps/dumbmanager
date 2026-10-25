# Checks and Windows build

The runtime uses Python 3.14's standard library. CI installs only development/build
tools on GitHub-hosted disposable workers. From the repository root:

```powershell
$env:PYTHONPATH = "$PWD/backend;$PWD"
py -3.14 -B tools/verify_public.py
py -3.14 -B -m unittest discover -s tests/api -v
py -3.14 -B -m unittest discover -s tests/host -v
node --check web/app.js
```

`private-preview` is a bounded check/build workflow. It verifies the selected
source tree, runs the suites with no configured connections, performs a first-run
HTTP smoke check, and attempts a Windows PyInstaller build. A matching complete
source ZIP and SHA-256 sums are made from the same exact Git commit as the EXE.
The workflow saves a draft prerelease containing the EXE, source ZIP, checksums,
test reports and navigation screenshots. It never publishes the draft or changes
repository visibility. Temporary Actions artifacts have seven-day retention.
Build success alone does not establish clean-install readiness.

Setup commits explicitly marked `Prepare private source preview:` squash only
the private bootstrap history to neutral contributor metadata and remove their
private setup run records. Ordinary later pushes retain normal history.

The frozen entry point dispatches host/native child processes explicitly. Detached
helpers use independent extraction environments so resources survive launcher exit
([PyInstaller guidance](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#using-sys-executable-to-spawn-subprocesses-that-outlive-the-application-process-implementing-application-restart)).
`tools/frozen_smoke.py` tests the actual packaged UI, including stashing and reload. Web
assets, fonts and notices, backend source helpers, JS GIF encoders and the OCR
PowerShell helper are bundled. Edge, FFmpeg and Cloudflare Tunnel remain external
optional prerequisites. Runtime data is stored outside the executable and source.
See `packaging/DumbManager.spec` and the pinned build requirements.

Before a later release, rerun against the reviewed commit, extract and scan both
artifacts, test on a clean Windows user profile, record signing status, and attach
the EXE, complete source ZIP and checksums together. Publication is an owner step.
