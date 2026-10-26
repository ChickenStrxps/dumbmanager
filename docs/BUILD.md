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

## Pull requests and main

**Checks** runs on pull requests to main, pushes to main and manual requests. Its
**Windows checks** job validates the source inventory and syntax, runs both suites,
then checks first launch and desktop/phone browser navigation in disposable state.
It has read-only repository permissions, receives no service keys, does not retain
Git checkout credentials and cannot publish a release. Reports last seven days.
Use **Windows checks** as the required status check after it has passed once.

## Windows preview

Run **Actions → Windows preview → Run workflow** on main when you want another
build. The build job is read-only and repeats the source checks before packaging.
It builds the EXE, exercises its actual UI, and archives the complete source from
the same exact commit. Other branches cannot run its build or publishing job.

After a successful build, a separate **Save draft release** job downloads only
that run's assets. It verifies checksums, source commit and successful test reports
before creating a draft prerelease. Only this job has permission to write release
contents. It does not check out or execute application source with that token.
Release downloads contain only the EXE and matching complete source ZIP. Test
reports, screenshots, checksums and build metadata remain in the Actions artifact
for seven days. Reruns remove extra attachments from an unpublished draft for the
same source commit. An existing published release is never overwritten.

Publication is an explicit owner action. Building never changes repository
visibility or rewrites source history. The one-time private bootstrap cleanup
workflow has been removed.

The frozen entry point dispatches host/native child processes explicitly. Detached
helpers use independent extraction environments so resources survive launcher exit
([PyInstaller guidance](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#using-sys-executable-to-spawn-subprocesses-that-outlive-the-application-process-implementing-application-restart)).
`tools/frozen_smoke.py` tests the actual packaged UI, including stashing and reload.
Web assets, fonts and notices, backend source helpers, JS GIF encoders and the OCR
PowerShell helper are bundled. Edge, FFmpeg and Cloudflare Tunnel remain external
optional prerequisites. Runtime data stays outside the executable and source.

Before publishing a later release, extract and scan both artifacts, test on a
clean Windows user profile and record signing status. Publish the EXE and complete
source ZIP together; retain the verification reports and checksums in the build
artifact. Build success alone does not establish
clean-install readiness. See [repository settings](REPOSITORY_SETTINGS.md) for
the owner-controlled switches.
