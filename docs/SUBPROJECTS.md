# Subprojects

## DumbLighting

`projects/dumb-lighting` is an optional Git submodule pointing to the private
[DumbLighting repository](https://github.com/ChickenStrxps/dumb-lighting). It
contains six SignalRGB effects and a Windows context switcher. Its source,
issues, pull requests and checks live in that repository; the parent records
one reviewed commit. Private repository access is required to initialize it.

After cloning DumbManager, opt in with:

```sh
git submodule update --init projects/dumb-lighting
```

The default clone, existing CI and app packaging do not fetch the private module.
DumbManager runs without it. Do not use a recursive clone unless you have access
and intend to fetch every optional subproject. GitHub source ZIPs do not include
submodule contents. Follow the child's README to install effects or the watcher;
cloning or updating a pointer never installs or launches lighting software.

Land lighting PRs in the child first. To advance the parent's pinned version:

```sh
git -C projects/dumb-lighting fetch origin
git -C projects/dumb-lighting checkout <reviewed-child-commit>
git add projects/dumb-lighting
```

Update the corresponding `submodules` entry in `SOURCE-MANIFEST.json`, then open a
parent PR. Keep the module optional and do not add recursive checkout or private
credentials to public CI. Existing app builds and releases remain independent.

## DumbVoice

`projects/dumbvoice` is an optional Git submodule pointing to the private
[DumbVoice repository](https://github.com/ChickenStrxps/dumbvoice), formerly Voice
Dock. It provides native Windows dictation with local speech recognition,
personal vocabulary and optional insertion into the focused editable field.
Its source, history, pull requests and checks stay in that repository.

With separate repository access, initialize only this subproject:

```sh
git submodule update --init projects/dumbvoice
```

Follow the child's README to build and install it. Checkout never starts the app,
captures audio or imports settings. The module is absent from source ZIPs and
optional for parent builds and CI. Public CI does not fetch it or need credentials.

Land changes in the child first, then update the reviewed pin:

```sh
git -C projects/dumbvoice fetch origin
git -C projects/dumbvoice checkout <reviewed-child-commit>
git add projects/dumbvoice
```

Update its `submodules` entry in `SOURCE-MANIFEST.json` in the same parent PR.
Both subprojects can be initialized and updated independently.
