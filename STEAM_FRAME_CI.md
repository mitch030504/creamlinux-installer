# Steam Frame CI, frozen SDK and distribution preparation

This supersedes the ad-hoc container provisioning in the original release
handoff. The canonical packaging implementation remains
`scripts/build-steam-frame-release.sh`; YAML never implements packaging.
Nothing here publishes a release, pushes an image, or uses a production key.

## Existing CI audit

Only `build.yml` and `test-build.yml` existed. They are legacy x86_64 workflows,
not Frame builds. `build.yml` mutates/commits/pushes package.nix, creates a draft
release, checks out main separately, signs with production secrets, uploads
assets and publishes. Both use moving Node/Rust/action references, unsigned
continuous appimagetool downloads, and remove the entire GTK/WebKit/GLib closure.
Even test-build exposes production signing secrets. Neither uses the private
ARM64 LLVM reader, locked source snapshot, Frame manifest, six-game capture
report, architecture checks or ten-library guard. The security review now removes production secrets from Test Build, pins its
and the legacy release actions/toolchains/appimagetool, updates obsolete GitHub
script actions, and restricts legacy publication to main. The legacy main-only
workflow still mutates package.nix and publishes with existing production secrets;
do not invoke it to validate or distribute the Frame inspector.

## Frozen SDK

`docker/steam-frame-release/Dockerfile` pins the approved ARM64 Ubuntu base
manifest by digest. `sdk-lock.json` pins Node 22.16.0/npm 10.9.9, Rust/Cargo 1.96.0,
toolchain archive SHA256s and the complete 1,083-package apt inventory. Packages
are requested by exact version from Ubuntu's signed `20260927T020000Z` snapshot.
The final inventory must equal `packages.tsv` byte for byte. This intentionally
preserves the proven SDK, including packages beyond the minimum needed.

Ubuntu snapshots are retained externally, not a hermetic archive owned by this
project. Historical index expiry is disabled only for the immutable snapshot;
Ubuntu archive signature authentication remains required. The minimal base
contains no CA bundle: only the CA bootstrap apt transaction disables HTTPS
peer verification, while authenticating indexes/packages with Ubuntu archive
signatures. Subsequent downloads verify TLS and SHA256 normally. Toolchain
archive installation needs no moving rustup installer. The Node archive's original
npm 10.9.2 embeds vulnerable tar 6.2.1; provision.py replaces it with the SHA256-pinned
npm 10.9.9 archive using Python extraction before any npm execution. Its tar is
7.5.22 and license notices survive. CI Node jobs likewise use
scripts/release/prepare-npm.py to prepare that archive in a fresh RUNNER_TEMP
prefix, add its bin directory to GITHUB_PATH, and fail on preparation error.
No global npm installation or vulnerable bootstrap extractor is used. No SteamOS changes occur.

Build on an x86_64 Docker controller with ARM64 binfmt already provisioned:

```bash
python3 scripts/frame_sdk.py
docker run -d --platform linux/arm64 --dns 1.1.1.1 \
  --name creamlinux-frame-frozen --mount "type=bind,source=$PWD,target=/work" \
  creamlinux-frame-sdk:locked
docker exec --user ubuntu --workdir /work creamlinux-frame-frozen npm ci
scripts/build-steam-frame-release.sh --prepare-tools --builder-mode strict \
  --container creamlinux-frame-frozen --output-dir tools/android-steam-proxy/build/releases/frozen-first
```

The DNS override is optional and only affects this container. The default UID
1000 matches the proven local checkout; do not change another checkout's owner.
CI instead runs with the checkout owner's numeric UID/GID and a private HOME.
Controller prerequisites/NDK remain documented in STEAM_FRAME_RELEASE.md.
`scripts/release/controller.json` pins the actual r30 test NDK archive SHA256,
size and version; `prepare-controller.py CACHE` verifies and transactionally
extracts it, preserves Unix symlinks and executable modes, and rechecks cached
file contents against the pinned archive. A fresh controller extraction is tested
with the actual API-21 ARM64 compiler. Ordinary ZIP extraction loses compiler
symlinks and must not replace this implementation.

