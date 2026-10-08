# Read-only inspector and ARM64 AppImage — 2026-10-07

The Rust backend and existing Lepton inspector now preserve the CLI's separate
fixed-proxy, generated-function, local-validation, hardware-evidence and
non-function states. An ARM64 AppImage includes the pinned private LLVM 20.1.8
reader. Its actual packaged backend passed four native Steam Frame cases.
The native GTK/WebKit inspector also passed 15 actual control/dialog checks
through AT-SPI, including analysis, artifact selection, refresh and close.

No commits or pushes were made. Existing workspace changes were preserved.
No installed game files were changed, no production context was started or
stopped, and no game process was injected. Packaging did not install anything
into the immutable SteamOS host. Linux-host tests used the isolated directory
`/tmp/creamlinux-inspector-validation/`; Android proxy evidence remains the
earlier dedicated-context result documented in
[JOBSIMULATOR_HARDWARE.md](JOBSIMULATOR_HARDWARE.md).

## Explicit read-only launch modes

```bash
APPIMAGE_EXTRACT_AND_RUN=1 WEBKIT_DISABLE_DMABUF_RENDERER=1 \
  ./Creamlinux_1.7.1_steam-frame-inspector_aarch64.AppImage \
  --lepton-inspector 448280
```

This entrypoint bypasses legacy installer/cache startup tasks and exposes only
game metadata, Lepton introspection and compatibility analysis through the
custom command dispatcher. The GUI has no proxy installation action. Artifact
selectors accept an existing generated directory and paired hardware bundle /
results directory. Analysis is manual; refresh clears the result. Async results
are guarded against stale game/refresh/artifact selection responses.

The same backend can run without GTK or installer startup:

```bash
APPIMAGE_EXTRACT_AND_RUN=1 ./Creamlinux_1.7.1_steam-frame-inspector_aarch64.AppImage \
  --lepton-compatibility 448280
```

Optional headless arguments are `--target-proxy-dir ABSOLUTE_DIRECTORY`,
`--hardware-bundle ABSOLUTE_FILE`, and `--hardware-results ABSOLUTE_DIRECTORY`.
Hardware inputs require all three. These inspect existing artifacts; they do
not generate, deploy or install proxies. Stdout is JSON; completed fixed-proxy
compatibility/incompatibility retains exit 0/1, operational incompleteness 2.
The backend adds `analysis_exit_code` while retaining the existing keys.

Use these explicit modes for compatibility review. Default application startup
still follows the repository's existing installer behavior and was not used
during hardware testing.

## Actual packaged Frame results

Final artifact, outside the repository directory:
`../Creamlinux_1.7.1_steam-frame-inspector_aarch64.AppImage`.

SHA256:
`cb5f6616e264139aa9bbc1bcecd49004c00a61afb0965e2777328435a575ec85`.

The transferred image had the same hash. Its extracted private runtime passed
all **10 SHA256SUMS entries**, including its manifest and licenses. All ten
excluded Wayland/XKB/XCB/X11 library families were absent throughout bundled
`usr/lib`. Host Python and private LLVM were used without a reader override.

| Native packaged-backend case | Exit | Measured outcome |
| --- | --- | --- |
| Live Job Simulator, default | 1 | fixed false; target `not_generated` |
| Live Job Simulator, explicit matching artifact/bundle/logs | 1 | fixed false; target `hardware_validated` |
| Hardware results without other required artifacts | 2 | incomplete JSON with actionable note |
| Stopped Walkabout context | 2 | incomplete JSON; no context started |

Both completed Job cases retained provider SHA256
`345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700`,
1365 public / 1156 function exports, and fixed coverage 1036/1156. The second
case reverified the actual provider, generated binary, bundle and complete
hardware logs. Hardware status was not inherited from AppID or a summary file.

Native GUI observation: the identified `Lepton compatibility inspector` window
rendered Job Simulator's responsive running context, actual package
`com.owlchemylabs.jobsimulator` and `arm64-v8a` metadata. The initial launch's
stdout/stderr log was empty. Native file chooser tests subsequently retained a
nonfatal GLib mountinfo warning. The isolated inspector processes closed through
their own Close controls after testing. Window screenshots, four JSON/stderr
pairs, accessibility snapshots and package observation are retained under
`build/frame-inspector-results/` on the workstation.

