# DESKTOP APP BUILD & LAUNCH STANDARD

Version: 2.0 — 2026-09

This document defines the build, local desktop launch, Windows App Mode behavior, icon handling, desktop shortcut, version management, and rebuild workflow for local Windows desktop app projects that use a web UI and local backend/frontend services.

Use this document only for projects that intentionally follow this local desktop app pattern. Do not apply it automatically to unrelated web, mobile, API-only, cloud-deployed, Electron, CLI, package/library, or Docker-only projects.

## 1. Scope

This standard is appropriate when a project uses some or all of the following:

- local backend and/or local frontend services
- Windows `.bat` / `.vbs` launch scripts
- Chrome or Microsoft Edge App Mode
- a dedicated desktop shortcut
- a dedicated Taskbar/Start icon
- `Build.bat` as a one-click rebuild command
- version synchronization across app config and UI

If a project does not provide `Build.bat`, follow that project's own build and verification workflow instead.

## 2. Version and UI versioning

- Initial version: `v1.0` / Semver `1.0.0`.
- Show the app version badge, such as `v1.0`, near the app name in the sidebar, navigation area, or main title area.
- Update the HTML title in `index.html` using this pattern: `<App Name> v1.0`.
- When the version changes, synchronize it across the relevant backend config, `package.json`, UI version dictionary/config, and `index.html`.

## 3. Silent launchers and shutdown

### `START.vbs`

Use `WScript.Shell` to run `START.bat` with hidden window style `0` / `vbHide` and non-blocking execution.

The app must not flash or leave any visible black CMD/console window.

### `START.bat`

The launcher should:

- detect Python from `.venv` first, then system Python if needed
- detect Node.js when the project has a separate frontend
- start backend and frontend services in the background
- locate Google Chrome or Microsoft Edge automatically
- open the app in standalone App Mode with the required flags:

```bat
--start-maximized --app="http://127.0.0.1:<PORT>" --user-data-dir="<DATA_DIR>\browser_profile" --no-first-run --no-default-browser-check
```

### `STOP.bat`

The shutdown script should:

- check and release backend/frontend port listeners
- stop all project background processes safely
- avoid killing unrelated user processes when possible

## 4. Windows Taskbar icon standard

When the app runs through Chrome/Edge App Mode, use a dedicated browser profile and complete icon declarations so Windows can group and display the app separately from normal Chrome/Edge windows.

### Required icon assets

Store app icons in `assets/` and the frontend static/public folder when applicable:

- `favicon.ico` with multiple sizes: 16, 24, 32, 48, 64, 128, 256px
- `favicon-16x16.png`
- `favicon-32x32.png`
- `icon-192.png`
- `icon-512.png`
- `icon.png`
- `manifest.json`

The web app manifest should declare standalone display behavior and theme color when applicable.

### Required HTML declarations

`index.html` should include:

```html
<link rel="shortcut icon" href="/favicon.ico" type="image/x-icon" />
<link rel="icon" type="image/x-icon" href="/favicon.ico" />
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png" />
<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png" />
<link rel="apple-touch-icon" sizes="180x180" href="/icon.png" />
<link rel="manifest" href="/manifest.json" />
```

### Dedicated user data directory

The App Mode launch command must include `--user-data-dir` to isolate the app browser profile and help Windows assign a separate Taskbar group and icon.

## 5. Desktop shortcut

Create a shortcut helper such as:

- `utils/create_shortcut.py`
- `Create_Shortcut.bat`

Shortcut standard:

- Location: `%USERPROFILE%\Desktop\<App Name>.lnk`
- TargetPath: `C:\Windows\System32\wscript.exe`
- Arguments: `//nologo "<PROJECT_ROOT>\START.vbs"`
- WorkingDirectory: project root
- IconLocation: `<PROJECT_ROOT>\assets\icon.ico,0`
- Description: `<App Name> (App Mode)`

Reason: using `wscript.exe` as the target allows users to right-click and choose **Pin to Taskbar** or **Pin to Start** directly on Windows.

## 6. One-click build system

### `Build.bat`

Place `Build.bat` at the project root.

It should call a build script such as `scripts/build_app.py`.

Recommended arguments:

```bat
Build.bat
Build.bat --bump minor
Build.bat --set-version <version>
Build.bat --no-bump
```

Recommended default behavior:

- `Build.bat` increments patch version by default, for example `1.0.0 -> 1.0.1`.
- Use `--no-bump` when rebuilding without a version increase is required.

### `scripts/build_app.py`

The build script should:

- read and update Semantic Version: `major.minor.patch`
- synchronize version across config and UI files
- synchronize or generate icons and `manifest.json`
- validate source syntax when practical
- rebuild the frontend bundle if applicable, for example `npm run build`
- call the shortcut helper to update the desktop shortcut when applicable
- print a clear completion banner/status report

## 7. Coding workflow rule

After a coding task that changes code, UI, config, launcher, packaging, versioning, or app behavior:

1. Run `Build.bat` from the project root before reporting completion.
2. Run tests, lint, typecheck, or other quality checks if the project provides them and they are relevant.
3. Do not create a Git commit automatically.
4. Create a Git commit only when the user explicitly requests it.

During implementation:

- Do not run `Build.bat` after every tiny intermediate edit.
- Run `Build.bat` once when the task is ready to verify, unless an earlier build is needed for debugging.
- If `Build.bat` fails, do not report the task as complete.
- Fix only failures related to the current task, then rerun the relevant check.
- If a visual/UI task needs user review, report that the build passed and wait for user confirmation before committing.

Final report should include:

- files changed
- `Build.bat` result
- tests/lint/typecheck result, if run
- remaining issue, if any
- note that Git commit was not created unless explicitly requested

## 8. Relationship with `AGENTS.md`

`AGENTS.md` should contain only the short mandatory rule that tells the agent when to run `Build.bat` and when to read this build document.

This document is the detailed project build reference. Agents should read it only when the task touches launcher, packaging, versioning, desktop shortcut, icon, Windows App Mode, or build behavior.
