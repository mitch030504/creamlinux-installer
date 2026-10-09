# Steam Frame inspector release workflow

This workflow builds the ARM64 **read-only Lepton inspector**. It does not install
a generated proxy into a game. Use explicit `--lepton-inspector APPID` or
`--lepton-compatibility APPID` entrypoints. The Frame-only distribution now rejects
default/unknown startup before legacy initialization; other builds retain legacy
behavior. See [STEAM_FRAME_CI.md](STEAM_FRAME_CI.md) for the frozen SDK and CI. Historical next-step text in the proxy research docs is
superseded by this release workflow and `INSPECTOR_INTEGRATION.md`.

Security review and residual dependency risks: [STEAM_FRAME_SECURITY_REVIEW.md](STEAM_FRAME_SECURITY_REVIEW.md).

## Build controller and external dependencies

Use an x86_64 Linux controller with Python 3.11+, Git, Docker access, binutils
(`ar`, `readelf`), `patch`, `zstd`, LLVM (`clang`, `ld.lld`, JSON-capable `llvm-readelf`),
and the Android NDK at `ANDROID_NDK_HOME` (tested `/opt/android-ndk`, r30).
The NDK and host LLVM are required by the complete proxy regression gate, not
by the shipped inspector. Docker must execute ARM64 containers through working
QEMU/binfmt. Install/configure those **on the build controller**, never SteamOS.
CI pins the controller reader to LLVM 20.1.8 and probes actual JSON evidence
before the test gate. Ubuntu's default LLVM 18 is incompatible; use
`scripts/release/prepare-llvm-reader.py` on Ubuntu 24.04 as documented in
[STEAM_FRAME_CI.md](STEAM_FRAME_CI.md#troubleshooting-the-first-hosted-test-failure).
The shipped private ARM64 reader is separate and retains its existing package pins.

**Historical provisioning reference:** prefer the frozen SDK in STEAM_FRAME_CI.md.
Provide an ARM64 Ubuntu 24.04 build container with this live repository mounted
read/write at `/work`. The tested container is
`creamlinux-arm64-lepton-validation`, user `ubuntu` (UID 1000). An example base:

```bash
docker run -d --platform linux/arm64 \
  --name creamlinux-arm64-lepton-validation \
  --mount "type=bind,source=$PWD,target=/work" \
  ubuntu@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3 \
  sleep infinity
docker exec --user root creamlinux-arm64-lepton-validation \
  bash -c 'apt-get update && apt-get install -y build-essential pkg-config curl ca-certificates git python3 binutils patchelf squashfs-tools libgtk-3-dev libwebkit2gtk-4.1-dev libssl-dev librsvg2-dev libsoup-3.0-dev gstreamer1.0-plugins-base gstreamer1.0-plugins-good'
```

Install Node **22.16.0** with npm and Rust **1.96.0**/Cargo for `aarch64-unknown-linux-gnu`
in that container using your trusted build-environment provisioning. Node is on
PATH; Cargo is at the build user's `$HOME/.cargo/bin`. The image's existing
`ubuntu` user must be able to write the mounted checkout. Do not change ownership
of an unrelated checkout. Provision frontend dependencies once inside ARM64:

```bash
docker exec --user ubuntu --workdir /work creamlinux-arm64-lepton-validation npm ci
```

Use `package-lock.json` and `Cargo.lock`. A host-created x86_64 `node_modules`
cannot substitute for ARM64 dependencies. Do not run `npm ci` over dependencies
being used by another build. System packages are external build dependencies:
their complete versions and SHA256 of the inventory are recorded in every
manifest. The base digest alone does not freeze an upgraded container. Reuse
the same provisioned container for bit-identity comparisons; archive the package
inventory and build environment if reproducing that environment elsewhere.

## One high-level command

From the repository root:

```bash
scripts/build-steam-frame-release.sh --prepare-tools
```

`npm run release:frame -- --prepare-tools` is equivalent. The default output is
a new directory under `tools/android-steam-proxy/build/releases/`. A successful
command exits 0 and prints `PASS Frame release`; failures exit 2, identify the
missing dependency/log, and leave a failed manifest when an output directory
has been reserved. They do not publish a successful-looking AppImage.

Check an already provisioned, **running** environment without downloads/builds:

```bash
scripts/build-steam-frame-release.sh --preflight
```

`--preflight` is read-only and incompatible with `--prepare-tools`. A regular
build starts a stopped selected build container and stops it afterward only if
it started it. It does not create or install dependencies into that container.
Missing prerequisites require provisioning before retrying.

## Options and environment

| Option | Environment/default | Purpose |
| --- | --- | --- |
| `--builder-mode` | `FRAME_BUILDER_MODE=development`, CI uses `strict` | Verify frozen SDK identity; deviations are recorded |
| `--capture-root` | `FRAME_CAPTURE_ROOT` | Optional private APPID capture directories; never bundled |
| `--container` | `FRAME_BUILD_CONTAINER=creamlinux-arm64-lepton-validation` | ARM64 build container |
| `--container-user` | `FRAME_CONTAINER_USER=ubuntu` | Build user |
| `--container-workdir` | `FRAME_CONTAINER_WORKDIR=/work` | Repository mount |
| `--tools-dir` | `FRAME_RELEASE_TOOLS_DIR`, default proxy `build/release-tools` | Checksum-pinned packaging cache |
| `--llvm-cache` | `FRAME_LLVM_CACHE`, default proxy `build/llvm-runtime` | Four pinned `.deb` inputs |
| `--output-dir` | `FRAME_RELEASE_OUTPUT` | Fresh output directory; existing paths refused |
| `--artifact-name` | `FRAME_RELEASE_NAME` | Safe basename ending `_aarch64.AppImage` |
| `--source-date-epoch` | `SOURCE_DATE_EPOCH`, otherwise HEAD commit time | AppDir/SquashFS timestamps |
| `--prepare-tools` | Off | Fetch missing pinned inputs at build time |
| `--smoke` | Off | Test exact new AppImage on Frame |
| `--ssh-target` | `FRAME_SSH_TARGET` | Optional Frame SSH user/host |
| `--ssh-control` | `FRAME_SSH_CONTROL` | Existing authenticated SSH control socket |
| `--smoke-fixtures` | `FRAME_SMOKE_FIXTURES`, default previous validation archive | Generated proxy/bundle/log evidence, never original games |

Version comes from matching `package.json`, `Cargo.toml`, and `tauri.conf.json`;
use `npm run set-version` to change the source version. Naming does not change
the compiled version. `ANDROID_NDK_HOME`/`ANDROID_NDK_ROOT` selects host test NDK.
QEMU is the controller's configured binfmt interpreter, not a hardcoded path.
The pipeline selects pinned linuxdeploy/appimagetool bytes from the tools cache;
arbitrary packaging tool overrides are deliberately rejected. The lower-level
`package-steam-frame-appimage.sh` accepts `APPIMAGETOOL` and
`FRAME_APPIMAGE_RUNTIME` only when their hashes match those pins.

## Automated stages and packaging workaround

1. Fail-closed preflight, matching source versions, tool checks and optional SSH
   prerequisites. Capture branch, HEAD, dirty status and source file hashes.
2. Prepare the private LLVM runtime, preserving package/payload hashes and licenses.
3. Complete Python, Rust/Tauri, rendering and whitespace gates. Required skipped
   tests fail; missing optional local game captures are explicitly reported.
4. `tauri build --ci --no-bundle --features custom-protocol,frame-inspector-only -- --locked` builds the frontend and ARM64 binary
   with `tauri.frame.conf.json`. The feature explicitly embeds production assets;
   no-bundle CLI behavior must not leave the app in development mode. No expected Tauri AppImage failure is swallowed.
5. Construct a fresh minimal AppDir, explicitly stage matching ARM64 WebKit
   Network/Web processes and injected bundle (normally staged by Tauri), and run ARM64 linuxdeploy with GTK and
   GStreamer, `APPIMAGE_EXTRACT_AND_RUN=1`, `DEPLOY_GTK_VERSION=3`. ARM64 tool
   AppImages are extracted with `unsquashfs` before executing their ordinary
   ELF binaries: common binfmt rules reject AppImage’s extra `AI` header marker.
   Final-image validation uses the same checked type-2 SquashFS boundary.
   No privileged binfmt rule modification is required.
6. Apply the checksum-verified Tauri GTK workaround from `gtk-tauri.patch`,
   including WebKit resource relocation. A private tooling directory excludes
   the cached `linuxdeploy-plugin-appimage` that broke emulated bundling.
7. Restore LLVM bytes after linuxdeploy's RPATH edits, remove display conflicts,
   normalize timestamps and package on x86_64 with `ARCH=aarch64`, a pinned
   ARM64 runtime and single-worker SquashFS compression.
8. Validate every ELF's architecture, resources, checksum integrity, exclusions,
   launch wrapper, all three WebKit helpers, extraction parity and the compiled resolved Tauri close ACL, inspector-only startup, denied updater and enabled Frame CSP.
9. Rerun available six-game captures with **this AppImage's** private ARM64 reader.
10. Optionally measure exact-artifact Frame GUI/backend behavior. Verify source
    inputs stayed fixed, then output artifact, checksums and final manifest.

`scripts/release/tools.json` pins every downloaded packaging binary/plugin.
Downloads occur only at build time with `--prepare-tools`; corrupt caches fail
without silent replacement. AppRun upstream currently offers a moving
`continuous` URL: its exact hash is pinned, so a changed asset fails closed.
Preserve the verified build cache or supply those exact bytes if that URL moves.
Other build assets use explicit releases/commits. The AppImage runtime is passed
explicitly; appimagetool's default moving runtime download is never used.

The outer AppRun sets `WEBKIT_DISABLE_DMABUF_RENDERER=${WEBKIT_DISABLE_DMABUF_RENDERER:-1}`
before the existing linuxdeploy plugin hooks/native launcher. An explicit
nonempty override is preserved. GTK deployment retains its validated X11 hook.
The ten excluded families (including version variants and nested plugins) are:

```text
libwayland-client.so.0  libwayland-cursor.so.0  libwayland-egl.so.1
libwayland-server.so.0  libxkbcommon.so.0       libxcb-randr.so.0
libxcb-render.so.0      libxcb-shm.so.0        libXau.so.6  libXdmcp.so.6
```

The helper removes them; the final AppDir and extracted AppImage independently
reject any remaining matching files. Host display libraries supply these APIs.
The release is not a universal Linux build.

## Immutable-host LLVM reader

See [LLVM_RUNTIME.md](tools/android-steam-proxy/LLVM_RUNTIME.md). LLVM 20.1.8 and
its pinned ARM64 dependencies are packaged privately at
`usr/lib/Creamlinux/compatibility/runtime`; all four copyright files, manifest
and ten payload checksums are included. No SteamOS package installation, host
`llvm-readelf` requirement, runtime binary download, or new ELF parser is used.
The reader subprocess isolates its library path and clears preload settings.
Remaining SteamOS host dependencies and supported glibc baseline are documented
there; exact Frame smoke exercises the shipped reader through real analysis.

## Outputs, traceability and determinism

The output contains AppImage, `SHA256SUMS`, `release-manifest.json`,
`source-inputs.json`, `build-packages.tsv`, `appdir-inventory.json`, test summaries,
six-game reports when available, complete build logs and optional `frame-smoke/`.
The manifest records filename/hash/size/version/architecture, branch/HEAD/dirty
snapshot, timestamp/epoch, controller/tool versions, package inventory identity,
LLVM identity, static checks, tests and exact-artifact hardware evidence.

The earlier `cb5f6616...` artifact is a behavioral reference only. A new build
does **not** inherit its hardware-tested status. `performed_this_build=false`
means this exact artifact was not measured. Historical Job function-proxy
evidence remains distinct from AppImage smoke and fixed-proxy compatibility.

Compare two builds with identical source files, lockfiles, epoch, tool pins,
container/package inventory and runtime inputs, using different fresh output
directories. AppDir inventories omit timestamps but preserve file hashes/modes
and symlink targets. Build reports intentionally contain current timestamps,
durations, staging paths and newly measured evidence, so their full JSON hashes
are not expected to match. The source must not change during a build. Release
documentation updated after a measured build has a different source snapshot;
the manifest, rather than current HEAD alone, identifies the built inputs.

## Optional exact-artifact Frame smoke

Use already authenticated noninteractive SSH (for example a persistent control
socket). The Frame needs Python GI/AT-SPI as used by the existing native test
harness, an active desktop session and an **already running** Job Simulator
context. The pipeline probes `lepton exec steamlaunch-448280 true`; it never
starts a production context. It refuses an occupied isolated smoke directory.

```bash
scripts/build-steam-frame-release.sh --prepare-tools --smoke \
  --ssh-target steamos@FRAME_IP --ssh-control "$HOME/.ssh/creamlinux-frame-control" \
  --output-dir tools/android-steam-proxy/build/releases/frame-smoke-new
```

The established evidence archive contains generated proxy artifacts and prior
Bionic mock/resolution logs, not providers/APKs. It is an optional external test
fixture; a source-only build without it still works with `--smoke` omitted.
The pipeline transfers and hashes the exact AppImage under the Linux host's
`/tmp/creamlinux-inspector-validation`, uses read-only entrypoints, runs native
GTK actions/dialogs/window close, checks the shipped reader and Job semantics,
and cleans only its token-owned directory. Walkabout, if stopped, must return
operational exit 2; its captured regression still checks compatible exit 0.
No game injection, library replacement or Android proxy experiment occurs.

## Tests and troubleshooting

Fast release guards are part of the normal Python suite; they need no full build:

```bash
python3 -m unittest discover -s tools/android-steam-proxy/tests -p 'test_*.py'
```

The release also runs `cargo test --locked`, `npm run test:lepton-ui`,
`git diff --check` and packaged ACL/capture checks. `--lepton-release-info` is a
headless read-only check of the compiled ACL/version, without legacy startup.
No test count is hardcoded as a substitute for current execution.

For failures, inspect the named stage log and failed manifest. Restore the exact
pinned input for checksum errors. Provision missing tools before retrying.
Occupied outputs are never overwritten; select a fresh directory. Investigate
excluded libraries or architecture failures rather than disabling a guard.
LLVM payload changes after linuxdeploy must be restored and hash-verified.
Source drift requires another build from stable source. SSH authentication or
desktop/context prerequisites require operator intervention; no hidden password
prompt is allowed. Native GUI checks require the established desktop test
environment; backend-only checks do not prove dialog behavior.

## Intentional limits

The compatibility workflow remains read-only. Target proxies omit unrequired
non-functions and are test artifacts, not supported installation actions.
Walkabout fixed compatibility wording remains “Compatible for observed static
consumers”; Job fixed compatibility remains false/exit 1. No real split APK
installation was available; synthetic split tests pass and future hardware
evidence remains optional. No release upload/signing/update publication occurs.

Measured end-to-end release results are recorded in the final release handoff
and generated manifests; see those for exact hashes/counts and repeated-build
comparison rather than treating historical measurements as current evidence.