The application startup log confirmed installer startup tasks were disabled.
Tauri also logged its AppImage-path warning: its installed version recognizes
`/tmp/.mount_*`, whereas extract-and-run used `/tmp/appimage_extracted_*`.
Resources still resolved and the packaged analysis passed; the warning was
retained rather than suppressed.

The initial browser-based test route exposed no available browser, and raw
targeted scroll events did not control GTK/WebKit. This was resolved using the
Frame's already-installed Python GI / AT-SPI bindings over the existing SSH
connection. Browser setup is unnecessary for the native workflows below.

## Actual native control and dialog validation

`scripts/test-frame-inspector-native.py` launches only `--lepton-inspector`,
requires the expected AppImage hash, and limits every node/action to that
isolated application's process group. It uses real accessibility actions and
editable-text interfaces, without JavaScript injection, test hooks, global
keyboard/mouse input or host package installation. Native GTK dialogs belonged
to the inspector itself. Picker inputs are limited to staged test fixtures.

Measured on the final image: **15/15 checks passed**, harness exit **0**.
The four packaged-backend cases above were also rerun on that same image.
Compact measured evidence:
[evidence/frame-inspector-ui-2026-10-07.json](evidence/frame-inspector-ui-2026-10-07.json).
Complete console and semantic UI snapshots are in `build/frame-inspector-results/`.

The checks cover running metadata; scrolling Analyze into view; default
analysis; native folder cancellation; generated-folder selection and stale
result clearing; local-only analysis; native bundle file selection; incomplete
evidence and its displayed note; native results-folder selection; hardware
analysis with precise provider/proxy identities while fixed compatibility
remains false; Refresh; clearing artifacts; clean Close; stopped-context
Analyze disabling; and stopped-context Refresh/Close without starting a game.
The last two behaviors are separate checks, giving 15 total.

Reproduce after staging the image and existing `evidence/{target,hardware-bundle.tar.gz,results}`:

```bash
python3 /tmp/creamlinux-inspector-validation/test-frame-inspector-native.py \
  --image /tmp/creamlinux-inspector-validation/Creamlinux-fixed.AppImage \
  --work-dir /tmp/creamlinux-inspector-validation \
  --expected-image-sha256 cb5f6616e264139aa9bbc1bcecd49004c00a61afb0965e2777328435a575ec85 \
  --stopped-appid 1408230
```

This Job Simulator fixture harness exercises the actual frontend/backend/dialog
path, rather than a browser preview with mocked Tauri calls. Clipboard Copy,
keyboard-only use and other desktop environments were not covered by these 15
checks. The compact GUI evidence is not imported as proxy hardware evidence.

## Failures and regression fixes

1. AppRun exports `PYTHONHOME`/`PYTHONPATH` for bundled applications. Host Python
   initially failed to import `encodings`, before producing JSON. Its process
   now runs with `-E -s -B`, ignores inherited Python configuration and drops
   bundled library/preload settings. A Rust regression executes this same
   command builder with invalid Python environment paths. Startup parse errors
   also retain useful bounded stderr diagnostics. The corrected AppImage
   passed the native cases above.
2. linuxdeploy rewrote private LLVM ELF RPATHs, invalidating the pinned payload
   hashes. Packaging now restores only the already-verified private resource
   files into the exact Creamlinux AppDir resource directory, checks the
   unchanged inventory/identity and verifies every hash again. Regressions
   cover rewritten ELF bytes, unexpected files and unsafe destinations.
3. The known QEMU AppImage plugin abort remained reproducible. Moving the cached
   plugin entirely out of linuxdeploy's plugin-search filenames and manually
   deploying GTK/GStreamer allowed the established x86 appimagetool fallback.
   No failing checksum or safety check was suppressed.
4. Actual native testing found that Close did not exit the inspector: the
   capabilities lacked `core:window:allow-close`, and its browser-window fallback
   did not close the native window. The missing permission was added for the
   existing `main` / `lepton-inspect-*` capability. After rebuilding/repackaging,
   actual Close exited both live and stopped inspectors cleanly. The native
   harness retains this end-to-end regression check.
