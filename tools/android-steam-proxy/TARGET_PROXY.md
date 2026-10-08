# Target-specific function proxy POC

`generate_target_proxy.py` reads the supplied provider's dynamic symbol table
with LLVM JSON inspection. The fixed Walkabout manifest is **not** its input.
It never loads the real provider, executes Steam APIs, installs a proxy, modifies
an APK/game library, or touches a running game. All outputs belong in a separate
build directory. No commits or pushes are part of this workflow.

Build and verify Job Simulator (the output must be new or empty):

```bash
python3 tools/android-steam-proxy/generate_target_proxy.py \
  --provider ~/creamlinux-jobsimulator-cli/libsteam_api.so \
  --output tools/android-steam-proxy/build/jobsimulator-target-next \
  --readelf /usr/bin/llvm-readelf --ndk /opt/android-ndk
```

`--ndk` defaults to `ANDROID_NDK_HOME`, then `ANDROID_NDK_ROOT`. The build uses
that NDK's `aarch64-linux-android21-clang`. `--sources-only` omits compilation
and leaves static validation `not_run`. Generation errors exit `2`; successful
builds include automatic static parity verification. Occupied output directories
are rejected to prevent stale binaries/reports from masquerading as new results.
The provider directory (including descendants) and `/data/app` are rejected as
outputs. Missing/invalid inputs or inspection diagnostics fail generation.

The shared `generate.py:emit_surface()` emits the same proven sequence:

```asm
adrp x16, .Lslot_INDEX
ldr  x16, [x16, :lo12:.Lslot_INDEX]
br   x16
```

This leaves x0–x8, v0–v7, stack, LR, and the return path untouched. Every slot
starts at `proxy_unready` through a relative relocation. The unchanged
`src/proxy.c` constructor resolves **all** names before publishing any slots.
The explicit `CREAMLINUX_ORIGINAL_STEAM_API` path must be absolute; same-file
self-loads, missing targets, and symbols owned by a dependency or the proxy
fail closed (exit `127`). Weak targets are required too. There is no `dlsym`
inside trampolines, interface-version aliasing, or fabricated target function.

GLOBAL definitions use `.global`; WEAK definitions use `.weak`. The export
map controls visibility without promoting weak binding. Ordinary DEFAULT and
PROTECTED visibility are preserved (PROTECTED uses `.protected`), and every
stub is `STT_FUNC`. Versioned names, unsafe assembler names, variant PCS,
IFUNCs, duplicate public names, invalid metadata, unsupported architecture,
and names that collide with loader implementation/dependencies are rejected.
Names must match `[A-Za-z_][A-Za-z_0-9]*`. Provider function addresses/sizes are
recorded for provenance; proxy stubs intentionally have their own addresses and
12-byte sizes. Aliased function-address identity and ELF symbol versions are
not reproduced.

**FUNCTION exports only: this is not a complete ABI clone.** Non-function
exports receive no storage, aliases, or fake function trampolines. Their full
name/type/binding/visibility records are retained in `manifest.json`. Their
presence does not itself block generation. Missing consumer evidence is not
proof that these exports are unused. Runtime validation stays
`unvalidated/limited`, and Steam Frame validation stays `unvalidated`, even
when all static checks and mocks pass. The analyzer's top-level/current fixed
proxy semantics are unchanged: Job Simulator `current_proxy.compatible`
remains false. The generator does not reinterpret weak strings as explicit
consumer `dlsym`/PInvoke requirements.

Each output contains deterministic, sorted `names.json`, `exports.map`,
`symbols.h`, `stubs.S`, and `manifest.json`; compiled builds also contain
`libsteam_api.so` and `function-parity.json`. The manifest records schema and
generator versions, provider SHA256, architecture/ABI, Android API and NDK
when an Android note is available (otherwise null), all required counts,
function metadata, all omissions, and validation status. Failed parity writes
a failed report/status. A provider hash change during the build also fails.
Generator v1.1 normalizes source/debug compilation paths. Two fresh Job
Simulator builds in different directories produced byte-identical binaries
and manifests. `build_identity` records toolchain, API, proxy SHA256, generator
version and input-source fingerprint. Its `cache_key` includes provider SHA256,
toolchain, API and source fingerprint. A future managed cache should store each
complete immutable directory under that key and reverify it before reuse;
automatic caching or installation is not enabled here.

