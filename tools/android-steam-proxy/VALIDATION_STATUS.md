# Steam Frame compatibility validation — 2026-10-07

This records the completed CLI/hardware phase. The subsequently authorized
read-only inspector and ARM64 AppImage phase is documented in
[INSPECTOR_INTEGRATION.md](INSPECTOR_INTEGRATION.md), including updated test
counts and a current full worktree inventory. Statements below about work not
performed and the next milestone refer to the earlier phase.

Job Simulator's exact target-specific **function forwarding harness completed
real Steam Frame/Bionic validation**. Six real games have read-only CLI results;
four additional captures also match native Frame-host analysis exactly.
The CLI distinguishes fixed-proxy compatibility, generated function artifacts,
static validation and explicit hash-scoped hardware evidence. The ARM64 LLVM
runtime approach has native Frame proof. The next meaningful milestone is
read-only inspector/backend and runtime-resource/AppImage integration.

No commits, pushes, GUI changes, AppImage builds, package installs, production
file changes or production process injections were performed. Existing worktree
changes were preserved. All Android tests remained in `creamlinux-poc` under
`/data/local/tmp/creamlinux-target-proxy/`. Only that development context was
started/stopped. Collected artifacts remain on the workstation; temporary Frame
test files and the temporary Linux-host reader directory were removed. Job
Simulator's production context still passed `lepton exec steamlaunch-448280 true`
after development-context shutdown.

## Exact verification results

- Full Python suite: **194 tests passed, zero skips**, final run 13.475 seconds.
- Before resumed deployment: **153 tests passed**; intermediate suites passed
  **176**, **182**, **192**, and **193** tests as regressions were added.
- `git diff --check` and hardware-runner shell syntax: **passed**.
- Two final Job Simulator builds in different output directories: proxy bytes
  and complete manifests **identical**.
- Walkabout target generation/parity: **1045/1045**, zero WEAK, zero binding or
  visibility mismatches, all static checks passed.
- Existing fixed/reference and mock source generation: names/maps/headers/stubs
  **byte-identical** to the legacy generated outputs.
- Existing legacy static mock: **11047 ABI assertions passed**; uninitialized
  slot process exited **127**. It was rerun, not rebuilt.
- Explicit artifact CLI results: Walkabout exit **0**, Job Simulator exit **1**.
- Four additional generated proxies: **1146/1146**, **1125 GLOBAL / 21 WEAK**,
  exact static parity, repeated artifact CLI JSON identical; exit **1**.

An intermediate suite failed because the new `provider_sha256` success field
was absent from the incomplete-result schema. Adding its null default restored
consistent JSON keys across every result; no assertion was relaxed. An initial
additional-game generation attempt correctly rejected output beneath the
provider capture directory. Outputs were moved to separate build directories,
preserving that safety check.

## Actual Android/Bionic hardware results

Device: Steam Frame. Lepton v2.8.14, rootfs v2.8.11. Dedicated context:
`creamlinux-poc`. Android 11 / API 30 / arm64-v8a. Kernel:
`6.18.0-ge66bc2ca6f8c`. Final observation: `2026-10-07T11:23:09.607313+00:00`.
The Android proxy/test toolchain was the installed NDK r30 Android clang 21.0.0
build `16134705`; generated proxy API is 21.

| Stage / criterion | Measured result |
| --- | --- |
| Dynamic mock target forwarding | 1156/1156 targets |
| ABI assertions | 11156/11156 |
| Fail-closed loader cases | 8/8; each exit 127 with expected diagnostic |
| Final binding / visibility check | 1135 GLOBAL / 21 WEAK; exact |
| Bionic interposition/load-scope fixtures | 4/4; 420 checks |
| Copied real provider symbol resolution | 1156/1156; zero failures |
| Steam API calls made by resolution probe | 0 |
| Individual mock/weak/resolve stages | all exit 0 |
| Subsequent combined all replay | exit 0, reproduces individual results |
| Production game files changed / processes injected | 0 / 0 |

The original prepared bundle passed, followed by another complete hardware run
for the reproducible-path proxy. No forwarding/loader implementation failure
was discovered on the Frame. These results validate the function-only controlled
mock harness and zero-call real-provider resolution, not real Steam calls,
initialization, gameplay or omitted object ABI. `dlopen` executes ELF constructors;
the probe's zero Steam API call count is not zero code execution.

Final precise identities:

| Artifact | SHA256 |
| --- | --- |
| Job Simulator provider | `345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700` |
| Final target proxy | `d14dbef4969e32e90564cc15af6b76cc951062629fb415cc2b211d8776eac0e7` |
| Final hardware bundle | `fc8614af167df51b85ec61fe88002845d9a24be11686b65a59543a111e58b3ed` |
| Collected results archive | `490533c053377003e0c94e7824660be0a9af72e37edc659d0eb0cbf6db370be6` |

