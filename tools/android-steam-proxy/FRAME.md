# Standalone Steam Frame / Lepton tests

These commands only stage a POC under `/data/local/tmp` and run standalone test
processes. They do not launch, replace files in, inject into, or configure Walkabout.
Use an **already-running development/test Lepton context**. If none is running,
stop; this procedure intentionally does not start a game context. No device
commands were executed during the local build.

## 1. Transfer from this build host

Run from the repository root. Supply your Frame's normal SSH destination at the
prompt (for example your configured SSH host alias). This transfers the bundle
only; it does not execute it.

```bash
./tools/android-steam-proxy/package.sh
read -r -p 'Steam Frame SSH destination: ' frame_host
scp tools/android-steam-proxy/build/android-steam-proxy-poc.tar.gz "$frame_host:~/android-steam-proxy-poc.tar.gz"
```

## 2. On the Steam Frame desktop terminal

The default Lepton path below matches the repository's existing discovery code.
If your Steam library is elsewhere, set `LEPTON_CLI` to its actual `lepton` path.
`lepton ps` gives the available contexts and their ADB endpoints; do not assume a
port or select the Walkabout context. The context and ADB endpoint prompts must
refer to the same existing development/test container.

```bash
set -e
lepton_cli=${LEPTON_CLI:-"$HOME/.local/share/Steam/steamapps/common/Lepton/lepton"}
"$lepton_cli" ps
read -r -p 'Already-running development/test context name: ' poc_context
"$lepton_cli" exec "$poc_context" true
"$lepton_cli" exec "$poc_context" getprop ro.product.cpu.abi
read -r -p 'ADB endpoint for that same context (IP:port): ' poc_adb
adb connect "$poc_adb"
adb -s "$poc_adb" shell getprop ro.product.cpu.abi
# Both ABI outputs must be arm64-v8a.
test "$(adb -s "$poc_adb" shell getprop ro.product.cpu.abi | tr -d '\r')" = arm64-v8a
poc_dir="/data/local/tmp/steam-api-forward-poc-$(date +%Y%m%d-%H%M%S)-$$"
adb -s "$poc_adb" shell mkdir -p "$poc_dir"
adb -s "$poc_adb" push "$HOME/android-steam-proxy-poc.tar.gz" "$poc_dir/bundle.tar.gz"
adb -s "$poc_adb" shell "cd '$poc_dir' && tar -xzf bundle.tar.gz && sha256sum -c SHA256SUMS"
adb -s "$poc_adb" shell "cd '$poc_dir' && chmod 700 abi_test abi_static load_probe mock_load_probe && sh ./run_android.sh"
```

Expected: 11,047 checks from the dynamic mock executable, the same 11,047 from the
static executable, and six deliberate initialization failures each recognized by
exit **127** plus its diagnostic. `run_android.sh` returns zero only if all pass.
It writes the six failure logs inside the POC directory. Do not treat the expected
127 diagnostics alone as a suite failure.

## 3. Real export loader test (no Steam API function calls)

Run only after the mock suite passes, in the same Frame terminal. The original is
a renamed **byte-identical reference copy**, not an installed game library.
`dlopen` necessarily executes any library constructors; the probe only resolves
symbols after loading and prints the original data address without dereferencing
or writing it. It does not call `SteamAPI_Init` or any other Steam interface.

```bash
adb -s "$poc_adb" shell "cd '$poc_dir' && echo 'f424277c8a431542b93bf71215615fa6730edb7968a03f5230d484437f0d4aa4  real/libsteam_api_original.so' | sha256sum -c -"
adb -s "$poc_adb" shell "env LD_LIBRARY_PATH='$poc_dir/runtime' '$poc_dir/load_probe' '$poc_dir/real/libsteam_api.so' '$poc_dir/real/libsteam_api_original.so'"
```

Expected successful output: `resolved 1045 functions`, four `proxy lookup ...:
absent` lines, and `PASS resolved 1045 proxy functions; zero Steam API calls`.
This is a loader/resolution test, **not** a test of actual Steam function behavior.

