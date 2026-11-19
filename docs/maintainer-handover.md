# Compact Virtual Mirrors maintainer handover

Compact Virtual Mirrors is Steam Workshop item `3842480345`. ETS2 Configurable Mirrors is the Windows editor and CLI for making a custom local mod. Both use the same HUD builder and override `ui/hud_left.sii` and `ui/hud_right.sii`. The editor's **Apply Compact preset** action and Workshop staging both read [`mirrors/compact.ini`](../mirrors/compact.ini). The root `config.ini` is the CLI's default editable layout.

The editor and Workshop package have independent version numbers. The editor's `v0.2.0` tag follows `VERSION` in `mirrors/release_info.py`. The initial Workshop package uses `MOD_VERSION = "1.0.0"` from `mirrors/workshop.py` in its manifest and targets ETS2 `1.62.*`. The repository records a successful build from ETS2 `1.62.3.3s`. The repository has no recorded in-game result for placement or F2 cycling.

## When ETS2 updates

1. Record the exact ETS2 build. Use the official SCS Game Archive Packer to extract that build's HUD pair into a fresh folder under ignored `source_ui/`. ETS2 `1.62.3.3s` supplied both files in `base_share.scs`. Check the archive layout again if the pair is missing. Keep the prior extraction and last validated Workshop upload folder available for comparison and rollback. [Extraction instructions](../README.md#build-and-install-a-mod)
2. Run a local Compact build using the new extraction. From PowerShell at the repository root, substitute your actual extraction folder and use a fresh output directory. A source path can point to the extraction root or its `ui` subfolder.

   ```powershell
   $source = '.\source_ui\ets2-target-build'
   $local = '.\output\local-target-build'
   .\build.bat --config .\mirrors\compact.ini --source $source --output $local
   .\.venv\Scripts\python.exe -m zipfile -l "$local\ets2_configurable_mirrors.scs"
   ```

   The archive should contain exactly `ui/hud_left.sii` and `ui/hud_right.sii`. For a custom layout, pass your saved INI to `--config`.
3. If the build rejects a fresh HUD pair, compare it with the last working inputs. Start at `inspect()` in [`mirrors/hud.py`](../mirrors/hud.py) and use the reported path and unit or field to locate the difference. Verify the new hierarchy and bindings before changing validation. Add a synthetic fixture for the new structure and run it alongside the existing fixture. Keep extracted game files and generated archives out of Git.
4. Install the candidate in the ETS2 user directory's `mod` folder and enable it for a test profile in Mod Manager. Disable the public Workshop item and other mods that replace the mirror HUD for that profile. In the cab, verify both mirrors and their frames, cycle through the F2 states, and confirm native placement and cycling after disabling the candidate. Check `game.log.txt` in the ETS2 user directory for HUD or mod-loading errors. Record the exact game build, resolution, display mode or aspect ratio, outcome, and any log errors. Capture an in-game screenshot for visible changes.

## Update the Steam Workshop item

1. Set `MOD_VERSION` in [`mirrors/workshop.py`](../mirrors/workshop.py) for the Workshop release. Stage a candidate with the extracted source from the build you tested. Use a new output folder each time. The stager expects the destination to be absent.

   ```powershell
   $compatibility = Read-Host 'Tested Workshop compatibility pattern'
   $stage = '.\output\workshop-target-build'
   .\.venv\Scripts\python.exe -m mirrors.workshop --source $source --output $stage --compatibility $compatibility
   ```

2. If you support multiple game versions, make a copy of the last validated upload folder and merge the candidate into that copy. The stager produces one playable package and an `unsupported` informational package. Keep the playable folders for previously supported builds and add the candidate's playable folder and entry to the combined `versions.sii`. Use distinct unit names such as `.compact_1_62` because the stager emits `.compact` each time. Give each playable package a distinct folder name and avoid overlapping compatibility patterns. If a patch within a supported series needs a different HUD, narrow the previous wildcard to verified builds before adding the patch-specific entry. Keep one `informational: true` fallback and update its description to reflect the supported versions. [SCS Workshop versioning](https://modding.scssoft.com/wiki/Tutorials/SCS_Workshop_Uploader/How_to_use_mod_versioning)
3. In SCS Workshop Uploader, select ETS2 and validate the complete folder as **Mod data**. Use a private test item for a subscription smoke test with the local candidate disabled. Then update existing item `3842480345` with the validated folder, change note, and supported game versions. Archive the exact uploaded folder outside Git. If an update breaks a previously supported build, use the last validated folder to restore that package and its `versions.sii` entry. [Workshop staging and listing assets](../workshop/README.md)

