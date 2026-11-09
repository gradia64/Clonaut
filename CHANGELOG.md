# Changelog

All notable changes to Clonaut are listed here. Versions follow
[Semantic Versioning](https://semver.org/).

## [0.4.0] — 2026-11-09

### Added
- **English user interface.** Clonaut follows the system language (Italian
  when the system is in Italian, English otherwise); *File → Settings…* has a
  new *Language* option and `CLONAUT_LANG=en|it` overrides both. Qt's own
  buttons and dialogs follow too. Translations are gettext `.po` catalogs in
  `clonaut/locale/`, read directly (no build step); `scripts/update-po.py`
  extracts the texts and lists what is left to translate.
- Standard Python packaging (`pyproject.toml`): `pip install .` provides the
  `clonaut` command; `python -m clonaut` works too.
- AppStream metadata (`io.github.gradia64.Clonaut.metainfo.xml`) and PNG icons
  (48–256 px) next to the SVG.
- **Choose which rclone to use**: `CLONAUT_RCLONE` environment variable, a new
  *rclone program* field in *Settings*, `PATH`, or a copy
  bundled with the AppImage — in this order. The About dialog shows the path.
- AUR packages `clonaut` (from the release tag) and `clonaut-git`, tested in
  a clean Arch container (`packaging/aur/test-in-docker.sh`).
- **AppImage** for x86_64 and aarch64 (`build-appimage.sh`): portable Python,
  PyQt6 trimmed to what Clonaut uses, the official rclone 1.76.0 as a
  fallback, static type2 runtime (no FUSE needed), update information and
  `.zsync` for Gear Lever / AppImageUpdate. Every download is pinned by
  SHA-256; x86_64 tested on Debian 12, Ubuntu 22.04/24.04, Fedora 45, Arch
  and openSUSE Tumbleweed, aarch64 on Debian 13, Ubuntu 24.04, Fedora 45 and
  openSUSE Tumbleweed (`packaging/appimage/test-distros.sh`).
- **Signed release tags** with the Clonaut release key
  (`packaging/clonaut-release-key.asc`); `scripts/verify-tag.sh` checks them
  and the AUR package verifies the tag before building.
- **GitHub Actions**: CI on every push and pull request (tests with Python
  3.10–3.14 and both Qt bindings, AppStream and desktop-file validation,
  `.deb` with lintian, shellcheck); release workflow on signed `v*` tags that
  builds and tests the `.deb` and both AppImages and attaches them with
  `SHA256SUMS` and build-provenance attestations
  (`gh attestation verify <file> -R gradia64/Clonaut`).
- `CLONAUT_QT=pyqt6|pyside6` picks the Qt binding.
- Automated test suite (pytest, Qt offscreen, real rclone), passing with both
  Qt bindings on rclone 1.75.2 and 1.76.0.

### Changed
- README and AppStream screenshots show the English interface (the Italian
  README keeps Italian ones), and the English README uses the English menu
  and button names.
- Desktop ID is now `io.github.gradia64.Clonaut` (`.desktop` file and icon
  name); menu shortcuts to the old `clonaut.desktop` are recreated.
- Startup code moved from `main.py` to `clonaut/app.py`; `main.py` and
  `run.sh` still work.
- If rclone is missing, the error lists every place that was checked.
- If no Qt binding can be imported, the error shows the real reason for each
  binding (often a missing system library).

### Fixed
- **Scheduled transfers stopped running after the window was closed.** With
  *Close to tray* off, the close button stopped the rclone daemon, but on KDE
  the tray icon kept the app running without it: ⏰ schedules never started
  again and *Run now* failed silently. Closing now really quits the app.
- When the rclone daemon does not respond, transfers and schedules show the
  error ("rclone rcd is not responding…") instead of failing silently.
- Possible crash with PySide6 6.12.0 when Python's garbage collector ran in a
  background thread: it now runs only in the GUI thread.

## [0.3.1] — 2026-11-08

First public release.

### Added
- **Edit scheduled transfers** (⏰): right-click → *Modifica…*, or double-click
  the row. Paths, mode, exclusions, trash and interval can be changed; a run in
  progress keeps its settings and the changes apply from the next run.
- **Help → About Clonaut** (*Aiuto → Informazioni su Clonaut*) with the versions
  of Clonaut, rclone, Qt and Python and the app's data folder; *About Qt* too.
- The window title shows the version (e.g. "Clonaut 0.3.1").
- Long intervals are shown in days ("1g 23h" instead of "47h 59m").

### Fixed
- **Tray icon:** a single left click now brings the window to the front, or
  hides it when it is already in front. Before, only the right-click menu
  could restore it.
- The status bar showed the rclone version as "vv1.75.2".
- Dry-run rows in the queue did not show mode, source and destination.
- New-remote form: labels from the previously selected type could stay on
  screen, and long drop-downs caused horizontal scrolling.
- New-transfer dialog: long texts were cut off.

### Changed
- README in English, with the Italian version in `README.it.md`.
- English package description and desktop entry (Italian translations kept).

## [0.3.0] — 2026-11-08

### Changed
- Renamed from "GUI rclone" (`gui-rclone`) to **Clonaut** (`clonaut`). The new
  package replaces the old one, and settings and schedules are migrated from
  `~/.config/rclone-gui/` on first launch.

### Fixed
- The `.deb` failed to start with PyQt6, its declared Qt dependency.
- Ticking "Cestino" (safety trash) in the new-transfer dialog raised an error.
- "Rimuovi completati" (clear finished) rows came back after one second.
- Every run of a scheduled transfer left a duplicate row in the queue.
- Daemon credentials were visible to other users through `ps`; they are now
  passed through the environment.
- New-remote form: example values could not be overridden (e.g. a custom S3
  endpoint), and backends repeating an option (Koofr) lost values.
- Clean exit from the tray and while a dry run is in progress; "run now" works
  on paused schedules; a corrupted `recurring.json` no longer blocks startup.

### Added
- Dry runs report how many files would be deleted.
- Old daemon logs are removed after 7 days.

## [0.2.0] — 2026-11-08

First packaged version (as "GUI rclone").

[0.4.0]: https://github.com/gradia64/Clonaut/releases/tag/v0.4.0
[0.3.1]: https://github.com/gradia64/Clonaut/releases/tag/v0.3.1
[0.3.0]: https://github.com/gradia64/Clonaut/commit/5f69e4a
[0.2.0]: https://github.com/gradia64/Clonaut/commit/5f69e4a