The bundle provides the r30 ARM64 `libc++_shared.so` for a standalone namespace.
Its compatibility with this r21-built reference is unproven until this test runs.
Android must provide `libandroid.so`, `liblog.so`, `libdl.so`, and `libc.so`.
If loading fails, retain the complete error; do not replace system/game runtimes,
change namespace configuration, preload the proxy, or patch the reference.
The original has 4 KiB segment alignment; the new artifacts have 16 KiB alignment.

Collect diagnostics without changing the game:

```bash
adb -s "$poc_adb" shell getprop ro.build.version.sdk
adb -s "$poc_adb" shell getconf PAGESIZE
adb -s "$poc_adb" pull "$poc_dir" ./steam-api-forward-poc-results
```

## 4. Optional read-only consumer evidence collection

If an already-running context actually contains Walkabout, these queries and
pulls read its package without launching or changing it. Do not start Walkabout
just to obtain these files. Use its ADB endpoint only for this evidence collection.

```bash
read -r -p 'ADB endpoint of an already-running context containing the package: ' scan_adb
adb connect "$scan_adb"
adb -s "$scan_adb" shell pm path com.MightyCoconut.WalkaboutMiniGolf
read -r -p 'Absolute base/split APK path from pm path, without package: prefix: ' scan_apk
mkdir -p ./walkabout-consumer-evidence
adb -s "$scan_adb" pull "$scan_apk" ./walkabout-consumer-evidence/
```

Repeat the pull for **every** base/split path returned by `pm path`, retaining all
APKs in the evidence directory. No game launch is needed. On a host with Python 3
and `llvm-readelf` (LLVM or the Android NDK), run from the repository root:

```bash
python3 tools/android-steam-proxy/tests/scan_consumers.py \
  ./walkabout-consumer-evidence > consumer-scan.json
```

Alternatively, supply explicit base/split paths (add every pulled split):

```bash
python3 tools/android-steam-proxy/tests/scan_consumers.py \
  ./walkabout-consumer-evidence/base.apk \
  ./walkabout-consumer-evidence/split_config.arm64_v8a.apk > consumer-scan.json
```

For an NDK reader outside PATH, add
`--readelf "$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf"`.
The scanner recurses into directories and APK/ZIP/APKS/XAPK members, inspecting
all embedded `.so` entries regardless of their directory. It never extracts into
the evidence directory or loads a library.

Print the target summary and any coverage errors:

```bash
python3 - <<'PYSCAN'
import json
with open('consumer-scan.json') as stream:
    report = json.load(stream)
print(json.dumps({
    'scan_complete': report['scan_complete'],
    'elf_files_scanned': report['elf_files_scanned'],
    'g_pSteamClientGameServer': report['summary']['g_pSteamClientGameServer'],
    'errors': report['errors'],
}, indent=2))
PYSCAN
```

Exit 2 or `scan_complete: false` means the scan is incomplete: inspect `errors`.
`statically_required: true` identifies a strong external ELF import/reference.
Weak imports are separately visible as linkage evidence but are not mandatory
provider requirements. Definitions (including the reference Steam API's own
definition and self relocation) and strings do not make this flag true. A false
result only applies to inspected inputs; missing splits and runtime lookups
remain outside that conclusion. Each evidence record names the containing APK
and native library. See [the JSON field details](README.md).

## 5. Standalone benign runtime parity (three pre-init calls)

This new test calls exactly `SteamAPI_IsSteamRunning`, `SteamAPI_GetHSteamUser`,
and `SteamAPI_GetHSteamPipe`, using verified types and the exact reviewed original.
It does not call `SteamAPI_Init`. The function bodies in this original permit
these pre-init reads; this does not generalize to other Steam API functions or
other originals. See [PARITY.md](PARITY.md) for signatures, disassembly, exclusions,
initialization dependencies, and limits. The existing mock and zero-call loader
suites above are unchanged. Their earlier hardware success does not constitute a
runtime result for this new harness.

Build and transfer **from this build host**, in the repository root:

