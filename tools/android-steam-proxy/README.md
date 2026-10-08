# Android ARM64 Steam API forwarding POC

Latest CLI/hardware work is summarized in [VALIDATION_STATUS.md](VALIDATION_STATUS.md).
Job Simulator's exact target function harness passed Steam Frame/Bionic validation;
six real game APKs have CLI evidence. This remains function-only compatibility
research, with no installation or game injection workflow. The original phase
results below retain their workstation scope.

Built with **Android NDK r30 (30.0.16248370), arm64-v8a, API 21**.
The mock and reference-function proxies compile successfully. Static Bionic
AArch64 execution under QEMU passes **11,047 ABI checks** and the uninitialized
slot exits **127** as required. Android dynamic loading and real-library loading
remain **not executed**: this host has no `/system/bin/linker64` runtime.

This is a standalone forwarding experiment. No installer integration, game
modification, injection, replacement, DLC behavior, commit, or push was performed.

## Preserved evidence and reproducible build

The previous handoff is preserved verbatim as `PHASE3-checkpoint.md`.
`generated/reference-manifest.json`, `generated/reference-readelf.txt`, and
`generated/verification.json` are unchanged historical evidence; their old
"not built" fields describe the Phase 3 stop, not today's build.
New results are under `build/`.

```bash
export ANDROID_NDK_HOME=/home/diemitchell/.local/share/android-ndk/android-ndk-r30
export ANDROID_NDK_ROOT="$ANDROID_NDK_HOME"
./tools/android-steam-proxy/build.sh
python3 tools/android-steam-proxy/tests/run_local.py
./tools/android-steam-proxy/package.sh
```

`build.sh` uses `aarch64-linux-android21-clang` from that NDK. No host compiler or
substitute sysroot is used for the Android artifacts. `generate.py` reads the
existing manifest and emits only its selected FUNC names, sorted deterministically.
It does not rerun the ELF analysis. Each build checks the reference SHA-256:

```text
f424277c8a431542b93bf71215615fa6730edb7968a03f5230d484437f0d4aa4
```

## Artifacts and measured coverage

All paths below are relative to this directory.

| Artifact | Purpose / result |
| --- | --- |
| `build/mock/libmock_original.so` | 1,047 functions: 17 ABI cases plus 1,030 distinct slot probes |
| `build/mock/libsteam_api.so` | Mock proxy: exactly 1,047/1,047 function exports |
| `build/real/libsteam_api.so` | Real proxy: exactly 1,045/1,045 reference function exports |
| `build/{mock,real}/stubs.S` | Generated three-instruction AArch64 stubs and initialized target slots |
| `build/{mock,real}/{names.json,exports.map,symbols.h}` | Export lists, anonymous visibility scripts, private tables |
| `build/abi_test` | Dynamic standalone Android mock ABI executable |
| `build/abi_static` | Static Bionic executable using identical generated stubs and ABI cases |
| `build/load_probe` | Real proxy loader and 1,045-name resolution probe; no Steam API calls |
| `build/mock_load_probe` | Mock-only loader probe for failure cases |
| `build/mock/{libempty.so,libdependency.so}` | Missing-symbol and wrong-owner fixtures |
| `build/run_android.sh` | Mock dynamic/static suite plus six loader rejection tests |
| `build/static-verification.json` | Exact export sets and linked-stub checks |
| `build/runtime-verification.json` | QEMU output, exit codes, dynamic-runtime failure evidence |
| `build/consumer-scan.json` | Available local ELF evidence; no actual consumers present |
| `build/build.log`, `build/toolchain.txt` | Build log and compiler/NDK identification |
| `build/android-steam-proxy-poc.tar.gz` | Frame bundle with binaries, docs and SHA256SUMS |

There are **zero missing supported functions and zero additional public exports**
in either proxy. Relative to all 1,049 public reference exports, coverage is
**1,045/1,049 (99.62%)**. The four omitted names are the single unsupported data
object and three linker boundaries below. This is not full ABI compatibility.