The same lock pins a **separate x86_64 LLVM 20.1.8 controller reader** from
apt.llvm.org's Noble packages. `prepare-llvm-reader.py` verifies exact package
sizes and SHA256s, reuses `build_llvm_runtime.py`'s selected-member extractor and
private-library launcher, and retains both package copyright files. Only
`llvm-readobj` and `libLLVM.so.20.1` are selected; no LLVM package is installed.
Ubuntu 24.04 provides libedit2, libtinfo6, libxml2 and their runtime dependencies.
This controller bundle is not the ARM64 runtime shipped in the AppImage, whose
pins remain unchanged. Both package sets use `data.tar.zst`: the shared extractor
decodes verified bytes with the controller's `zstd` before selecting tar members,
so it works with hosted Python 3.12 as well as newer Python versions.

Strict mode executes only the approved /opt Node/Rust paths without home-bin
wrappers or login startup files, rejects compiler/Node/loader/shell override
variables, and records development override names without values. Malformed
artifact metadata fails with exit 2 and no traceback. Manual GitHub workflows
must first exist on the default branch before branch-ref dispatch is possible;
this requires separate maintainer authorization.

Strict mode checks root-filesystem drift outside user/runtime caches both before
and after the build, the SDK source label, embedded definition hash, full installed
package inventory and Node/npm/Rust/Cargo versions. A manifest records immutable
local Docker image ID, base digest, definition hash, inventory hash and tool
pins. No SDK has been published to an OCI registry; there is consequently no published
registry identity for the assembled SDK yet; the local OCI digest is recorded. Each CI run builds the approved
recipe locally and records its exact image ID. Approval covers this recipe and
inventory, not an arbitrary image tag. The verification assumes a trusted Docker
controller and is not remote image attestation. Development mode is explicit in
manifests and records every deviation; official CI uses strict mode.

To refresh: review snapshot/package/tool pins, build a new SDK, validate inventory
and release tests, run two release builds and exact-artifact Frame smoke where
available. Never edit a checksum merely to silence drift. Record new evidence.

## Workflow architecture and runner decision

- `steam-frame-tests.yml`: PR path-filtered Python, Rust and rendering tests;
  no full AppImage packaging and no signing secrets.
- `steam-frame-release.yml`: manual, non-publishing validation using a freshly
  built SDK and fresh container; optional second complete build. Uploads only
  allowlisted artifact/reports/logs for 14 days.
- `steam-frame-signing-preparation.yml`: separate manual ephemeral-key rehearsal,
  consuming a successful manual validation run from the exact same source
  commit. It rejects PR producers and wrong workflows before download, validates
  artifact/provenance again, and never reads production signing variables.

The release workflow now separates compilation from the x86_64 controller:
`ubuntu-24.04-arm` compiles and runs Rust/rendering tests natively inside the
unchanged frozen ARM64 SDK. It invokes the canonical release script with
`--compile-only`, prepares the existing pinned ARM64 LLVM reader, builds the
production frontend and exports the binary plus checksummed test logs and a
compilation manifest. No binfmt privilege is needed in this job.
The dependent `ubuntu-24.04` job retains the pinned x86_64 NDK, reader and
appimagetool. It invokes the same script with `--compiled-input`, runs the full
Python gate, validates native test evidence and assembles/validates the AppImage
in the frozen ARM64 SDK under QEMU. Privilege remains confined to the existing
immutable binfmt provisioning step, never release scripts. Cross-compilation
was not selected: it would add a new linker/sysroot/toolchain trust boundary.