Complete final logs, 1156 per-target resolution records and observed stage exits
are under `build/frame-hardware-reproducible-2026-10-07/`. The compact verified
summary is [evidence/jobsimulator-frame-2026-10-07.json](evidence/jobsimulator-frame-2026-10-07.json).
Initial-run logs remain under `build/frame-hardware-results-2026-10-07/`.
Real providers/APKs are not added to tracked artifacts.

Initial SSH authentication was blocked, then resolved by the user's shared
control connection. Direct SSH `lepton start` hit Lepton's process-group setup;
launching Lepton as a child shell resolved it. Only the dedicated context was
affected. This external launcher behavior needed no proxy code change.

## Six-game CLI validation

AppIDs, original APK paths and package identities were discovered from actual
Steam manifests/APK badging. Listed context candidates were individually checked
with `lepton exec CONTEXT true`; `lepton ps` was never running-state authority.
Only Job Simulator was running. Other APKs were inspected read-only on the host;
no production context was started. Into Black had no listed context, so no
context identity was guessed for it.

| Game / AppID | Public / functions / non-functions | Fixed covered / uncovered / absent | Consumers / direct / strong runtime | Fixed proxy / exit |
| --- | --- | --- | --- | --- |
| Walkabout Mini Golf / 1408230 | 1049 / 1045 / 4 | 1045 / 0 / 0 | 14 / 0 / 1 | true / 0 |
| Job Simulator / 448280 | 1365 / 1156 / 209 | 1036 / 120 / 9 | 19 / 0 / 1 | false / 1 |
| VRChat / 438100 | 1355 / 1146 / 209 | 1043 / 103 / 2 | 39 / 0 / 1 | false / 1 |
| VAIL / 801550 | 1355 / 1146 / 209 | 1043 / 103 / 2 | 37 / 1 / 1 | false / 1 |
| Into Black / 3606610 | 1355 / 1146 / 209 | 1043 / 103 / 2 | 15 / 0 / 1 | false / 1 |
| Dungeons of Eternity / 3189340 | 1355 / 1146 / 209 | 1043 / 103 / 2 | 21 / 0 / 1 | false / 1 |

All captured native game libraries use arm64-v8a. Required unsupported exports
remain empty for every game. VAIL's `libUnreal.so` directly needs `libsteam_api.so`
and imports **16** Steam-named functions; it also has runtime-resolution evidence.
The other additional games expose runtime lookup evidence. No exact string is
promoted to proof of a particular dlsym/PInvoke call. No false C++ provider
attribution or silent weak-to-global promotion was reintroduced.

| Game | Android package | Provider SHA256 |
| --- | --- | --- |
| Walkabout | `com.MightyCoconut.WalkaboutMiniGolf` | `f424277c8a431542b93bf71215615fa6730edb7968a03f5230d484437f0d4aa4` |
| Job Simulator | `com.owlchemylabs.jobsimulator` | `345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700` |
| VRChat / VAIL | `com.vrchat.android` / `com.AEXLAB.VAIL` | `de0ffad291557797b30e1abd153481cca46225720410f8c8f8709811f9029bb1` |
| Into Black / Dungeons | `com.thebinarymill.intoblack` / `com.othergate.doe` | `ee573a79ad0bf0fa4e6530fa35a4e2911e9f473141a7580b83a3d79fd1679646` |

Job Simulator reports `generation_status=hardware_validated` only with explicit
matching artifact/bundle/log inputs. Walkabout and the other four generated
function surfaces report `locally_validated` (static parity) and hardware
`not_run`. Without explicit artifacts, all report `not_generated`. The legacy
`validated` boolean remains false because actual game behavior is unvalidated.
Walkabout's current fixed proxy preserves **Compatible for observed static consumers**.
Job Simulator's fixed proxy remains false / exit 1 regardless of target success.

Additional capture hashes, native consumer evidence, generation manifests,
parity reports and deterministic JSON are retained in
`build/frame-game-discovery-2026-10-07/`. A compact summary is
[evidence/multigame-2026-10-07.json](evidence/multigame-2026-10-07.json).

## Split APK / variation coverage

No real split installation was found in the accessible original-game APK
inventory or baked APK filename search. Running Job Simulator returned one
`pm path` entry and `splits=[base]`. Stopped contexts could not be queried with
`pm path` and were not started. Therefore real split-installation validation
remains unmeasured; existing synthetic all-path/split/duplicate/archive/ABI
regressions pass. No hardware-discovered split behavior was fabricated.

Observed diversity includes the 1045/1146/1156 function surfaces, four distinct
provider hashes, newer interfaces, weak C++ exports, runtime/PInvoke evidence,
and VAIL's direct ELF consumer. The accessible six Steam games did not provide
an additional ABI or a no-Steam-provider example. All findings retain scope.

## LLVM and immutable-host deployment

