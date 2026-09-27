# Android Steam API forwarding POC — analysis checkpoint

Status: **stopped before implementation at the requested Phase 3 NDK gate**.
No usable Android NDK was found. No proxy, mock library, test executable, or
modified original copy has been generated. Analysis does not establish runtime
ABI compatibility. A second limitation is that four real exports cannot be
forwarded by function stubs; full export transparency requires a separate design.

## Files and provenance

- `generated/reference-manifest.json`: all 1,096 dynamic symbol entries, with
  name, type, binding, visibility, definition status, section index, size, ELF
  virtual address, version index, and explicit public-export selection.
- `generated/reference-readelf.txt`: `file`, GNU `readelf`, and LLVM `nm` evidence.
- `generated/verification.json`: independent manifest checks and execution status.

The manifest was extracted from the ELF64 section and symbol records using Python
standard-library `struct`, then checked against GNU `readelf` and LLVM `nm`.
Addresses are ELF virtual addresses before ASLR, not live process pointers.
The null entry is retained but is not an export. Undefined imports and local or
hidden symbols are never proxy export candidates. Linker boundary symbols are
retained as public exports and explicitly marked unsupported.

Read-only input, never copied into this repository:

```text
/home/diemitchell/creamlinux-arm64/reference/walkabout-libsteam_api.so
SHA-256: f424277c8a431542b93bf71215615fa6730edb7968a03f5230d484437f0d4aa4
```

## Original ELF analysis

| Property | Observed value |
| --- | --- |
| Class / encoding | ELF64 / little endian |
| Machine | EM_AARCH64 (183) |
| Type | ET_DYN (shared object) |
| Android ABI | arm64-v8a |
| OSABI header | UNIX System V, ABI version 0 |
| Android identification note | API 21, NDK r21, build 6113669 |
| Build ID | dd6e64881c831ee6 |
| SONAME | libsteam_api.so |
| Binding flags | BIND_NOW / NOW |
| PT_LOAD alignment | 4,096 bytes |
| TLS symbols / PT_TLS | None / absent |
| Variant PCS symbol flags | None |
| Version sections | .gnu.version, .gnu.version_r |
| Version definition section | Absent |
| Export symbol versions | All index 1, unversioned global exports |
| Required versions | LIBC from libc.so (index 2) and libdl.so (index 3) |

The note records API 21 as the build minimum; no higher minimum was identified
by this analysis. That does not prove availability of every runtime dependency.
The proxy build should target API 21 when a toolchain becomes available.

DT_NEEDED, in order:

```text
libandroid.so
liblog.so
libdl.so
libc++_shared.so
libc.so
```

`libc++_shared.so` must be available in the standalone test's Android linker
namespace. Finding an NDK does not by itself prove that its libc++ is compatible
with the game library; a compatible runtime must be validated separately.

| ELF type | All dynamic entries | Undefined imports (excluding null) | Public defined exports |
| --- | ---: | ---: | ---: |
| STT_FUNC | 1,087 | 42 | 1,045 |
| STT_OBJECT | 5 | 4 | 1 |
| STT_NOTYPE | 4 | 0 | 3 |
| STT_IFUNC | 0 | 0 | 0 |
| STT_TLS | 0 | 0 | 0 |
| Other | 0 | 0 | 0 |
| Total | 1,096 | 46 | 1,049 |

All 1,049 exports are GLOBAL/DEFAULT. Across the complete dynamic symbol table,
1,095 entries are GLOBAL and one is LOCAL (the null entry); all are DEFAULT
visibility. There are no WEAK, GNU_UNIQUE, HIDDEN, or PROTECTED entries.

### Unsupported public exports

| Name | Type | Size | ELF value |
| --- | --- | ---: | --- |
| g_pSteamClientGameServer | OBJECT | 8 | 0x2e5a0 |
| __bss_start | NOTYPE | 0 | 0x2d3a8 |
| _edata | NOTYPE | 0 | 0x2d3a8 |
| _end | NOTYPE | 0 | 0x2e6cc |

The object is writable storage in `.bss`. The original also has an
`R_AARCH64_GLOB_DAT` relocation referring to it. Exporting an assembly branch at
that name would corrupt the data ABI. Copying its current pointer value into a
proxy object would create distinct storage and would not transparently track
writes. The three boundary symbols describe original section addresses; proxy
linker-generated boundary names would describe different memory.

These four exports must remain explicitly unsupported by a function-only POC.
Do not claim complete library ABI compatibility from a 1,045-function match.

## Function forwarding feasibility

The 1,045 STT_FUNC exports are candidates for the requested generic tail branch.
There are no exported IFUNC resolvers, symbol versions, or variant-PCS flags
requiring an alternative path. ELF type information does not reveal every source
signature or prove undocumented calling conventions; mock runtime tests remain
required.