Download is restricted to this workflow run's named immutable compilation
artifact. Before consumption, the script checks source HEAD/snapshot, version,
epoch, Cargo environment/jobs, private reader identity, all payload checksums,
AArch64 ELF, approved SDK definition/inventory/tool versions, clean SDK rootfs,
nonempty passing Rust/rendering gates and zero ignored/skipped cases. In CI,
repository/run ID/commit must match too. The final manifest and unsigned
provenance retain the native producer, test evidence and both SDK identities.
Compilation success is explicitly `native_compilation_only`, not an AppImage or
hardware-validation claim. The six-game/private-capture policy is unchanged.
CI disables test/dev debug information and incremental compilation to reduce
disk use; these settings are forwarded and recorded, without skipping tests or
changing release optimization. The manual runner choice also offers `steam-frame-release-x64`, which requires
an explicitly provisioned isolated self-hosted runner with that label.
Hosted disk/runtime limits may require a provisioned x86_64 self-hosted runner
with ample free disk (recommend 30 GB) and Docker. No such runner is assumed to
exist. The assembled SDK is deliberately large; no unrelated host caches are
silently deleted to make room. Fresh-container local integration is the acceptance
proof. The first hosted PR run exposed controller-reader and test-environment
issues described below; a successful hosted rerun is still required.

All new action references use actual resolved commit SHAs with version comments.
No pull_request_target, release publication, signing secret, mutable action ref,
write-scoped contents token, or shared build cache is introduced. Build and test
jobs receive contents:read only. Signing rehearsal receives actions:read solely
to retrieve a selected run; downloaded artifact contents are never executed.
The build executes source with Docker access on an ephemeral runner; do not give
these jobs a persistent sensitive self-hosted machine or signing credentials.

## Troubleshooting the first hosted test failure