5. Harness development encountered stale accessibility objects during React
   updates/dialog dismissal. Reads now process accessibility signals and retry
   only the observed disappearance with a bounded limit; actions and ownership
   failures are never retried or suppressed. An incomplete-evidence note was
   initially hidden inside collapsed details; the test now opens those details
   before checking it. These were test-harness issues, not app compatibility
   downgrades. Failed attempt logs remain available.

## Exact checks

- Python suite: **202 passed, zero skips** (194 previous + 8 resource tests).
- Rust suite: **51 passed, zero ignored**, including Python-environment,
  artifact/JSON preservation, running-state and entrypoint checks.
- Component rendering suite: **8 passed, zero skipped**; fixed incompatibility
  beside hardware function evidence, conservative Walkabout scope, no inherited
  status, mismatched/missing identity, operational errors, unknown states and
  escaped evidence/no installation controls.
- TypeScript check and Vite production build: passed.
- Targeted ESLint: zero errors; one fast-refresh warning
  for the report's exported testable label helper.
- `git diff --check` and packaging/hardware-runner shell syntax: passed.
- Native packaged backend: **4/4 cases passed** on the final image.
- Native GUI controls/dialogs: **15/15 checks passed**, harness exit 0.

This phase did not change the generator, loader or validated proxy bytes.
Earlier Walkabout 1045/1045 parity and 11047 legacy mock assertions remain
recorded in [VALIDATION_STATUS.md](VALIDATION_STATUS.md). The Python suite
reran their applicable regressions. Earlier Job Bionic results remain
1156/1156 mock targets, 11156 assertions, 8 loader rejection cases, 21 WEAK /
1135 GLOBAL, 420 weak/load-scope checks and 1156/1156 zero-call resolution.

Six-game CLI coverage remains Walkabout, Job Simulator, VRChat, VAIL, Into Black
and Dungeons of Eternity. Only the exact Job function artifact has hardware
evidence. No real split install was found; synthetic split/duplicate/ABI tests
remain passing. Job and four newer providers omit 209 non-function exports;
Walkabout omits four. No observed requirement is not proof of complete ABI or
gameplay compatibility. Walkabout's fixed scope remains
**Compatible for observed static consumers**.

## Build and packaging workflow

Stage the pinned reader with `npm run prepare:frame` (after building the runtime
as documented in [LLVM_RUNTIME.md](LLVM_RUNTIME.md)). Use the ARM64 build
environment for `npm run tauri build -- --config src-tauri/tauri.frame.conf.json`.
On QEMU, the expected final plugin failure still leaves Creamlinux.AppDir.

Move `linuxdeploy-plugin-appimage.AppImage` outside the cache plugin directory;
simply appending a disabled suffix is insufficient because discovery still
matches it. Run ARM64 linuxdeploy with `APPIMAGE_EXTRACT_AND_RUN=1`,
`DEPLOY_GTK_VERSION=3`, the produced AppDir/executable/desktop/icon and
`--plugin gtk --plugin gstreamer`. Then run `npm run package:frame` on x86_64.
The helper restores/verifies private reader resources, removes the ten
conflicting library families and uses appimagetool with `ARCH=aarch64`.
It refuses to overwrite an existing output image.

For an incremental `--no-bundle` Rust rebuild, copy the new release executable
into AppDir `usr/bin/creamlinux` and retain the application RUNPATH
`$ORIGIN/../lib` before repackaging. Preserve older outputs under distinct names.
Build resources, large runtime packages, original APKs/providers and test
artifacts are ignored workspace outputs rather than tracked binaries.

## Next milestone

Read-only backend/resource integration and the specified native GUI workflows
are validated. No connected-browser blocker remains. Next steps are release
build automation and optional visual/keyboard/clipboard review, preserving
these regression checks and explicit read-only launch modes. Proxy installation
and gameplay remain outside the validation scope.

The full current worktree inventory below includes pre-existing changes and
both implementation phases; it does not attribute every edit to this phase.

## Current worktree inventory

Tracked diff statistics exclude untracked additions.