The proposed sequence uses `ADRP` plus `LDR` to load a pre-resolved target through
a hidden slot, then `BR x16`. Only the PCS scratch register x16 changes; x17 is
also available as scratch if needed. Preserve x0–x7, x8 (indirect result), v0–v7,
x18, callee-saved registers, SP, and LR. Unchanged SP preserves stack arguments;
unchanged LR lets the original return directly to the caller, including scalar,
FP, register aggregate, and indirect returns. `BLR` would overwrite LR. These
requirements follow the [Arm AAPCS64](https://github.com/ARM-software/abi-aa/blob/main/aapcs64/aapcs64.rst).

Implementation requirements when work resumes:

- Give each table slot a hidden local address. Use its page and low 12-bit
  relocation, including slots beyond the first 4 KiB. Avoid absolute text
  relocations and preemptible table symbols.
- Resolve every function from an explicit original handle before publishing the
  proxy for calls. No `dlsym`, C call, stack adjustment, or lazy resolver inside
  the forwarding stub.
- Require an explicit absolute original path, such as
  `CREAMLINUX_ORIGINAL_STEAM_API`; use `RTLD_NOW` and handle-scoped `dlsym`.
- Verify each target belongs to the original mapping, not the proxy or a
  dependency. Fail initialization on missing symbols, self-resolution, or
  reentrant calls before initialization completes. Keep the original loaded
  while any proxy target is callable.
- Hide implementation symbols so future export comparison can require exactly
  the 1,045 supported function names, with no additional public helpers.

These are design requirements, not implemented or compiled assembly.

## SONAME and loader assessment

Renaming a file to `libsteam_api_original.so` does not change its internal
`libsteam_api.so` SONAME. Bare-name requests for `libsteam_api.so`, including
DT_NEEDED dependencies, can select an already-loaded proxy. Before API 23,
Android used basenames for loaded-library matching; API 23 introduced proper
SONAME/path distinction. See the [Android linker change notes](https://android.googlesource.com/platform/bionic/+/refs/heads/android15-tests-release/android-changes-for-ndk-developers.md).

In current upstream Bionic, the SONAME lookup explicitly skips requests containing
`/`. Thus an absolute path to a distinct renamed copy does **not** inherently
require changing SONAME merely to load it beside the proxy. This is an inference
from [Bionic's loader implementation](https://android.googlesource.com/platform/bionic/+/master/linker/linker.cpp),
not a test of Valve's Lepton build. A unique SONAME on a disposable copy could
remove ambiguity for subsequent bare-name/dependency lookups, but would not fix
symbol interposition or data-storage identity. No patch is justified as mandatory
for the explicit-path POC based on the current evidence.

No original copy was made or patched. If hardware evidence later requires a
SONAME change, apply it only to a generated disposable copy outside the repository,
record its new hash, and leave the reference and installed game untouched.

## Local toolchain discovery

Observed on this CachyOS x86_64 host:

| Tool / setting | Result |
| --- | --- |
| ANDROID_NDK_HOME | Unset |
| ANDROID_NDK_ROOT | Unset |
| ANDROID_HOME | /opt/android-sdk |
| ANDROID_SDK_ROOT | /opt/android-sdk |
| CMake | /usr/bin/cmake, 4.4.3 |
| Ninja | /usr/bin/ninja, 1.13.2 |
| Host clang | /usr/bin/clang; not an Android NDK |
| ELF inspection | GNU readelf, LLVM readelf and nm available |
| Emulator command | /usr/bin/qemu-aarch64 available; insufficient alone for Android |
| ADB command | /usr/bin/adb available; no device commands run |

No NDK was found at `$HOME/Android/Sdk/ndk`, `$HOME/Android/sdk/ndk`,
`/opt/android-sdk/ndk`, `/opt/android-sdk/ndk-bundle`, `/opt/android-ndk`, or the
obvious user-local SDK locations. Searches under `/home/diemitchell`, `/opt`,
`/tmp`, and `/usr/local` to depth seven found no toolchain. Additional recursive
`android.toolchain.cmake` searches covered `$HOME/Android`, `$HOME/.local`,
`$HOME/.cache`, `$HOME/.gradle`, `/tmp`, and `/opt/android-sdk`. Unreadable directories
were skipped, so this is a discovery result rather than a claim about every disk.

`/opt/android-studio/plugins/android-ndk` contains IDE plugin JARs, not an NDK.
The missing requirement is a usable Linux-host Android NDK with
`build/cmake/android.toolchain.cmake`, an LLVM AArch64 Android compiler/linker,
and the Android sysroot/CRT/libraries for arm64-v8a API 21. No installation,
package change, or sudo command was attempted.

## Verification status and remaining work

| Requested phase | Result |
| --- | --- |
| 1. Actual ELF / manifest | Complete; metadata cross-checked independently |
| 2. Feasibility | Function subset viable in principle; four unsupported data/address exports |
| 3. Build system | Blocked: Android NDK absent |
| 4. Proxy implementation | Not started, per stop instruction |
| 5. SONAME | Static assessment above; no copied or patched binary |
| 6. Mock ABI tests | Not built or run |
| 7. Real proxy export coverage | Original: 1,049 total / 1,045 functions / 4 non-functions; proxy counts, missing and extra sets not measured because no proxy exists |
| 8. Real loader test | Not built or run; original was never dlopened |
| 9. Local verification | Reference inspection and manifest validation only; no Android runtime success claimed |
| 10. Frame deployment | Not prepared or executed; no executable artifacts exist |

Future mock tests must cover integers, 64-bit values, pointers, 8 and more than 8
integer arguments, float/double, mixed arguments, 8 and more than 8 FP arguments,
register aggregate returns, and an aggregate large enough to exercise x8.
Compilation alone cannot establish transparency. The real loader test must
resolve targets without calling Steam functions, including DLC-related exports.

Exact hardware copy/run commands are intentionally deferred until the actual
executables and their interfaces exist. Providing commands referring to unbuilt
artifacts would not constitute a runnable test. The eventual standalone test must
use an Android temporary directory such as `/data/local/tmp/`, load the original
by explicit path, and never launch, inject into, or modify Walkabout.

Remaining risks: shared mutable data ABI; constructor/reentrancy ordering;
original symbol interposition; actual Lepton loader/namespace behavior;
`libc++_shared.so` availability and compatibility; original 4 KiB segment alignment
on a different page-size runtime; and all unexecuted AArch64 ABI cases.

No existing Steam Frame support files were changed. No commit or push was made.
