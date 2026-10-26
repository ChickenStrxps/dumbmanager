# Preview status

A public [Windows preview](https://github.com/ChickenStrxps/dumbmanager/releases/tag/preview-2f2de9718cf6) is available.
Its two downloads are **DumbManager.exe** and the matching complete source ZIP.
The executable is unsigned. The published build is pinned to commit
`2f2de9718cf617174c127dc298745074298a7445`; main may include later documentation,
artwork and workflow changes.

The source includes itch intake/evidence, plans/refactor/review/acceptance,
research, learning, Suggested/manual scout, public Inspiration readers, suggestive
typing, Jev/Mercury, Browse, T3 chats/handoffs/attachments, DumbBridge, completion
GIFs/privacy/sharing/webhooks, generic Git/source/MCP, native and phone modules.

Private analytics, authored edit/batch tools and captured-account feeds are absent.
Posting notes accept manually supplied links and do not claim verification.
Fresh defaults have no projects, records or connections.

## Verified

- Source inventory and syntax checks passed.
- Windows CI passed 233 API tests and 34 host tests; four optional API tests were skipped.
- Disposable first-run and browser checks passed at desktop, 390px and 320px widths.
- The packaged preview passed its hosted executable UI and start/stop checks.

See [Actions](https://github.com/ChickenStrxps/dumbmanager/actions) for the exact
commit and run results. CI uses disposable data and synthetic fixtures.
Reports, screenshots and checksums stay in Actions artifacts for their retention
period; release downloads contain only the EXE and source ZIP.

## Still needs testing

- A clean Windows user profile: first run, restart, upgrade and removal.
- Real Jev/Mercury/T3/Discord/webhook connections using the tester's own accounts.
- Phone access and native capture, clipboard, OCR, replay and animated-card flows
  on real devices.

Passing hosted or mocked checks does not establish live-service or clean-machine
readiness. See [setup](SETUP.md) for prerequisites and connections.

The manual **Windows preview** workflow prepares a draft for owner review.
Publishing a draft is a separate owner action. The existing preview is already
public; building another candidate does not replace it or change repository
visibility.