```bash
./tools/android-steam-proxy/package-parity.sh
read -r -p 'Steam Frame SSH destination: ' frame_host
scp tools/android-steam-proxy/build/android-steam-proxy-parity-poc.tar.gz \
  "$frame_host:~/android-steam-proxy-parity-poc.tar.gz"
```

The package command expects the existing base artifacts from `build.sh`; on a
fresh checkout, run `./tools/android-steam-proxy/build.sh` and
`python3 tools/android-steam-proxy/tests/run_local.py` first. It builds an Android
API-21 ARM64 PIE executable with NDK r30, runs host-only fixture tests, checks the
exact original and its candidate instruction bytes, and verifies the existing
proxy ELF artifacts. It never runs the real library on the build host. The
original POC tarball remains available separately.

**On the Steam Frame desktop terminal**, stage a fresh disposable directory in
an already-running **development/test** Lepton context. Do not select a game
context or start a game to obtain one. If none exists, stop.

```bash
set -e
lepton_cli=${LEPTON_CLI:-"$HOME/.local/share/Steam/steamapps/common/Lepton/lepton"}
"$lepton_cli" ps
read -r -p 'Already-running development/test context name: ' parity_context
"$lepton_cli" exec "$parity_context" true
"$lepton_cli" exec "$parity_context" getprop ro.product.cpu.abi
read -r -p 'ADB endpoint for that same context (IP:port): ' parity_adb
adb connect "$parity_adb"
test "$(adb -s "$parity_adb" shell getprop ro.product.cpu.abi | tr -d '\r')" = arm64-v8a
parity_dir="/data/local/tmp/steam-api-parity-poc-$(date +%Y%m%d-%H%M%S)-$$"
adb -s "$parity_adb" shell mkdir -p "$parity_dir"
adb -s "$parity_adb" push "$HOME/android-steam-proxy-parity-poc.tar.gz" "$parity_dir/bundle.tar.gz"
adb -s "$parity_adb" shell "cd '$parity_dir' && tar -xzf bundle.tar.gz && sha256sum -c SHA256SUMS && chmod 700 parity_probe"
# Capture the status even on failure so logs can always be collected below.
set +e
adb -s "$parity_adb" shell "cd '$parity_dir' && sh ./run_parity.sh parity-results"
parity_status=$?
set -e
printf 'Android parity runner exit: %s\n' "$parity_status"
parity_local="$HOME/steam-api-parity-results-$(date +%Y%m%d-%H%M%S)-$$"
mkdir "$parity_local"
adb -s "$parity_adb" pull "$parity_dir/parity-results" "$parity_local/"
adb -s "$parity_adb" pull "$parity_dir/compare_parity.py" "$parity_local/"
set +e
python3 "$parity_local/compare_parity.py" "$parity_local/parity-results" > "$parity_local/parity.json"
compare_status=$?
set -e
cat "$parity_local/parity.json"
printf 'Comparator exit: %s; saved results: %s\n' "$compare_status" "$parity_local"
```

Each mode is a separate process. The runner pins the original hash, preserves
stdout/stderr/exit status, and stops on a failed mode. A nonzero runner status
means stop and inspect logs; comparison of partial data will be inconclusive.
Do not create app-ID files, initialize Steam, alter namespaces, substitute game
runtimes, set up JNI, or inject anything to obtain a different result.

Parity means: both processes exit 0, both records and original identities/hashes
validate, and all three rows report `equal:true` with top-level `parity:true`
(comparator exit 0). Matching false/zero values **pass**. A value mismatch exits 1;
a loader error, crash, timeout, missing record, or identity/hash discrepancy
exits 2 with `parity:null`. Expected low-information observations are false/0/0;
actual observations must come from the hardware run.

For additional read-only environment diagnostics after a failure:

```bash
adb -s "$parity_adb" shell getprop ro.build.version.sdk
adb -s "$parity_adb" shell getconf PAGESIZE
cat "$parity_local/parity-results/direct.stderr"
# Present only if the direct mode completed and proxy mode was attempted:
test ! -f "$parity_local/parity-results/proxy.stderr" || cat "$parity_local/parity-results/proxy.stderr"
```