Static verification independently re-inspects the provider and proxy. It
compares exact public names, function type, GLOBAL/WEAK binding, and visibility;
rejects additional public functions and all public non-functions; and checks
AArch64 ELF64 little endian, Android API 21 note, `libsteam_api.so` SONAME,
16 KiB PT_LOAD alignment/congruence, SysV hash, RELRO, eager binding,
non-executable stack, and absence of TLS/TEXTREL or writable executable loads.
It decodes every linked stub and checks its exact slot address and relative
fail-closed initializer, including slots spanning pages. There are **zero**
public internal function exceptions. Recheck an existing build:

```bash
python3 tools/android-steam-proxy/verify_target_proxy.py \
  --provider ~/creamlinux-jobsimulator-cli/libsteam_api.so \
  --proxy tools/android-steam-proxy/build/jobsimulator-target/libsteam_api.so \
  --readelf /usr/bin/llvm-readelf \
  --report tools/android-steam-proxy/build/jobsimulator-target/function-parity-recheck.json
```

## Validated local captures

| Result | Job Simulator | Walkabout |
| --- | ---: | ---: |
| Provider public exports | 1365 | 1049 |
| Provider/proxy target functions | 1156 / 1156 | 1045 / 1045 |
| GLOBAL functions | 1135 | 1045 |
| WEAK functions | 21 | 0 |
| Binding/visibility mismatches | 0 / 0 | 0 / 0 |
| Missing/extra functions | 0 / 0 | 0 / 0 |
| Omitted non-functions | 209 | 4 |
| Exact name parity / all static ABI checks | passed | passed |
| Runtime / Steam Frame | exact function harness passed; real calls unvalidated | new target build unvalidated/limited |

Job Simulator SHA256:
`345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700`.
Walkabout SHA256:
`f424277c8a431542b93bf71215615fa6730edb7968a03f5230d484437f0d4aa4`.

Local artifacts are under `build/jobsimulator-target/` and
`build/walkabout-target/`. They are ignored by git; real providers/APKs are not
added to the repository. Walkabout's existing hardware results apply to the
previous fixed proxy; no new Walkabout target hardware result is claimed.
Job Simulator's measured target hardware results are recorded separately in
[JOBSIMULATOR_HARDWARE.md](JOBSIMULATOR_HARDWARE.md).

## Mock ABI and loader validation

`tests/run_target_abi.py` reuses the 17 signatures in `src/mock.c` and the
existing `tests/abi_test.c`. A generated mock provider has the **exact target
function names and bindings**. Signature cases occupy 17 GLOBAL slots; all
remaining slots use integer mock pads, including every WEAK slot. These are
mock implementations even when their exported names resemble Steam APIs.
The real provider is never loaded or called.

The Android shared mock passes the same static verifier. The NDK-built static
executable namespaces its trampoline labels so bionic's own C++ runtime
startup cannot interpose through uninitialized test slots before `main`.
Instruction shape and binding are unchanged. The test covers integer/stack
arguments, v0–v7, vector arguments/returns, indirect x8 return, aggregates,
variadic arguments, callbacks, every table slot, and 10000 repeated calls.

Measured Job Simulator mock result: **11156 assertions pass** (17 signature
cases, 1139 slot probes, 10000 repeated calls), and an uninitialized slot exits
127. The host lacks `/system/bin/linker64`; **Android dynamic execution did
not run**. A supplemental AArch64 glibc build of the same sources/stubs passes
11156 dynamic assertions, resolves all 1156 mock symbols, and rejects seven
loader failure cases: unset path, relative path, missing file, self-load,
missing functions, dependency-owned functions, and a missing WEAK function.
That result does not establish Android linker or Steam Frame behavior.

The passing logs/report are in
`build/jobsimulator-mock-validation/abi-verification.json`, with Android mock
parity in `mock-function-parity.json`. Reproduce with an available QEMU and
AArch64 glibc sysroot (use a fresh output each time). On this workstation:

