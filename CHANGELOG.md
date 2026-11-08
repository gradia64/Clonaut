# Changelog

All notable changes to Clonaut are listed here. Versions follow
[Semantic Versioning](https://semver.org/).

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

[0.3.1]: https://github.com/gradia64/Clonaut/releases/tag/v0.3.1
[0.3.0]: https://github.com/gradia64/Clonaut/commit/5f69e4a
[0.2.0]: https://github.com/gradia64/Clonaut/commit/5f69e4a