Verification inspects linked instructions and checks each ADRP/LDR slot address
against its intended table index, not just the mnemonic pattern. All public
GLOBAL/WEAK/UNIQUE and DEFAULT/PROTECTED candidates are considered; the actual
exports must be GLOBAL/DEFAULT FUNC. Both proxies retain SONAME `libsteam_api.so`,
use LIBC-versioned libc/libdl imports, NOW/RELRO, SysV hash for API 21, a
non-executable stack, and 16 KiB load alignment. There are no text relocations,
TLS segments, or public implementation helpers. The Android note records API 21
and NDK r30. The original remains 4 KiB aligned.

## Forwarding and initialization

Each function is `ADRP x16, slot; LDR x16, [x16, lo12(slot)]; BR x16`.
Each slot has its own page relocation, so the table works beyond 4 KiB.
SP, LR, x8, x18, argument registers and SIMD registers are untouched. This follows
the scratch-register/tail-call rules in [Arm AAPCS64](https://github.com/ARM-software/abi-aa/blob/main/aapcs64/aapcs64.rst).
No signature is inferred for any real Steam export.

The constructor requires an absolute `CREAMLINUX_ORIGINAL_STEAM_API` path,
rejects the proxy's own inode, opens with `RTLD_NOW | RTLD_LOCAL`, and resolves
all names from that explicit handle. Every target's `dladdr` mapping must match
the requested original's device/inode and differ from the proxy mapping.
This rejects missing functions, self-resolution and functions obtained from a
dependency. All slots initially target an exit-127 failure routine; none are null.
Resolution finishes before slot publication. The original handle is retained
without `dlclose` for process lifetime.

**Loading assumption:** load synchronously and publish entry points to callers
only after `dlopen` returns. Slots are assigned individually with plain stores;
there is no atomic all-slots publication protocol. A constructor-spawned thread
with access to proxy entry points during final publication is outside this POC's
supported loading model. Reentry during the resolution phase fails closed.
The dynamic constructor/reentry behavior still needs Android runtime validation.
The QEMU uninitialized-slot test proves the initial failure target, not loader
constructor ordering.

## ABI tests

The same assertions and assembly stubs are used in dynamic and static executables:

- Signed integers, full-width 64-bit values, pointers, 8 and 12 integer arguments.
- Float/double, 8 and 12 FP arguments, mixed integer/FP/pointer arguments.
- Two-register aggregate return, four-word indirect return through x8,
  homogeneous FP aggregate argument/return, vector argument/return.
- Variadic arguments, callbacks, large indirect aggregate arguments.
- 1,030 distinct target slots and 10,000 repeated stack-argument calls.

Local measured result: **11,047 assertions pass under `qemu-aarch64`**, and
`--uninitialized` exits 127. This executes Android-targeted static Bionic code;
it does not emulate Android's dynamic linker, namespace rules or Lepton.

`run_android.sh` additionally tests missing environment, relative path,
nonexistent original, self-load, missing symbols and dependency-owned symbols.
These six dynamic failure cases and the dynamic ABI executable are built but
**not run locally**. No real Steam function has been called. No real original
library has been dlopened locally.

## Single writable export: explicitly unsupported

`g_pSteamClientGameServer` is an 8-byte writable OBJECT at original ELF address
`0x2e5a0`. The original's relocation at `0x2c360` is an
`R_AARCH64_GLOB_DAT` referring to that name. This establishes an internal dynamic
relocation, **not a consumer reference**. At the initial POC analysis, the only available local native inputs were two
identical copies of the reference itself; no game consumer or APK was available.
Consumer usage was **unknown**, not absent. The later read-only capture findings
below supersede that evidence availability limit.

The POC deliberately defines no object, trampoline, pointer copy or alias at this
name. A pointer-sized proxy variable would have a different address; copying its
value cannot preserve arbitrary writes through the original and consumer aliases.
Function forwarding cannot forward a data lvalue, and an ELF symbol definition
cannot become a runtime `dlsym`-based storage alias.

A plausible future design is to give the original a unique, stable dependency
identity and put it in the proxy/consumer's `DT_NEEDED` dependency graph **before
consumer relocations**, leaving the original as the only object definition.
Then the consumer relocation and handle-scoped dependency lookup can select the
original storage. This requires checking Android search scopes, load ordering,
SONAME identity, symbol interposition, and pointer identity/write visibility on
hardware. A constructor-only `RTLD_LOCAL` dlopen is not a substitute for that
dependency graph. Defining another object and hoping the original's GOT is
interposed is insufficient without proving all references bind to the same
storage; changing load order or already-loaded originals can break it.

This alternative is **not implemented or validated**. The original and SONAME
have not been patched. Until actual consumer evidence and identity tests are
available, this remains the **one unsupported public data export**.
`tests/scan_consumers.py` recursively inspects local directories, base/split APKs,
and ZIP/APKS/XAPK bundles (including nested archives). It requires Python 3 and
`llvm-readelf`; LLVM decodes Android packed relocations as well as REL/RELA/RELR.
See [LLVM's Android relocation support](https://reviews.llvm.org/D39272).
No ELF is loaded or executed. Input files are opened read-only; embedded libraries
are copied to temporary files for inspection, then those copies are removed.
See [the scan commands and report interpretation](FRAME.md#4-optional-read-only-consumer-evidence-collection).

JSON `files` entries contain `file`, `architecture`, `sha256`, `imported_symbols`,
`relocations`, `string_occurrences`, `defined_symbols`, and
`symbol_table_references`. Symbol/relocation/string lists are filtered to the four
target names. Dynamic and regular symbol tables are distinguished; relocations
include section, offset, type, dynamic status, symbol binding and definition
status. Versioned names retain their full spelling and match by the name before
`@`. String hits include byte offsets and containing sections, including symbol
and debug string tables; substring hits are reported too. They never establish
linkage or prove `dlsym` use.

`summary.g_pSteamClientGameServer.statically_required` is true when an inspected
ELF has a non-weak external import/reference. `static_reference_detected` also
includes weak imports, which do not by themselves require a provider. Evidence
records distinguish imports, relocations, definitions, regular symbol-table
entries, and strings. A definition (even with a self relocation) does not prove
that a consumer needs an external proxy export. An import does not prove which
library provides it, that the code executes, or that the app fails without it.
The same summary is provided for the three linker boundary names.

Exit status is 0 for a completed scan and 2 for an incomplete scan, with errors
recorded in JSON. Missing/malformed inputs, reader warnings, sectionless images,
and scans finding no ELF files cannot yield a clean negative result. A normal
stripped ELF retaining its dynamic metadata is supported. Check `scan_complete`
before interpreting false: even a complete scan only covers supplied inputs and
cannot exclude omitted splits, downloaded consumers, computed runtime names, or
internal static uses whose symbols and relocations have been stripped.

Host-only scanner regression tests (requires `clang`, `ld.lld`, `llvm-readelf`):

```bash
python3 tools/android-steam-proxy/tests/test_scan_consumers.py
```

The tests compile synthetic ARM64/ARM32 fixtures and inspect them without loading
or executing them. They also verify input file hashes and directory contents are
unchanged after scans.

## Linker boundary names

`__bss_start`, `_edata`, and `_end` are omitted. No function stubs or substitute
proxy boundaries are created. They describe the original image's layout, not
Steam interfaces; proxy boundaries would describe unrelated addresses.
No relocation to these three names was found in the reference itself. There is
no evidence that this standalone function-only test needs them. Actual consumer
compatibility remains conditional on checking consumer imports/runtime lookups:
a consumer explicitly requesting an omitted boundary would fail, so exact
1,049-name transparency is not claimed.

## SONAME, real loader and next commands

The bundle contains `real/libsteam_api_original.so`, a byte-for-byte copy of the
reference retaining SONAME `libsteam_api.so`. The absolute renamed path is used
for the standalone probe; no mandatory SONAME patch is assumed. Android changed
basename/SONAME matching in API 23, so API-21 compilation does not establish
loader behavior on every Android version. See [Android linker change notes](https://android.googlesource.com/platform/bionic/+/master/android-changes-for-ndk-developers.md).

The real probe resolves function names but does not call their targets. Loading
still runs ELF constructors. The bundled r30 ARM64 `libc++_shared.so` is only a
candidate standalone runtime; its compatibility with the r21 reference and
Lepton namespace access to `libandroid.so`/`liblog.so` remain untested.

**Exact transfer, Lepton, ADB, mock, real-resolution and evidence-collection
commands are in [FRAME.md](FRAME.md).** They use a fresh `/data/local/tmp`
directory in an already-running development/test context, never installed game
paths. Device execution is the next validation step, not a completed phase.

## Initial POC progress ledger and review

- Phase 3: NDK r30 located; build script and API 21 artifacts produced.
- Phase 4: 1,045 real / 1,047 mock generic stubs and fail-closed resolver built.
- Phase 5: Absolute-path loading retained; reference copy unchanged, no SONAME patch.
- Phase 6: Mock ABI built; static QEMU execution passed; dynamic execution pending.
- Phase 7: Exact function export sets and all linked slot addresses verified.
- Phase 8: Real loader built, not run.
- Phase 9: Host ELF checks and static execution passed; dynamic-runtime absence recorded.
- Phase 10: Frame bundle and non-invasive commands prepared, not executed.

Review found no blocking ABI defect. Its publication-order finding is recorded as
the single-threaded loading restriction above; violating it can expose partially
published targets. The export verifier was strengthened to reject accidental weak
or protected public exports as well as extra ordinary exports. The original
analysis files and reference hash remain unchanged.

## Standalone benign runtime parity

`package-parity.sh` builds the separate
`build/android-steam-proxy-parity-poc.tar.gz` bundle. It preserves the existing
mock ABI and zero-call resolution tests and adds `parity_probe`, a fixed three-call
pre-initialization harness, a hash-checking Android runner, and a host JSON
comparator. See [PARITY.md](PARITY.md) for the reviewed signatures and exact
reference disassembly, and [FRAME.md section 5](FRAME.md#5-standalone-benign-runtime-parity-three-pre-init-calls)
for complete build, transfer, execution, and result-collection commands.

The completed hardware result is recorded in [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md). Matching false/zero values demonstrate
only parity for these three pre-init reads, not initialized Steamworks or game
compatibility. No initialization, DLC/entitlement/inventory calls, or writes to
Steam state are added.

## Manual inspector compatibility analysis

CreamLinux's Lepton Inspector now offers **Analyze compatibility**. The Linux
backend refreshes metadata using the existing `lepton exec CONTEXT true` probe,
then runs the embedded `compatibility.py`, shared `tests/scan_consumers.py`, and
preserved `generated/reference-manifest.json` with host Python 3 and
`llvm-readelf` on PATH. Neither repository access nor proxy build artifacts are
needed by the packaged app. Missing dependencies produce an inconclusive result.

The analyzer rechecks the running context and all `pm path PACKAGE` entries,
reads the installed Steam API and every base/split APK using `lepton exec ... cat`,
and scans private host temporary copies. It rechecks the APK list afterward.
Temporary scripts, APKs, library copies and extracted members are removed on
normal completion/error. Abrupt host process termination can leave OS temporary
files; no copied data or generated `/data/app` path is saved as game identity.
No Android writes, package changes, launches, proxy generation, loading, or
installation occur. Large packages require host disk space and can take minutes;
individual CLI/LLVM operations have timeouts (30/60 seconds; copies 120 seconds).

Coverage uses the same manifest as `generate.py`, including all targets required
by the current proxy constructor. Missing/extra unsupported functions, versioned
or variant-PCS functions, unsupported architecture/ABI, or required unsupported
exports prevent a positive result. Optional unsupported data/boundary exports
can yield **Compatible for observed static consumers** only with complete
inspection and at least one consumer. The shared scanner now accepts arbitrary
symbol targets; its default four-symbol CLI behavior is retained.

Scope is observed native ELF consumers in all listed APKs. Downloaded libraries,
system consumers, package updates that retain identical paths, computed `dlsym`,
and runtime behavior are outside this snapshot. Weak references, definitions,
and string matches do not establish mandatory external requirements. An undefined
symbol overlapping the Steam provider is not automatically attributed to that
provider; the linkage and alternate-provider policy below applies.

See [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md) for completed hardware
results and the separate validation still needed for this inspector integration.

## Standalone compatibility CLI

`compatibility.py` also supports development-machine analysis with human-readable
output by default. Both CLI modes use the same provider inspection, consumer
`Scanner`, generated proxy manifest, and `evaluate()` policy as the inspector.
The analyzer only reads inputs: it never loads native libraries, calls Steam
APIs, initializes Steamworks, installs anything, or changes APKs/game files.

Analyze a local copy of the Steam API and every base/split APK:

```bash
python3 tools/android-steam-proxy/compatibility.py files \
  --steam-api ~/creamlinux-walkabout-cli/libsteam_api.so \
  --apk ~/creamlinux-walkabout-cli/apks/base.apk \
  --abi arm64-v8a
```

Repeat `--apk /path/to/split.apk` for each split. Files mode performs no Lepton
commands; it inspects the local provider, scans all supplied APKs read-only, and
excludes copies of the provider from consumer evidence by SHA-256. Supply the
complete APK set and the package's primary ABI; local mode cannot verify either
against an installed package.

Analyze an already-running package with a locally accessible Lepton CLI:

```bash
python3 tools/android-steam-proxy/compatibility.py live \
  --lepton /home/steamos/.local/share/Steam/steamapps/common/Lepton/lepton \
  --context steamlaunch-1408230 \
  --package com.MightyCoconut.WalkaboutMiniGolf
```

Live mode validates LLVM, verifies running state with `exec CONTEXT true`, queries
the current `pm path PACKAGE` list, identifies `base.apk` and its install root,
and reads `dumpsys package PACKAGE` for the primary ABI (`getprop
ro.product.cpu.abi` is the fallback). It discovers `libsteam_api.so` with
`find INSTALL_ROOT/lib -name libsteam_api.so`, preferring the primary ABI's
library directory and rejecting ambiguous results. It copies the provider and
all APKs through read-only `exec CONTEXT cat PATH` operations into private host
temporary files, then rechecks `pm path` after scanning. It never uses `lepton ps`
as the running-state authority or saves transient `/data/app` tokens as identity.

For desktop development against a remote Frame, point `--lepton` at your existing
SSH wrapper, which forwards its arguments to the Frame's Lepton executable and
preserves stdout bytes and exit status (SSH must not allocate a terminal):

```bash
python3 tools/android-steam-proxy/compatibility.py live \
  --lepton /tmp/creamlinux-live-lepton \
  --context steamlaunch-1408230 \
  --package com.MightyCoconut.WalkaboutMiniGolf
```

SSH wrapping is a **development technique**, not part of the final Steam Frame
deployment architecture. LLVM runs on the development machine; this does not
solve the currently missing `llvm-readelf` on the Frame host.

The standalone CLI has been validated against both the local Walkabout snapshot
and the live running `steamlaunch-1408230` context through the development SSH
wrapper: 1,049 public exports, 1,045 supported functions, no required unsupported
exports, and 14 consumer ELFs in one APK; both modes exited `0`. Split discovery
and failure cases are covered by fake-Lepton and generated-ELF regression tests;
Job Simulator files-mode findings are recorded below. Additional split
installations and native Frame deployment remain separate validation work.

Add `--json` to either mode for only structured compatibility JSON
on stdout, for example:

```bash
python3 tools/android-steam-proxy/compatibility.py files \
  --steam-api ~/creamlinux-walkabout-cli/libsteam_api.so \
  --apk ~/creamlinux-walkabout-cli/apks/base.apk \
  --abi arm64-v8a --json > compatibility.json
```

The default tool is `shutil.which("llvm-readelf")`. Override it with
`--readelf /usr/bin/llvm-readelf` in either CLI mode. The selected tool must pass
a read-only ELF probe using the scanner's exact LLVM JSON options, including
`--elf-output-style=JSON`; GNU `readelf` is rejected without a fallback.

CLI exit status is independent of output format:

| Code | Meaning |
| --- | --- |
| `0` | Complete analysis, compatible for observed static consumers |
| `1` | Complete analysis, incompatible with the current fixed proxy |
| `2` | Incomplete analysis, operational failure, or invalid CLI arguments |

Incomplete inspection takes precedence over an incompatibility finding for exit
status: a partial scan exits `2` even if JSON already contains
`proxy_compatible: false`. CLI analysis failures produce an inconclusive result
without a traceback; argument-parser usage errors go to stderr. Help exits `0`
without reading stdin:

```bash
python3 tools/android-steam-proxy/compatibility.py --help
python3 tools/android-steam-proxy/compatibility.py live --help
python3 tools/android-steam-proxy/compatibility.py files --help
```

With no arguments and redirected/piped stdin, the inspector's legacy protocol
is preserved, including its original top-level JSON keys and exit `0` for handled analysis
failures or incompatible results:

```bash
python3 tools/android-steam-proxy/compatibility.py < request.json
```

This mode still accepts `{"cli": "...", "info": {"context": "...", "package":
"...", "apk_path": "...", "steam_api_path": "...", "primary_abi": "..."}}`.
Running with no arguments from an interactive terminal shows help and exits `2`.


## Separate compatibility and evidence models

The current fixed proxy remains the Walkabout-derived 1,045-target proxy. Its
constructor requires every manifest target to be present. Top-level
`proxy_compatible`, `supported_function_exports`, and CLI exit status continue
to describe this fixed proxy. Target-specific forwarding feasibility is a
separate, unvalidated assessment; this analyzer does not generate or install a
proxy. The manifest and forwarding implementation are unchanged.

All original top-level keys remain: `analyzed`, `steam_api_found`,
`architecture`, `total_public_exports`, `function_exports`,
`supported_function_exports`, `unsupported_exports`,
`required_unsupported_exports`, `proxy_compatible`, `compatibility_scope`, and
`notes`. The four additive objects below are `null` on operational failures.
The legacy stdin request format and handled-error exit `0` are unchanged; the
Rust deserializer accepts the additional fields.

| JSON object | Contents and interpretation |
| --- | --- |
| `current_proxy` | Manifest/target function counts, name intersection, structurally supported count, complete lists of target functions not forwarded or absent from the manifest, proxy targets absent from the target, present-but-unsupported targets, architecture/ABI support, and fixed-proxy `compatible`. |
| `consumer_evidence` | Per-ELF `dt_needed`, `directly_needs_libsteam_api`, undefined Steam-named symbols, provider-export intersections, and candidate alternate packaged providers (including SONAME and whether directly needed). Aggregate counts concern the target ABI. Each overlap records attribution confidence and `exact_provider_established: false`. |
| `runtime_resolution_evidence` | Per-ELF loader API imports, module and Steamworks.NET markers, Steam-related strings, raw exact export/function strings, strings explained by the consumer's dynsym/symtab, `runtime_lookup_literal_candidates`, and Steam-named/target-only subsets. Confidence is `strong_candidate`, `candidate`, `literal_evidence_only`, or `no_runtime_lookup_evidence`. |
| `target_specific_forwarding` | `assessment: candidate/blocked/inconclusive`, `validated: false`, function/non-function counts, complete non-function export list, structural function blockers, weak bindings needing review, bounded static non-function requirements, runtime non-function literal candidates, and limitations. |

Consumer file identities use stable `apk[INDEX]!/lib/... [entry N]` labels; the
index refers to the supplied APK order (the sorted discovered order in live
mode). This avoids temporary paths in results and makes identical snapshots
comparable across files, live and legacy modes. Every consumer has evidence;
other architectures are marked `relevant_target_abi: false` and listed in
`ignored_other_abi_files`. They do not affect target-ABI requirements or runtime
confidence. No matching consumer ELF means incomplete analysis (CLI exit `2`).

Undefined imports are linkage evidence, not exact provider attribution. A
non-weak exact-name import, direct `DT_NEEDED libsteam_api.so`, and no observed
alternate packaged export produce a **bounded conservative requirement**. Only
unsupported exports meeting that policy enter `required_unsupported_exports`.
An overlap without the direct dependency is unattributed. An alternate packaged
provider makes it **ambiguous / alternate provider available**, even with a
direct Steam dependency, and prevents hard attribution. A candidate provider
need not be loaded: `directly_needed` records the observed dependency evidence.
System libraries, transitive load graphs, symbol versions and Android load
scopes can still affect binding; the analyzer never claims an exact provider.
The standalone scanner's `summary.statically_required` continues to mean
"needs an external definition", independently of provider attribution.

Runtime strings are scanned as entire printable strings, avoiding substring
matches in the compatibility model. Candidates exclude names present in the
consumer's own dynamic or regular symbol table and strings located in
symbol/string/debug tables. This intentionally conservative filter can discard
a real lookup literal whose name is also a normal ELF symbol. Raw matches remain
available separately in JSON. The scanner's original four-name substring/offset
evidence remains available through its standalone CLI.

A Steam-named literal, module name or Steamworks.NET marker together with a
`dlsym` import makes the library a strong runtime-resolution candidate.
`dlopen`/`android_dlopen_ext` with Steam evidence gives a candidate; literals
without loader imports give weaker evidence. C++ ABI literal matches alone
cannot create strong Steam confidence, even with loader imports. None of these
states proves a particular name is dynamically called or creates a hard export
requirement. Computed names and runtime-only consumers remain unknown.

Target-specific assessment is `blocked` for unsupported architecture/function
shapes or conservatively required non-function exports; `inconclusive` for
incomplete or insufficient consumer evidence, runtime non-function candidates,
or weak-binding policy questions; otherwise it is `candidate`. Global and weak
ordinary AArch64 function shapes can use the trampoline mechanism, but the
existing generator only emits global definitions. Weak binding/interposition
needs an explicit policy before extending it. Non-function storage, TLS, aliases
and address identity cannot be forwarded by function trampolines. Even
`candidate` does not mean compatible or hardware validated.

Human output separates Steam API Target, Current Proxy, Static Consumer
Evidence, Runtime Resolution Evidence, Target-Specific Forwarding Assessment,
and Limitations. It prints counts and bounded blocker lists by default. Add
`--verbose` for full unsupported-symbol lists and per-consumer evidence, or
`--json` for complete machine-readable lists (`--json --verbose` still emits
only JSON).

## Two real-game read-only findings

Both local ARM64 captures were analyzed with LLVM JSON inspection; no native
library was loaded and no game file was changed.

| Capture | Walkabout Mini Golf | Job Simulator |
| --- | --- | --- |
| AppID / package | 1408230 / `com.MightyCoconut.WalkaboutMiniGolf` | 448280 / `com.owlchemylabs.jobsimulator` |
| Lepton context | `steamlaunch-1408230` | `steamlaunch-448280` |
| Architecture / ABI | ARM64 / arm64-v8a | ARM64 / arm64-v8a |
| Public exports / functions | 1,049 / 1,045 | 1,365 / 1,156 |
| Manifest targets / intersection | 1,045 / 1,045 | 1,045 / 1,036 |
| Target functions not forwarded / proxy targets absent | 0 / 0 | 120 / 9 |
| Non-function exports | 4 | 209 |
| Consumer ELFs | 14 | 19 (20 packaged ARM64 libraries including the provider) |
| Direct Steam dependencies / normal Steam-named undefined imports | 0 / 0 | 0 / 0 |
| Hard required unsupported exports | None | None |
| Fixed proxy / CLI exit | Compatible for observed static consumers / 0 | Incompatible / 1 |
| Target-specific assessment | Candidate, unvalidated | Inconclusive, unvalidated; 21 weak function bindings need review |

Walkabout provider SHA-256:
`f424277c8a431542b93bf71215615fa6730edb7968a03f5230d484437f0d4aa4`.
Job Simulator provider SHA-256:
`345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700`.
Walkabout's existing hardware trampoline validation is recorded separately in
[HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md).

Job Simulator has a newer/different Steam interface surface. Its nine missing
Walkabout-era targets include older versioned accessors (Apps v008, Input v006,
Utils v010, RemotePlay v003, MatchmakingServers v002, NetworkingSockets v012,
GameServerNetworkingSockets v012, GameServerUtils v010) and
`SteamAPI_ISteamUtils_IsSteamRunningOnSteamDeck`. The current constructor cannot
resolve them. Newer accessor variants in the target do not satisfy those exact
names, and absence of a raw consumer string does not prove an export unused.

Job Simulator's provider itself does **not** need `libc++_shared.so` and exports
C++ ABI/runtime functions and objects. The old analyzer reported 19 C++ imports
as hard unsupported Steam requirements. All 19 also exist in the APK's packaged
`libc++_shared.so`; after subtracting those exports, zero remain. They are now
reported as ambiguous alternate-provider overlaps rather than hard Steam
requirements. This does not prove which library Android actually binds.

Neither game's inspected APK consumers statically link `libsteam_api.so` or
import normal Steam-named undefined dynamic symbols. Both `libil2cpp.so` files
have `steam_api`, `com.rlabrecque.steamworks.net.dll`, Steam entry-point literals,
and `dlopen`/`dlsym` imports: strong evidence for Steamworks.NET/IL2CPP
PInvoke-style resolution, without proof of per-symbol calls. Job Simulator's
`libgame.so` has no comparable Steam literal evidence.

For Job Simulator, 1,020 of 1,156 provider function names occur as raw exact
`libil2cpp.so` strings. Of 120 functions outside the current manifest, 105 have
raw exact matches, but only 14 are SteamAPI-named entry points. Most others are
C++ ABI/runtime names that can be explained by ELF tables or unrelated runtime
uses. The filtered Steam-named literal set retains these 14 target-only entry
points. The 13 remaining new Steam-named exports without exact string matches
are not declared unused. No consumer requirement for the 209 non-function
exports was observed; their forwarding limitation remains explicit.

Reproduce the Job Simulator snapshot analysis (expected exit `1`):

```bash
python3 tools/android-steam-proxy/compatibility.py files \
  --steam-api ~/creamlinux-jobsimulator-cli/libsteam_api.so \
  --apk ~/creamlinux-jobsimulator-cli/apks/base.apk \
  --abi arm64-v8a
```

Read-only live analysis of an already-running Job Simulator context:

```bash
python3 tools/android-steam-proxy/compatibility.py live \
  --lepton /tmp/creamlinux-live-lepton \
  --context steamlaunch-448280 \
  --package com.owlchemylabs.jobsimulator --json
```

The wrapper must already exist and preserve binary stdout. Native Frame live
analysis and isolated forwarding mocks have now run; see the current validation
report for their distinct scopes. Synthetic/mock ELF
fixtures cover the evidence policy, both fixed-proxy exits, base/split scanning,
pure JSON, and legacy stdin:

```bash
python3 -m unittest discover -s tools/android-steam-proxy/tests -p 'test_*.py'
git diff --check
```

## Target-specific function proxy generator POC

The provider-driven build entry point is now `generate_target_proxy.py`; it
reuses `generate.py`'s AArch64 emitter and the existing safe loader. It preserves
GLOBAL/WEAK function binding and omits/reports all non-functions. Job Simulator
and Walkabout have exact static function parity. Target-specific runtime status
is hash-scoped: Job Simulator's controlled function harness passed on Frame;
other providers retain their own local-only status. The fixed-proxy analyzer
is unchanged.
See [TARGET_PROXY.md](TARGET_PROXY.md) for the CLI, exact counts, mock evidence,
reproduction commands, and validation limits. The earlier
analyzer findings above remain a record of the fixed proxy and evidence model.

## Isolated Job Simulator hardware bundle

See [JOBSIMULATOR_HARDWARE.md](JOBSIMULATOR_HARDWARE.md) for reproducible bundle
creation, separate Android/Bionic mock and weak-binding stages, a zero-call
real-provider resolver, checksum guards, and exact Lepton deployment commands
for `creamlinux-poc`. The individual stages and combined replay passed on
Steam Frame. See that document for measured provider/proxy/bundle hashes;
the fixed-proxy Job Simulator result remains false / exit 1.

The CLI now accepts explicit generated artifacts and verified hardware logs.
See [TARGET_PROXY.md](TARGET_PROXY.md) for the separate status fields, hash-scoped
evidence and unchanged exit codes. [LLVM_RUNTIME.md](LLVM_RUNTIME.md) documents
the pinned ARM64 reader bundle and native Frame CLI proof without host package
installation. [INSPECTOR_INTEGRATION.md](INSPECTOR_INTEGRATION.md) records the
read-only inspector/backend integration, rebuilt ARM64 AppImage and native
packaged-backend checks. Fifteen actual native control/dialog checks now pass
through the Frame's existing accessibility interface, without a browser
connection; the documented scope remains separate from gameplay validation.
