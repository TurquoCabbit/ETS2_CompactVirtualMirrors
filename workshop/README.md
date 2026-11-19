# Compact Virtual Mirrors

**Steam title** · Compact Virtual Mirrors  
**Author** · TurquoCabbit  
**Initial mod version** · 1.0.0  
**Initial game series** · ETS2 1.62

## Listing description

Moves the left and right virtual mirrors into compact frames in the top corners, leaving more of the windshield visible. Subscribe, then enable Compact Virtual Mirrors in ETS2 Mod Manager. Press F2 to use the game's virtual mirror controls.

Use one mod that changes the virtual mirror HUD at a time. The layout was designed on a 1920 × 1080 reference canvas. Placement can vary with display aspect ratio and ETS2 settings.

Want to move or resize the mirrors? Download ETS2 Configurable Mirrors for Windows, apply the Compact preset, and build a local mod using HUD files from your own game installation. Disable this Workshop item before enabling your custom build. [Editor releases](https://github.com/TurquoCabbit/ETS2_CompactVirtualMirrors/releases)

**Initial change note** · Adds compact virtual mirrors in both top corners.

## Staging and validation

Run from the repository root with the HUD pair extracted from the ETS2 build you plan to test.

```powershell
.\.venv\Scripts\python.exe -m mirrors.workshop --source .\source_ui --output .\output\workshop-compact-162
```

Select the generated folder as **Mod data** in SCS Workshop Uploader. Select `preview.jpg` from this directory for the listing. Add a real in-game screenshot after validation. Select ETS2, the UI category if offered (otherwise Others), and Private visibility for the first upload. [SCS upload guide](https://modding.scssoft.com/wiki/Tutorials/SCS_Workshop_Uploader/How_to_upload_new_mod%3F)

1. Confirm distribution rights for the modified HUD files and listing assets under the applicable SCS and Steam terms. [SCS modding policy](https://blog.scssoft.com/2019/04/important-notice.html) · [Steam Subscriber Agreement](https://store.steampowered.com/subscriber_agreement/)
2. Resolve uploader validation errors. Subscribe to the private item and disable any local or subscribed mirror HUD override. Use a clean ETS2 profile to verify both mirror positions, F2 cycling, and restoration after disabling the item. Record the exact game build, resolution, and any game log errors.
3. Publish the tested item alongside the GitHub release and link to the Workshop page from the editor README. When a new ETS2 version changes the HUD, validate its own package before adding it to `versions.sii`. Keep previously tested packages when updating the same item. The informational package covers game versions without a matching HUD package.