```bash
poc_linux_root=/opt/unreal-engine/Engine/Extras/ThirdPartyNotUE/SDKs/HostLinux/Linux_x64/v26_clang-20.1.8-rockylinux8/aarch64-unknown-linux-gnueabi
python3 tools/android-steam-proxy/tests/run_target_abi.py \
  --manifest tools/android-steam-proxy/build/jobsimulator-target/manifest.json \
  --output tools/android-steam-proxy/build/jobsimulator-mock-next \
  --ndk /opt/android-ndk \
  --qemu "$PWD/tools/android-steam-proxy/build/validation-tools/qemu-aarch64" \
  --linux-cc /usr/bin/clang --linux-sysroot "$poc_linux_root" \
  --linux-gcc-install-dir "$poc_linux_root/lib/gcc/aarch64-unknown-linux-gnueabi/8.5.0"
```

The local QEMU copy comes from the already available pmbootstrap tools; nothing
was installed. On other machines, pass an available `qemu-aarch64` and a working
AArch64 Linux compiler/sysroot, or omit all `--linux-*` options for Android
static checks alone. A matching Android runtime root can be supplied with
`--android-sysroot` for QEMU dynamic mock checks. The built `run_android.sh`
is also ready for a separately authorized standalone Android mock test; it
includes the missing-weak rejection when that fixture exists.

The earlier generator checkpoint passed **128 tests** (the original 90 plus 38 new regressions),
with no skips on this workstation. Legacy real/mock names, stubs, headers and
export maps match the previous build byte-for-byte; the original 11047 static
ABI assertions also still pass.

Repeat Walkabout generation and run the full regression suite:

```bash
python3 tools/android-steam-proxy/generate_target_proxy.py \
  --provider ~/creamlinux-walkabout-cli/libsteam_api.so \
  --output tools/android-steam-proxy/build/walkabout-target-next \
  --readelf /usr/bin/llvm-readelf --ndk /opt/android-ndk
python3 -m unittest discover -s tools/android-steam-proxy/tests -p 'test_*.py'
git diff --check
```

The isolated [Job Simulator hardware bundle](JOBSIMULATOR_HARDWARE.md) now
provides a reproducible Android dynamic mock ABI stage, eight fail-closed loader
checks, four actual-Bionic weak-binding scopes, and a separate zero-call
real-provider resolution executable. Build and deployment commands are in that
document. All individual stages and the combined replay now passed on Steam
Frame for the exact recorded Job Simulator provider/proxy. Loading a provider
runs its ELF constructors; the resolver made zero Steam API calls. Consumer/game behavior,
computed lookups, omitted objects, and complete ABI compatibility remain
unvalidated. No installation/injection/game modification is part of these
commands.

## Explicit CLI artifact/evidence reporting

`compatibility.py files` and `live` accept `--target-proxy-dir`. The analyzer
checks provider SHA256, complete function/omission metadata and deterministic
generated sources, then independently rechecks the binary's surface/stubs/slots.
`--hardware-bundle` and `--hardware-results` must be supplied together with
that directory. Hardware evidence is never discovered implicitly or transferred
between different provider hashes.

The `target_specific_forwarding` object separates `generation_status`
(`not_generated`, `generated`, `locally_validated`, `hardware_validated`),
`local_validation_status`, `hardware_validation_status`, `binding_validation_status`,
`non_function_coverage` and `validation_evidence`. Local status currently means
static parity, not a dynamic mock run. `omitted-unrequired` means no requirement
was observed in the inspected consumers, with the existing runtime limitations.
The legacy `validated` boolean remains false because actual game behavior is
unvalidated. Fixed-proxy booleans and exits remain unchanged even when an exact
target proxy is hardware validated. Missing/mismatched/partial evidence returns
operational exit 2, never a downgraded compatibility conclusion.

The final measured Job Simulator evidence can be checked locally with:

```bash
python3 tools/android-steam-proxy/compatibility.py files \
  --steam-api ~/creamlinux-jobsimulator-cli/libsteam_api.so \
  --apk ~/creamlinux-jobsimulator-cli/apks/base.apk --abi arm64-v8a \
  --target-proxy-dir tools/android-steam-proxy/build/jobsimulator-target-final \
  --hardware-bundle tools/android-steam-proxy/build/jobsimulator-hardware-reproducible.tar.gz \
  --hardware-results tools/android-steam-proxy/build/frame-hardware-reproducible-2026-10-07 \
  --json
```

Expected exit remains **1**: `current_proxy.compatible=false` and target function
`generation_status=hardware_validated` describe different results.