```text
 .gitignore                                         |   2 +
 package.json                                       |   4 +-
 scripts/package-steam-frame-appimage.sh            |  18 +-
 src-tauri/capabilities/default.json                |   3 +-
 src-tauri/src/lepton.rs                            |  13 +-
 src-tauri/src/main.rs                              |  63 +++-
 src/components/pages/LeptonInspectorView.tsx       | 100 +++++-
 src/styles/components/pages/_lepton_inspector.scss |  44 +++
 src/types/Game.ts                                  |  59 ++++
 tools/android-steam-proxy/FRAME.md                 |   3 +-
 tools/android-steam-proxy/PARITY.md                |   7 +-
 tools/android-steam-proxy/README.md                | 365 ++++++++++++++++++++-
 tools/android-steam-proxy/generate.py              | 148 +++++++--
 tools/android-steam-proxy/tests/abi_test.c         |  18 +-
 tools/android-steam-proxy/tests/run_android.sh     |   5 +-
 tools/android-steam-proxy/tests/scan_consumers.py  |  83 ++++-
 16 files changed, 854 insertions(+), 81 deletions(-)
```

All modified and untracked source/documentation files:

```text
 M .gitignore
 M package.json
 M scripts/package-steam-frame-appimage.sh
 M src-tauri/capabilities/default.json
 M src-tauri/src/lepton.rs
 M src-tauri/src/main.rs
 M src/components/pages/LeptonInspectorView.tsx
 M src/styles/components/pages/_lepton_inspector.scss
 M src/types/Game.ts
 M tools/android-steam-proxy/FRAME.md
 M tools/android-steam-proxy/PARITY.md
 M tools/android-steam-proxy/README.md
 M tools/android-steam-proxy/generate.py
 M tools/android-steam-proxy/tests/abi_test.c
 M tools/android-steam-proxy/tests/run_android.sh
 M tools/android-steam-proxy/tests/scan_consumers.py
?? scripts/prepare-steam-frame-runtime.py
?? scripts/test-frame-inspector-native.py
?? scripts/test-lepton-inspector.mjs
?? src-tauri/src/lepton_compatibility.rs
?? src-tauri/src/lepton_entry.rs
?? src-tauri/tauri.frame.conf.json
?? src/components/pages/LeptonCompatibilityReport.tsx
?? tools/android-steam-proxy/HARDWARE_VALIDATION.md
?? tools/android-steam-proxy/INSPECTOR_INTEGRATION.md
?? tools/android-steam-proxy/JOBSIMULATOR_HARDWARE.md
?? tools/android-steam-proxy/LLVM_RUNTIME.md
?? tools/android-steam-proxy/TARGET_PROXY.md
?? tools/android-steam-proxy/VALIDATION_STATUS.md
?? tools/android-steam-proxy/build_hardware_bundle.py
?? tools/android-steam-proxy/build_llvm_runtime.py
?? tools/android-steam-proxy/compatibility.py
?? tools/android-steam-proxy/evidence/frame-inspector-ui-2026-10-07.json
?? tools/android-steam-proxy/evidence/jobsimulator-frame-2026-10-07.json
?? tools/android-steam-proxy/evidence/multigame-2026-10-07.json
?? tools/android-steam-proxy/generate_target_proxy.py
?? tools/android-steam-proxy/hardware/binding_probe.c
?? tools/android-steam-proxy/hardware/resolve_probe.c
?? tools/android-steam-proxy/hardware/run_hardware_validation.sh
?? tools/android-steam-proxy/hardware/weak_probe.c
?? tools/android-steam-proxy/tests/run_target_abi.py
?? tools/android-steam-proxy/tests/test_compatibility.py
?? tools/android-steam-proxy/tests/test_compatibility_cli.py
?? tools/android-steam-proxy/tests/test_frame_resources.py
?? tools/android-steam-proxy/tests/test_hardware_bundle.py
?? tools/android-steam-proxy/tests/test_llvm_runtime.py
?? tools/android-steam-proxy/tests/test_target_proxy.py
?? tools/android-steam-proxy/tests/test_validation_evidence.py
?? tools/android-steam-proxy/validation_evidence.py
?? tools/android-steam-proxy/verify_target_proxy.py
```
