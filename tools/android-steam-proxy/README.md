# Android ARM64 Steam API forwarding POC

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
relocation, **not a consumer reference**. The only available local native inputs
are two identical copies of the reference itself. No `libil2cpp.so`, other game
consumer, or APK is available to establish external linkage or `dlsym` usage.
Consumer usage is **unknown**, not absent.

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

## Progress ledger and review

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

The new hardware result remains pending. Matching false/zero values demonstrate
only parity for these three pre-init reads, not initialized Steamworks or game
compatibility. No initialization, DLC/entitlement/inventory calls, or writes to
Steam state are added.
