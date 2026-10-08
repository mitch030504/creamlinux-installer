# Job Simulator isolated Steam Frame validation bundle

## Measured Steam Frame/Bionic result (2026-10-07)

The individual `mock`, `weak`, `resolve`, then combined `all` stages **passed**
in `creamlinux-poc`, Android 11 / API 30, arm64-v8a, kernel
`6.18.0-ge66bc2ca6f8c`, Lepton v2.8.14 / rootfs v2.8.11.

| Check | Actual result |
| --- | --- |
| Mock targets / ABI assertions | 1156/1156 / 11156/11156 |
| Fail-closed loader cases | 8/8, each exit 127 with expected diagnostic |
| Final proxy bindings | 1135 GLOBAL / 21 WEAK; exact visibility |
| Bionic weak/load-scope fixtures | 4/4; 420 checks |
| Copied real provider resolution | 1156/1156; failures=0 |
| Steam API calls by resolution probe | 0 |
| Production game files modified / processes injected | 0 / 0 |
| Independent stages / combined replay | all exit 0 |

Both the original prepared proxy (`f3bb48da…`) and the proxy rebuilt with
reproducible debug paths passed every stage. The final measured identities are:

- Provider: `345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700`.
- Proxy: `d14dbef4969e32e90564cc15af6b76cc951062629fb415cc2b211d8776eac0e7`.
- Bundle: `fc8614af167df51b85ec61fe88002845d9a24be11686b65a59543a111e58b3ed`.

Complete final logs, all 1156 resolution records, transferred metadata and
checksums are retained in `build/frame-hardware-reproducible-2026-10-07/`:
`mock-console.log`, `weak-console.log`, `resolve-console.log`, `all-console.log`,
`results.tar.gz`, and `observation.json`. The separate analyzer evidence importer
checks the exact bundle, provider/proxy identity, log hashes, stage exits,
counts, bindings, diagnostics and resolution-name set. Bundle/generator
manifests intentionally remain build records with `not_run`/`unvalidated`;
only explicit verified run evidence upgrades CLI status. These are operator
observations, not cryptographic attestations of the device.

This validates the **function-only mock forwarding harness and zero-call
provider resolution**. No real Steam function forwarding or gameplay was
tested; 209 non-function exports remain omitted. `dlopen` executes ELF
constructors: zero Steam API calls by the probe does not mean zero code
execution. Job Simulator's fixed proxy remains incompatible / CLI exit 1.
See [VALIDATION_STATUS.md](VALIDATION_STATUS.md) for multi-game and CLI results.

## Initial workstation recheck and access attempt (resolved)

The full workstation suite passed **153 tests, zero skips**. `git diff --check`
and runner shell syntax checks passed. Rebuilding with `/opt/android-ndk` and
`/usr/bin/llvm-readelf` reproduced the archive SHA256
`b50fb068f2381f5624983031bad7dc6241ebf5764b1f4fd83917444e3c8ed9be`
and proxy SHA256
`f3bb48da77fdd5cd51476086760c6831c2c19e42592c5faf9061a31eff967f8d`.
All 18 regular archive members and all internal checksums were verified.
Independent static parity rechecks passed for Job Simulator (1156 functions,
21 WEAK) and Walkabout (1045 functions, zero WEAK), with zero binding
mismatches. The existing fixed-proxy static mock passed 11047 ABI assertions;
its uninitialized-slot process exited 127 as expected.

The Frame SSH endpoint `steamos@192.168.8.192` responded, but noninteractive
authentication failed with `Permission denied (publickey,password)`.
`/tmp/creamlinux-live-lepton` was absent, no reusable SSH control socket was
found, and the available GPG SSH agent reported no identities. The user then
opened an authenticated shared SSH control connection. The wrapper was safely
recreated. `lepton start creamlinux-poc` initially failed because direct SSH
execution made Lepton's process-group setup fail; launching it as a child of a
shell resolved this, without modifying Lepton. No proxy implementation failure
was discovered on hardware. See the measured results above.

This bundle is for **isolated Android/Bionic hardware execution**.
Use the dedicated `creamlinux-poc` Lepton context.
Do not use `steamlaunch-448280` or any production game context. These commands
do not start or stop contexts: `creamlinux-poc` must already be running.
No ADB is required. No APK, installed library, Steam game file, `/data/app`,
or production-context changes are part of this procedure. Every Android test
file, copied provider and log stays under
`/data/local/tmp/creamlinux-target-proxy/`.

## Build on the workstation

From the repository root, using the existing generated target directory:

