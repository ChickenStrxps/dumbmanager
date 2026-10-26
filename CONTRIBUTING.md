# Contributing

Keep changes small enough to try. Explain what was awkward, what changed, and
what you actually checked. Use disposable records for tests. Never attach keys,
real chats, screenshots of private work, or saved runtime state.

Please keep provider connections optional, source access explicit, sharing under
user control, and itch acceptance a separate user action. Keep the licensed font
notices with the fonts. Read docs/BUILD.md before changing packaging.

Pull requests run the read-only **Windows checks** job. Update
`SOURCE-MANIFEST.json` entries for changed or added files so the inventory check
matches the submitted source. Release builds are started separately by a maintainer;
see [Build and checks](docs/BUILD.md).