[Run 37818104779](https://github.com/mitch030504/creamlinux-installer/actions/runs/37818104779)
executed 285 Python tests with 60 failures, 39 errors and two skips. The Ubuntu
`llvm` metapackage selected LLVM 18, whose JSON representation does not satisfy
the analyzer: a real AArch64 shared library produces malformed JSON with the
scanner's combined options, and the sectionless protocol probe lacks
`DynamicSection`. Exit 0 from the reader alone does not establish compatibility.
Rendering and Rust steps were not reached. GNU readelf is not a substitute.

Both Frame workflows now prepare the checksum-pinned x86_64 reader into a fresh
RUNNER_TEMP prefix, then append its **bin directory to GITHUB_PATH**. This
prepends it to subsequent steps' PATH, covering `shutil.which('llvm-readelf')`,
literal command names and analyzer CLI subprocesses. An environment override
alone would miss tests that discover or invoke the reader directly. Existing
explicit-missing-reader and invalid-reader tests still exercise real failures;
there is no fallback that turns those failures into successful inspection.

Preparation probes the selected executable before publishing the prefix. A
separate preflight step then checks the **actual PATH executable** before the
Python suite: exact LLVM 20.1.8 version, real compiler-produced AArch64 provider
exports (GLOBAL/WEAK/functions/object/SONAME) and consumer evidence
(DT_NEEDED/imports/Android packed relocations) using the existing scanner. A
version mismatch, malformed/missing JSON fields, absent host library/compiler,
checksum mismatch or failed evidence probe stops the workflow. Neither fixture
is executed or loaded; no Steam API functions are called.

For a Ubuntu 24.04 controller, the equivalent diagnostic preparation is:

```bash
# Requires clang, lld, binutils, zstd, libedit2, libtinfo6 and libxml2.
llvm_bin="$(python3 scripts/release/prepare-llvm-reader.py /tmp/frame-llvm-reader \
  --cache /tmp/frame-llvm-packages)"
export PATH="$llvm_bin:$PATH"
python3 scripts/release/prepare-llvm-reader.py --preflight-only
python3 -m unittest discover -s tools/android-steam-proxy/tests -p 'test_*.py'
```

Choose a fresh output directory; existing output is refused. Downloads are
HTTPS plus locked size/SHA256, not a moving package install. Preparation failures
return exit 2 on stderr without a traceback or a successful-looking prefix.
Keep NDK/reader shell assignments separate from `echo`, so preparation errors
propagate instead of being masked by a successful echo command.

The same failed run also exposed synthetic artifact tests inheriting
`GITHUB_ACTIONS=true`/`GITHUB_SHA`. Their fixture source is intentionally not the
workflow commit. Only those unit fixtures now isolate the inherited flag; tests
explicitly opt into hosted behavior to verify matching commit/snapshot acceptance
and wrong commit/checkout rejection. The production provenance guards are unchanged.

Local validation in a fresh **x86_64 Ubuntu 24.04 / Python 3.12** container with
the prepared reader and hosted-style environment ran 326 tests: 326 passed,
zero failures/errors/skips with the two private captures available. The second
run without captures ran 326 tests: **324 passed, two `local capture unavailable`
skips, zero failures/errors**; those proprietary captures are not uploaded or
provisioned in CI. Pinned ARM64 SDK validation passed 8 rendering tests, the
frontend production build and 53 Rust tests in each of the Frame/default feature
modes. Actionlint 1.7.7 across all five workflows and whitespace checks passed.
Fresh-download and cached x86_64 reader payload hashes match, and building the
ARM64 runtime under Python 3.12 retains its previously validated manifest/hashes.
These local results do not claim a successful hosted rerun.

## Release timeout and resource diagnostics

[Release run 37889969234](https://github.com/mitch030504/creamlinux-installer/actions/runs/37889969234)
passed Python/Rust/rendering and the frozen SDK checks. The test stage took
1,770 seconds under QEMU; release compilation was then killed by the old blanket
1,800-second command timeout while still compiling dependencies around `ring`.
No compiler error was demonstrated, and old logs lacked memory/CPU samples.
Increasing that single timeout would retain the slow emulated compiler. Native
compilation preserves the same ARM64 SDK and ABI without adding a cross linker.

The canonical script has configurable tool/test/build/package budgets (defaults
600/3600/7200/1800 seconds), validated to 1..21600. Heartbeats default to 60
seconds and Cargo uses two build jobs by default. Native CI has a 240-minute job
budget; packaging retains 180 minutes with shorter 900-second test and
1800-second import budgets. SDK construction has its own configurable
`frame_sdk.py --timeout` (1800 seconds by default). See release options below.
Logs preserve compiler output, stage/command elapsed time, CPU/load/process
state, RAM/swap, cgroup OOM counters and free/used disk. Process command lines
and environment values are not logged. Diagnostics go to stderr and remain
separate from captured JSON stdout. A synthetic slow JSON subprocess regression
guards this separation; an early local capture run exposed the issue before CI.

Each command has an owned process group. Container commands also have an
internal deadline and private PID/start-time record; controller cancellation
can terminate that exact group without killing unrelated container processes.
Timeouts send TERM then KILL, reap the owned child, retain partial logs and
record termination state. Failed stages record their elapsed time and reason.
No required test, checksum, source lock, display-library exclusion, production
asset/ACL check or hardware-evidence boundary is disabled by this architecture.
Optional reproducibility rebuilds packaging from the same verified compilation
input; independent cold compiler reproducibility needs comparison across runs.

## Provenance, captures and hardware

`provenance.json` is an unsigned in-toto statement containing source commit,
dirty state/snapshot hash, workflow/run identity, runner OS/architecture, exact
builder identity, package inventory, tool pins, LLVM runtime identity, epoch,
artifact hash, AppDir inventory hash, tests, capture status and hardware smoke.
No SLSA compliance level or signed provenance is claimed. `frame_ci.py verify`
checks manifest/artifact/checksums/source/provenance consistency, frozen builder,
test gates, static packaging and exact-artifact hardware identity. `export`
allowlists payloads; arbitrary files, APKs/providers, caches and keys are excluded.
The artifact is not authenticated merely by accompanying unsigned hashes. CI
also checks the source inventory against the exact checkout and independently
checks the builder definition/inventory against the approved lock. GitHub artifact
downloads lose executable permission; restore it with chmod +x before launching.

GitHub's pinned attest-build-provenance action was inspected, including its
subject-checksums input and transitive action pins. Attestation is deliberately
not enabled here: it writes repository attestations and requires OIDC/attestation
write permissions. A separately authorized attestation job can later consume
verified artifacts without executing them. Current workflows need neither token
permission and cannot imply that a local unsigned record is a signed attestation.

Synthetic fixtures run unconditionally. Optional securely provisioned original
captures may be supplied with `FRAME_CAPTURE_ROOT=/private/captures`, containing
APPID directories with libsteam_api.so and base.apk (or apks/base.apk). No original
capture is bundled/uploaded. `captured_game_regressions` records performed,
unavailable or failed, with passed/unavailable counts; individual rows preserve
partial availability. Missing private captures never become six fabricated passes.
CI does not attach a Frame. Exact-artifact smoke is not performed or inherited;
historical Bionic proxy evidence stays separate. Local `--smoke` records the exact
new artifact hash when actually measured.

```bash
python3 scripts/frame_ci.py verify RELEASE_DIRECTORY
python3 scripts/frame_ci.py compare FIRST_RELEASE SECOND_RELEASE
python3 scripts/frame_ci.py export RELEASE_DIRECTORY FRESH_UPLOAD_DIRECTORY
```

Comparison requires identical source, SDK identity, epoch, AppImage bytes and
AppDir inventory. JSON timestamps/durations/run IDs intentionally vary.

The dependency security review separately inventories all 32 initial npm package
findings / 71 unique GHSAs. Compatible lock updates fix 18 package findings / 59
initial GHSAs, including critical tar; 14 entries / 13 GHSAs remain (12 original and one newly exposed bundled advisory), without hiding
or ignoring audit output. Rust's two vulnerability findings are remediated; seven
maintenance/soundness warnings remain. The patched SDK npm has additional bundled
findings recorded separately. See STEAM_FRAME_SECURITY_REVIEW.md before protected
production signing/distribution; successful packaging is not a clean security audit.

## Signing and updater preparation

Tauri's locked updater uses Minisign Ed25519 signatures with a base64-encoded
signature envelope. Its source searches `{os}-{arch}-{installer}` first, then
`{os}-{arch}`. The ARM64 AppImage keys are therefore `linux-aarch64-appimage` and
`linux-aarch64`; existing x86_64 keys remain untouched. Prepared metadata is a
separate `inspector-latest.prepared.json`, not the legacy latest.json endpoint.
Do not merge this channel into the legacy updater without explicit approval.

`frame_signing.py` accepts no private-key argument and refuses inherited Tauri
signing variables. It generates a disposable key in a mode-0700 temporary
directory, captures all potentially secret-bearing signer output, signs a copy
of the verified AppImage, verifies it using pinned minisign-verify 0.2.5, and
rejects tampering. Only public key/signature/metadata/report survive. Private keys
are deleted on success or error and never included in artifacts/handoffs.

```bash
python3 scripts/frame_signing.py RELEASE_DIRECTORY FRESH_SIGNING_OUTPUT \
  --container creamlinux-frame-frozen \
  --url https://example.invalid/steam-frame-inspector.AppImage
```

Production signing/publication remains intentionally absent. A future publication
job must use an operator-approved artifact hash/provenance, protected environment,
separate inspector key/channel, and secrets available only in the isolated signing
job. No untrusted producer/PR code may execute with that key. Authorization to
publish or use a production key is required separately.

## Read-only distribution boundary

The Frame recipe now compiles `frame-inspector-only` and uses identifier
`com.creamlinux.steam-frame-inspector`. Default/unknown startup fails with clear
CLI instructions before legacy initialization, even when invoking the embedded
ELF directly. AppRun also accepts only the three read-only modes. The Frame
binary does not register the legacy updater plugin. Its separate capability
allows core window operations, close and read-only file selection; it omits
updater/process and webview-creation permissions. Other builds retain legacy
startup/updater behavior. The desktop file is intentionally NoDisplay: this is
an explicitly launched CLI/inspector distribution, not a legacy installer menu
entry. Launch `AppImage --lepton-inspector APPID`; argumentless execution exits 2
safely. A friendly read-only game-selection launcher can be a later milestone.
No installation/unlocker actions are exposed by the inspector dispatcher. Frame
configuration now enables a local-content CSP: scripts/assets are local, IPC is
explicitly permitted, arbitrary remote connections, objects and child frames are
blocked. Inline styles remain for React styling. Resolved packaged release-info
must report CSP enabled, inspector-only identity and updater denied. Legacy CSP
and installer functionality are unchanged.