```bash
python3 tools/android-steam-proxy/build_hardware_bundle.py \
  --target-dir tools/android-steam-proxy/build/jobsimulator-target \
  --ndk /opt/android-ndk --readelf /usr/bin/llvm-readelf \
  --output tools/android-steam-proxy/build/jobsimulator-hardware-validation.tar.gz
python3 -m unittest discover -s tools/android-steam-proxy/tests -p 'test_*.py'
git diff --check
```

The builder needs the target `manifest.json` and generated `libsteam_api.so`,
the Android NDK, and LLVM readelf. It never loads a provider. It preserves the
actual generated proxy bytes, statically verifies proxy/mock parity and every
tail stub/slot, and constructs fresh controlled fixtures. The real provider is
neither needed nor included. Outputs are the archive and its `.tar.gz.sha256`
sidecar. Build output remains ignored by Git. Fixed inputs/toolchain produce
byte-identical archives: sorted members, fixed ownership/modes/timestamps and
a gzip header without a filename or timestamp.

The archive contains exactly:

```text
SHA256SUMS
manifest.json
target-functions.tsv
mock-parity.json
libsteam_api.so
abi_test
mock_load_probe
binding_probe
weak_probe
resolve_probe
run_hardware_validation.sh
mock/libmock_original.so
mock/libempty.so
mock/libdependency.so
mock/libbroken_dependency.so
mock/libmissing_weak.so
weak/libstrong.so
weak/libconsumer.so
```

There is no static ABI executable, glibc executable, Android runtime copy,
game file, real provider, or extra library dependency in the bundle.

## Stage designs and scope

`mock` uses the **actual generated Job Simulator proxy** and an NDK-built
controlled original with the exact 1,156 function names/bindings/visibility.
The existing `abi_test.c` logic dynamically loads the proxy with Bionic's
`/system/bin/linker64`. The unchanged fail-closed constructor dynamically
loads the mock and pre-resolves every target, requiring same-file ownership.
The 17 typed mock signatures map to representative GLOBAL names; the other
1,139 names are controlled pad functions, including every WEAK name. Real
Steam prototypes are irrelevant to these mock-only signatures.

Expect 11,156 assertions: 17 typed cases, 1,139 pad probes and 10,000 repeated
stack-argument calls. This covers every slot plus integer registers, SIMD/vector
registers, stack arguments, mixed arguments, scalar/pointer/aggregate returns,
hidden structure-return pointers, variadic arguments and callbacks. Eight
separate rejection processes must exit **127** with the expected diagnostic:
missing configuration, unsafe relative path, nonexistent provider, self-load,
missing required target, target found only in a dependency, missing ELF
dependency, and missing WEAK target. The dependency-only fixture contains a
valid `DT_NEEDED` mock; the broken dependency fixture needs
`libhardware_absent.so`, which is intentionally absent from the bundle.

`weak` first reads the transferred proxy's final ELF dynsym on Android using
`binding_probe`, requiring **21 WEAK FUNC and 1,135 GLOBAL FUNC**, exact names,
types and visibility, with no extra public definitions. It then launches four
independent Bionic test processes. A controlled strong library defines all 21
weak names as GLOBAL, with distinct return values and `DF_1_GLOBAL` (`-z global`).
A consumer has strong undefined references to all 21 names and a
`DT_NEEDED libsteam_api.so`; its calls and address relocations are bound with
`RTLD_NOW`:

| Process | Load order | Expected consumer binding |
| --- | --- | --- |
| baseline | proxy, consumer | proxy WEAK definitions |
| strong-first | strong global, proxy, consumer | strong global definitions |
| strong-middle | proxy, strong global, consumer | strong global definitions |
| strong-late | proxy, consumer, strong global | existing proxy bindings retained |

Each process checks all 21 relocated addresses and call results. Explicit
`dlsym(proxy_handle, name)` and `dlsym(mock_handle, name)` must still reach
their respective definitions; both calls must return the controlled mock
value, and their addresses must differ. This is **105 checks per process,
420 total**. It proves override in the controlled global-before-local scope,
not that runtime lookup always prefers a strong definition over an earlier
weak definition in an arbitrary search order.