Decision: **bundle compatible ARM64 LLVM**, preserving LLVM's Android ELF
packed-relocation implementation. Do not implement a new embedded parser.
[LLVM_RUNTIME.md](LLVM_RUNTIME.md) documents the pinned package extraction,
licenses, hashes and private library launcher. Ubuntu LLVM's `libedit.so.2`
and `libtinfo.so.6` did not match available host SONAMEs, so both are bundled
privately; no ABI-incompatible symlink or host package install was used.

The prepared ARM64 reader reported LLVM 20.1.8 on the Frame. Its complete native
dependency graph resolved against Frame glibc 2.39 and the private libraries.
Native live Job Simulator CLI returned exit 1 with the same static/runtime
consumer evidence as workstation analysis. Native host analysis of all four
additional APKs matched workstation coverage and every consumer/runtime record.
Linux host tool experiments used only the separately created
`/tmp/creamlinux-analyzer-runtime-2026-10-07/`, required for Linux/glibc execution
outside Android. That directory was cleaned after collecting logs.

Explicit reader selection fails closed. Packaging the proven runtime as a
Tauri resource and connecting its absolute path to the embedded backend remain
next-milestone work; no AppImage was rebuilt. Required host libraries must be
checked for supported SteamOS images during packaging.

## Status, limitations and next milestone

The CLI preserves original top-level keys and adds provider SHA256 plus explicit
function generation, local/hardware/binding validation, non-function coverage,
and evidence fields. Evidence validation rechecks deterministic sources,
independent binary parity, exact input hashes, original logs, every resolution
name, stage exits and safety counters. Missing/stale/mismatched evidence returns
operational exit **2**, with pure JSON and no expected-error traceback. Current
fixed-proxy compatibility continues to control completed exits **0/1**.

Generated v1.1 artifacts are complete directories with provider identity,
normalized reproducible paths, toolchain/API/source fingerprint and a cache key.
Future managed caches should retain each immutable directory under that key and
reverify before reuse. No implicit cache reuse, proxy installation or unsafe
GUI action was added. A summary JSON alone is not accepted as hardware proof;
retained bundle/log files and observation are required. These records are
operator observations, not cryptographic attestations of hardware execution.

Job Simulator still omits **209** non-functions, Walkabout **4**, and the other
four providers **209** each. No consumer requirement or runtime non-function
literal candidate was observed, which does not prove absence of computed
lookups. Aliased address identity, full object ABI and actual game execution
remain outside validated scope.

**CLI is ready for read-only inspector/backend and AppImage-runtime integration**
with these separate states and limits. Actual proxy installation/game injection
is unsupported. No external blocker remains. A real split game is optional
additional evidence when available. The next milestone is to expose these exact
CLI states in the existing inspector and package the proven ARM64 reader;
GUI polish should follow backend/resource verification.

## Current diff and all files changed

This session changed the analyzer, target generator, evidence importer, pinned
LLVM runtime builder, regression tests and current documentation/evidence.
Pre-existing Lepton backend/UI and proxy/hardware-bundle work were preserved.
The inventory below includes both previous work and this session; it does not
attribute every existing edit to this session.

Tracked diff statistics (untracked additions are separately listed):

```text
 src-tauri/src/lepton.rs                            |  13 +-
 src-tauri/src/main.rs                              |  11 +
 src/components/pages/LeptonInspectorView.tsx       |  72 ++++-
 src/styles/components/pages/_lepton_inspector.scss |  16 +
 src/types/Game.ts                                  |  15 +
 tools/android-steam-proxy/FRAME.md                 |   3 +-
 tools/android-steam-proxy/PARITY.md                |   7 +-
 tools/android-steam-proxy/README.md                | 359 ++++++++++++++++++++-
 tools/android-steam-proxy/generate.py              | 148 +++++++--
 tools/android-steam-proxy/tests/abi_test.c         |  18 +-
 tools/android-steam-proxy/tests/run_android.sh     |   5 +-
 tools/android-steam-proxy/tests/scan_consumers.py  |  83 ++++-
 12 files changed, 683 insertions(+), 67 deletions(-)
```

All modified/untracked files:

```text
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
?? src-tauri/src/lepton_compatibility.rs
?? tools/android-steam-proxy/HARDWARE_VALIDATION.md
?? tools/android-steam-proxy/JOBSIMULATOR_HARDWARE.md
?? tools/android-steam-proxy/LLVM_RUNTIME.md
?? tools/android-steam-proxy/TARGET_PROXY.md
?? tools/android-steam-proxy/VALIDATION_STATUS.md
?? tools/android-steam-proxy/build_hardware_bundle.py
?? tools/android-steam-proxy/build_llvm_runtime.py
?? tools/android-steam-proxy/compatibility.py
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
?? tools/android-steam-proxy/tests/test_hardware_bundle.py
?? tools/android-steam-proxy/tests/test_llvm_runtime.py
?? tools/android-steam-proxy/tests/test_target_proxy.py
?? tools/android-steam-proxy/tests/test_validation_evidence.py
?? tools/android-steam-proxy/validation_evidence.py
?? tools/android-steam-proxy/verify_target_proxy.py
```
