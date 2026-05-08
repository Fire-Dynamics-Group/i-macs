# Release runbook — i-macs

End-to-end guide for cutting a release. Most steps are automated by
`.github/workflows/release.yml`; the bits that need human action (signing
key generation, repo secrets) are flagged below.

## One-time setup (do this before the first release)

### 1. Generate a Tauri updater signing keypair

The Tauri updater uses [minisign](https://jedisct1.github.io/minisign/)
signatures so installs can verify update artefacts came from you. Generate
the keypair with the Tauri CLI:

```powershell
npx @tauri-apps/cli signer generate -w $HOME\.tauri\i-macs.key
```

You'll be prompted for a passphrase. **Keep that passphrase and the
generated `.key` file** — they're needed for every release. Back them up
to a password manager. Losing them forces every existing install to be
reinstalled by hand because they can no longer verify update signatures.

The CLI prints both the private key (the `.key` file content) and a
public key. Capture both.

### 2. Add repo secrets

Go to <https://github.com/Fire-Dynamics-Group/i-macs/settings/secrets/actions>
and add:

| Secret name                              | Value                                                             |
|------------------------------------------|-------------------------------------------------------------------|
| `TAURI_SIGNING_PRIVATE_KEY`              | Full content of `i-macs.key` (the `untrusted comment: ... RWT...` block) |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`     | The passphrase you typed in step 1                                |

### 3. Wire the public key into `tauri.conf.json`

Open `src-tauri/tauri.conf.json` and replace the `pubkey` placeholder with
the generated public key (the base64 `dW50cnVzdGVkIGNvbW1lbnQ6...` block):

```json
"plugins": {
  "updater": {
    "endpoints": [
      "https://github.com/Fire-Dynamics-Group/i-macs/releases/latest/download/latest.json"
    ],
    "pubkey": "<paste public key here>",
    ...
  }
}
```

Commit + push this change. The pubkey is meant to be public — it ships
inside every install — only the private key is sensitive.

## Per-release runbook

Once the one-time setup above is complete, every release is just:

1. Bump the version in **three places** (they must all agree, otherwise
   the updater compares the wrong values):
   - `package.json` → `version`
   - `src-tauri/tauri.conf.json` → `version`
   - `src-tauri/Cargo.toml` → `[package].version`
2. Commit the bumps:
   ```powershell
   git commit -am "Release v0.1.0"
   ```
3. Tag and push:
   ```powershell
   git tag v0.1.0
   git push origin main --tags
   ```
4. Watch the workflow at
   <https://github.com/Fire-Dynamics-Group/i-macs/actions>. ~10–15 min
   first run (Rust cache cold), 5–8 min subsequent.
5. On success: a GitHub Release is published with the `.exe` installer
   plus a `latest.json` updater feed. Existing installs pick the update
   up on next launch (silent check via `App.tsx` → `checkForUpdates`).

## Cutting a release candidate first

Tag with an `-rc.N` suffix to publish a pre-release without flipping the
"latest" pointer:

```powershell
git tag v0.1.0-rc.1
git push origin --tags
```

Note: the workflow currently sets `prerelease: false` unconditionally —
edit `.github/workflows/release.yml` if you want `-rc` tags to be marked
as pre-releases on GitHub.

## Local smoke before tagging

Run a clean local build to catch issues before they go through CI:

```powershell
# 1. Rebuild the sidecar bundle (32-bit venv must be active).
.\scripts\build-sidecar.ps1

# 2. Build the React frontend + Tauri shell.
npm run build
```

The output lands in `src-tauri/target/release/bundle/nsis/` —
double-click the `.exe` to install in your user profile. Uninstall via
the standard Windows uninstaller.

## Troubleshooting

- **Workflow fails at "Build, sign, and publish"** — almost always the
  signing secrets. Check both env vars are present and the private key
  isn't truncated.
- **`actions/setup-python@v5` reports "no matching version"** for x86 —
  upgrade to the latest setup-python; older versions don't honour
  `architecture: x86` for cp310.
- **Updater says "no update available" right after a release** — GitHub
  caches the `latest.json` URL for ~5 min. Wait or open
  `https://github.com/Fire-Dynamics-Group/i-macs/releases/latest/download/latest.json`
  directly to confirm the new version landed.