Android documents the global-before-local relocation groups (API 23+) in
[Android linker changes for NDK developers](https://android.git.googlesource.com/platform/bionic/%2B/HEAD/android-changes-for-ndk-developers.md).
The [Bionic explicit-handle lookup implementation](https://android.googlesource.com/platform/bionic/%2B/d3e7d088453e089b3d625b0864ccdf3c74893f18/linker/linker.cpp)
searches the handle and its dependency tree. These documented rules motivate
the assertions; the **actual Steam Frame results must establish them on the
installed Bionic runtime**. No glibc result establishes this stage. The fixture
names include C++ allocation/deallocation and emulated-TLS exports, but only
controlled C mock bodies execute, with no C++ test runtime linked.

Loader policy remains unchanged: every target, including every WEAK function,
must exist in the explicitly configured original. Proxy-owned slots are
populated from that handle and checked for same-file ownership. Binding on a
consumer relocation and choosing a proxy's original target are different
operations. Missing WEAK exports remain fatal; no global fallback is added.

`resolve` is a separate executable that **loads only the copied real provider**,
then performs `dlsym` for all 1,156 generated target names. It prints each
non-null address and verifies its `dladdr` owner has the provider's device/inode.
It never casts a resolved address to a function pointer or invokes it. No
Steam API initialization, callbacks, interfaces, DLC, entitlement, inventory,
achievement/stat, cloud, UGC, or other Steam target calls occur in probe logic.
It does not load the proxy, inspect provider data, or use `LD_PRELOAD`.
After flushing output it uses `_exit`, avoiding unload and process-exit
destructors. **`dlopen` still executes provider/dependency ELF constructors**;
their internal behavior is outside the zero-explicit-API-call claim.

## Runner and checksums

Inside the test directory:

```sh
./run_hardware_validation.sh mock
./run_hardware_validation.sh weak
./run_hardware_validation.sh resolve /data/local/tmp/creamlinux-target-proxy/original-provider.so
./run_hardware_validation.sh all /data/local/tmp/creamlinux-target-proxy/original-provider.so
```

Each stage independently verifies **all** bundled files against `SHA256SUMS`
before launching test binaries. Missing files, bad hashes, symlink members,
paths outside the test directory and failed test processes return nonzero.
The runner replaces inherited library-search paths with its own bundle paths
and clears inherited `LD_PRELOAD`/original-provider settings. Each mock,
loader case and weak scope uses a new standalone process. The log directory
and existing log files may not be symlinks. No stage injects into a game.

The manifest records the generated proxy SHA256, counts, toolchain and the
required real-provider SHA256:

```text
345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700
```

`resolve` and `all` reject a mismatching real provider before running any
test stage. A deliberately explicit development-only override is
`CREAMLINUX_ALLOW_PROVIDER_SHA_MISMATCH=1`; it prints and records the actual hash
as `DEVELOPMENT OVERRIDE`. It relaxes only that hash check, not path isolation,
bundle checksums, ownership checks or target counts. A run with this override
is not validation of the captured Job Simulator provider.

## Exact host deployment with Lepton exec

Run these commands **on the Steam Frame host** in Bash. First transfer the
workstation-built archive and its sidecar to a convenient host location
(for example the repository's `tools/android-steam-proxy/build/`). The host
also needs your already captured provider at
`$HOME/creamlinux-jobsimulator-cli/libsteam_api.so`. No command reads an installed
game or `/data/app`. If you use a host wrapper, replace the `lepton_exec`
function body with your wrapper's `exec creamlinux-poc "$@"` invocation.

```bash
set -euo pipefail
lepton_exec() {
  /home/steamos/.local/share/Steam/steamapps/common/Lepton/lepton exec creamlinux-poc "$@"
}
bundle="$PWD/tools/android-steam-proxy/build/jobsimulator-hardware-validation.tar.gz"
provider="$HOME/creamlinux-jobsimulator-cli/libsteam_api.so"
host_logs="$PWD/tools/android-steam-proxy/build/frame-hardware-results"
mkdir -p "$host_logs"

# Test-context availability only. No start/stop commands.
lepton_exec true
(cd "$(dirname "$bundle")" && sha256sum -c "$(basename "$bundle").sha256")
archive_sha=$(sha256sum "$bundle")
archive_sha=${archive_sha%% *}

# Require a fresh/empty test directory; use the cleanup below before a repeat.
lepton_exec sh -c '
  set -eu
  base=/data/local/tmp/creamlinux-target-proxy
  [ ! -L "$base" ]
  if [ -e "$base" ]; then
    [ -d "$base" ] && [ -z "$(ls -A "$base")" ]
  fi
  umask 077
  mkdir -p "$base"
  [ "$(readlink -f "$base")" = "$base" ]
'

# Binary stdin transfer. No terminal allocation; cat preserves bytes.
lepton_exec sh -c 'umask 077; cat > /data/local/tmp/creamlinux-target-proxy/validation-bundle.tar.gz' < "$bundle"

# Verify the archive against the hash computed on the host, then extract.
lepton_exec sh -c '
  set -eu
  cd /data/local/tmp/creamlinux-target-proxy
  printf "%s  validation-bundle.tar.gz\n" "$1" | sha256sum -c -
  tar -xzf validation-bundle.tar.gz
  sha256sum -c SHA256SUMS
  chmod 755 run_hardware_validation.sh abi_test mock_load_probe binding_probe weak_probe resolve_probe
' sh "$archive_sha"

# Run the two mock-only stages independently.
lepton_exec sh -c 'cd /data/local/tmp/creamlinux-target-proxy && ./run_hardware_validation.sh mock' 2>&1 | tee "$host_logs/mock-console.log"
lepton_exec sh -c 'cd /data/local/tmp/creamlinux-target-proxy && ./run_hardware_validation.sh weak' 2>&1 | tee "$host_logs/weak-console.log"

# Check the user's capture locally, then copy to a NEUTRAL Android filename.
printf '%s  %s\n' 345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700 "$provider" | sha256sum -c -
lepton_exec sh -c 'umask 077; cat > /data/local/tmp/creamlinux-target-proxy/original-provider.so' < "$provider"

# Resolution only. The runner checks the transferred provider hash again.
lepton_exec sh -c 'cd /data/local/tmp/creamlinux-target-proxy && ./run_hardware_validation.sh resolve /data/local/tmp/creamlinux-target-proxy/original-provider.so' 2>&1 | tee "$host_logs/resolve-console.log"

# Optional combined run, with the same provider guard and zero-call resolve.
lepton_exec sh -c 'cd /data/local/tmp/creamlinux-target-proxy && ./run_hardware_validation.sh all /data/local/tmp/creamlinux-target-proxy/original-provider.so' 2>&1 | tee "$host_logs/all-console.log"

# Collect logs/manifests without copying the real provider back into an artifact.
lepton_exec sh -c 'cd /data/local/tmp/creamlinux-target-proxy && tar -czf - logs manifest.json SHA256SUMS target-functions.tsv mock-parity.json' > "$host_logs/results.tar.gz"
tar -tzf "$host_logs/results.tar.gz"

# After collecting results: remove only this isolated test directory.
lepton_exec sh -c 'rm -rf /data/local/tmp/creamlinux-target-proxy'
```

Android must provide `sh`, `cat`, `tar`, `sha256sum`, `readlink`, `grep`, `tee`,
`mkdir` and `chmod` (normally Toybox tools). The bundle brings all test binaries;
no Android LLVM or Python installation is required. The Lepton wrapper must
forward stdin/stdout as binary pipes and preserve the remote exit status.
If stdin transfer is unsupported by a wrapper, use another existing Lepton
file-transfer mechanism to the same isolated paths and retain both checksum
checks. Do not switch to a production context to work around access failures.

## Expected summaries and remaining evidence

The detailed logs include loader diagnostics and all real-provider resolution
addresses. Console summaries for a passing `all` run include:

```text
PASS bundle checksums
PASS real-provider checksum: 345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700
PASS 11156 ABI checks (17 signature cases, 1139 slot probes, 10000 repeated calls)
PASS missing_env (exit 127)
PASS relative_path (exit 127)
PASS nonexistent (exit 127)
PASS self_load (exit 127)
PASS missing_symbols (exit 127)
PASS dependency_target (exit 127)
PASS dependency_failure (exit 127)
PASS missing_weak (exit 127)
PASS mock: 1156 targets; 11156 ABI checks; 8 loader rejections
PASS dynsym: 1135 GLOBAL, 21 WEAK FUNC; exact final-link bindings/visibility
PASS weak baseline: 21/21 symbols; 105 checks; explicit handles retain mock targets
PASS weak strong-first: 21/21 symbols; 105 checks; explicit handles retain mock targets
PASS weak strong-middle: 21/21 symbols; 105 checks; explicit handles retain mock targets
PASS weak strong-late: 21/21 symbols; 105 checks; explicit handles retain mock targets
PASS weak: 21 WEAK, 1135 GLOBAL; 4 Bionic load-scope cases; 420 checks
PASS resolve: 1156/1156 targets; failures=0; zero Steam API calls
PASS hardware stage=all (logs: /data/local/tmp/creamlinux-target-proxy/logs)
```

These summaries were observed in the completed Steam Frame run above.
Lepton binary stdin transfer, namespace accessibility, Android tool availability
and captured-provider dependency loading also succeeded. Host unit tests stub
stage executables only to check orchestration; the real Bionic results come
from the separate hardware run. The passing run does not validate gameplay,
initialization, real function calls,
the 209 omitted non-function exports, or arbitrary game load scopes.