## Maintain and release the Windows editor

From a fresh checkout, install the development dependencies with Windows x64 Python 3.11 or newer. The example uses 3.12, which the release script requires.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
.\run_gui.bat
```

The automated suite uses synthetic SII fixtures and an offscreen Qt platform. For GUI changes, also open the editor interactively and check opening and saving an INI and building and installing from the current layout. Keep old INIs usable. Saves preserve extra keys and sections and create an `.ini.bak` when replacing an existing config. The GUI builds the layout on screen, including unsaved edits. The CLI reads the selected INI. The packaged editor keeps its default config and output in writable Windows app data.

1. Commit the release source and make sure the matching tag points to that commit. For the replacement v0.2.0 upload, reuse the v0.2.0 tag and keep `VERSION` at `0.2.0`. For a new version, update `VERSION` in [`mirrors/release_info.py`](../mirrors/release_info.py) and create the matching tag. Run `./release.ps1 -Tag v0.2.0` from the clean tagged checkout, substituting the actual tag for future releases. The build runs tests and launches the final EXE under `dist` before generating its checksum.
2. Attach the EXE, checksum, notices ZIP, and source ZIP from that build to a GitHub Release draft. When replacing v0.2.0, move the existing release back to draft and replace all four assets so the executable, checksum, and source refer to the same build. With an authenticated GitHub CLI, use `gh release edit v0.2.0 --draft` to set draft status. [GitHub CLI release edit](https://cli.github.com/manual/gh_release_edit)
3. Download the draft EXE and `SHA256SUMS.txt` into a fresh directory. For example, save them to `$env:TEMP\mirrors-draft` and run:

   ```powershell
   .\verify-release.ps1 -ReleaseDirectory .\dist\v0.2.0 -DownloadDirectory "$env:TEMP\mirrors-draft"
   ```

4. On clean Windows 10 and 11 x64 machines, browser-download the verified draft EXE. Use a fresh standard Windows account with default security settings and no separately installed Python, Qt, VC++ Redistributable, Steam, or ETS2. Disconnect from the network, double-click the EXE, confirm the editor opens directly, apply the Compact preset, then save and reopen an INI. Record the tested Windows builds and any warnings or blocks. Label the EXE unsigned in the release notes.
5. Publish after the draft checks pass. Download the public EXE and checksum into a second fresh directory and run the same verifier with that directory. Announce the release only after the public check passes. If a download check fails, replace the affected assets and repeat the checks before announcement.

A Workshop-only compatibility update can ship independently of the editor. [Editor release process](../README.md#maintainer-releases)

## Where to make changes

| Change | Start here |
| --- | --- |
| Compact layout shared by the editor and Workshop | [`mirrors/compact.ini`](../mirrors/compact.ini) |
| New HUD syntax, preset bindings, or coordinate mapping | [`mirrors/hud.py`](../mirrors/hud.py), [`tests/conftest.py`](../tests/conftest.py), [`tests/test_core.py`](../tests/test_core.py) |
| Local archive contents, source validation, or installation | [`mirrors/builder.py`](../mirrors/builder.py), [`mirrors/cli.py`](../mirrors/cli.py) |
| Dragging, resizing, or layout constraints | [`mirrors/model.py`](../mirrors/model.py), [`mirrors/preview.py`](../mirrors/preview.py), [`mirrors/gui.py`](../mirrors/gui.py), [`tests/test_gui.py`](../tests/test_gui.py) |
| INI compatibility or folder detection | [`mirrors/config.py`](../mirrors/config.py), [`mirrors/preferences.py`](../mirrors/preferences.py) |
| Workshop package metadata and Windows packaging | [`mirrors/workshop.py`](../mirrors/workshop.py), [`release.ps1`](../release.ps1), [`release.spec`](../release.spec) |

For HUD changes, preserve the camera bindings and anchors, and apply custom geometry to all four native presets on each edited side. `transform()` scales the top-left editor coordinates to the source window bounds and reverses Y. A side set to `use_game_defaults = 1` passes its validated source HUD through byte for byte. Keep PySide6 out of the CLI and shared build code so the CLI can still run with the standard library alone.
