# 10 — Deployment

## Deployment model

CredCodex is a **local macOS app** — there is no server, no cloud deployment, and no CI/CD pipeline in the repository. "Deployment" means distributing or installing the app bundle on a user's machine.

## Build

```bash
bash build_app.sh
```

Produces `dist/CredCodex.app`. Requires:
- `python3`, `cc`, `sips`, `iconutil`, `plutil` on PATH
- The `credcodex` package importable (run `pip install -e .` first)

The C launcher (`CredCodex` binary inside the `.app`) has the repo path embedded at compile time via `@@REPO_DIR@@` substitution. The built bundle is **not relocatable** — it will only work from the directory where it was built.

## Install

```bash
bash install.sh
```

- Creates `./venv`, installs package, builds bundle.
- Copies bundle to `~/Applications/CredCodex.app`.
- Writes launchd plist to `~/Library/LaunchAgents/com.local.credcodex.plist`.
- Bootstraps the launch agent and opens the app immediately.

`Confirmed from code — install.sh`

## Uninstall

```bash
bash uninstall.sh
```

- Quits the running app.
- Removes the launchd login item.
- Removes `~/Applications/CredCodex.app`.
- Leaves `~/.credcodex/` intact (user data preserved).

## Launchd plist (`install.sh`)

```xml
<key>ProgramArguments</key>
<array>
  <string>open</string>
  <string>-a</string>
  <string>~/Applications/CredCodex.app</string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><false/>
```

`KeepAlive` is false — if the process crashes, launchd will not restart it. Single-instance is enforced by the PID lock, not by launchd.

## Environment separation

`Not found in repository` — no staging vs production environments. The app targets production OpenAI endpoints directly.

## Risks and failure points

- **Non-relocatable bundle**: the C launcher embeds the absolute repo path. Moving or copying the app elsewhere breaks it; re-run `install.sh` to rebuild.
- **Venv tied to repo**: the launcher looks for `$REPO_DIR/venv/bin/python`. If the venv is deleted or the repo moved, the app shows an error dialog and exits.
- **No code signing**: the app bundle is unsigned. macOS Gatekeeper may block first launch on some security settings. Users may need to allow it in System Settings → Privacy & Security.
- **No auto-update mechanism**: users must re-run `install.sh` to update.
- **macOS permission prompts**: `osascript` automation of Terminal and notification delivery require user permission grants on first use.
