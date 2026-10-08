# Standalone pre-initialization parity scope

The harness compares three typed calls to the original library with calls through
its generated proxy, in separate fresh standalone processes. It is a bounded
forwarding check, not initialized Steamworks or game compatibility validation.
The mock ABI suite, original loader probes, generated forwarding stubs, and
proxy implementation are unchanged.

## Selected functions and evidence

| Function | Pointer type used | Initialization dependency for this test |
| --- | --- | --- |
| `SteamAPI_IsSteamRunning` | `bool (*)(void)` | None in the pinned binary: returns constant false. |
| `SteamAPI_GetHSteamUser` | `int32_t (*)(void)` | None for reading the pinned binary's current handle; meaningful initialized user state is outside scope. |
| `SteamAPI_GetHSteamPipe` | `int32_t (*)(void)` | None for reading the pinned binary's current handle; meaningful initialized pipe state is outside scope. |

Declarations were checked in Valve's
[`steam_api.h`](https://raw.githubusercontent.com/ValveSoftware/source-sdk-2013/master/src/public/steam/steam_api.h)
and [`steam_api_internal.h`](https://raw.githubusercontent.com/ValveSoftware/source-sdk-2013/master/src/public/steam/steam_api_internal.h).
[`steam_api_common.h`](https://raw.githubusercontent.com/ValveSoftware/source-sdk-2013/master/src/public/steam/steam_api_common.h)
defines both handles as `int32`. These are no-argument C linkage functions; the
Android ARM64 build uses the platform ABI, with a one-byte C `bool` and signed
32-bit handle types. The harness has compile-time size checks and separate typed
function pointers. It does not call a generic untyped function dispatcher.

The SDK header's general guidance requires initialization before API use. It is
not a blanket guarantee that arbitrary exports or SDK versions are safe before
initialization. Our narrower decision is supported by the complete function
bodies in this **specific** original, SHA-256:

```text
f424277c8a431542b93bf71215615fa6730edb7968a03f5230d484437f0d4aa4
```

```asm
SteamAPI_IsSteamRunning:  // VA 0x25ad4, size 8
    mov w0, wzr
    ret
SteamAPI_GetHSteamUser:   // VA 0x23cec, size 12
    adrp x8, 0x2e000
    ldr w0, [x8, #0x4bc]
    ret
SteamAPI_GetHSteamPipe:   // VA 0x23ce0, size 12
    adrp x8, 0x2e000
    ldr w0, [x8, #0x4b8]
    ret
```

Both words lie in mapped `.bss` in the original. There are no branches to helper
functions, pointer dereferences through interfaces, or writes in these bodies.
`tests/verify_parity.py` checks the full file hash, symbol types/addresses/sizes,
exact instruction bytes and `.bss` locations on each build. It emits the bounded
disassembly and static verification JSON into `build/parity/`. That evidence does
not apply to any other original library version.

`SteamAPI_Init`, `SteamAPI_Shutdown`, and callbacks are never resolved or called
by the harness. It has no option to add arbitrary function names. It explicitly
excludes `BIsDlcInstalled`, DLC enumeration, inventory, licenses/entitlements,
achievements, stats writes, UGC writes, cloud writes, install/uninstall functions,
and `SteamAPI_RestartAppIfNecessary`. The **unchanged proxy constructor** still
resolves its existing 1,045 function targets to initialize forwarding slots; mere
resolution does not invoke any of those functions. Only the three allowlisted
targets are invoked by this test. Loading runs ELF constructors as in the
previous loader probe. Successful harness termination uses `_exit` after flushing
its result, avoiding library finalizers; it never explicitly unloads a library.

## Execution and comparison

Use `run_parity.sh` on the staged bundle, as documented in [FRAME.md](FRAME.md).
It verifies all bundle hashes and the pinned original checksum before either
mode, uses only the bundle's C++ runtime in `LD_LIBRARY_PATH`, and hashes the
original again afterward. It makes no app-ID file, Java/JNI setup, Steam identity
or game process configuration. Results go into a newly created directory; an
existing directory is rejected to prevent stale records. Both modes inherit the
same development context and run sequentially in fresh processes.

The low-level executable accepts exactly:

```text
parity_probe direct /absolute/original.so
parity_probe proxy /absolute/proxy.so /absolute/original.so
```

Use the runner for the reviewed real library: the low-level executable alone
checks paths, identities, and symbol ownership, but does not independently hash
the library or enforce a particular original version. In direct mode it clears
an inherited proxy-original setting; in proxy mode it replaces it with the
explicit original path. Both reject nonempty `LD_PRELOAD`. All three names are
resolved and their owning library validated before any call. The unchanged
proxy constructor separately validates that its targets belong to the exact
explicit original. Handles and false values are recorded, never interpreted as
API failure by this harness.

Each process emits one `PARITY_JSON` success record with mode, original file
identity, loaded library identity, `steam_api_init_called:false`, and typed
results. stderr marks the loader step and each call before invocation. A
15-second alarm bounds loading and calls; a crash, timeout, missing symbol,
constructor exit 127, missing result, or nonzero exit is **inconclusive**, never a
matching false/zero result. The runner stops after a failed direct run and does
not attempt proxy calls. Preserve both stderr and exit-code files.

`compare_parity.py RESULTS` checks exit codes, one complete record per mode,
allowlist, value types, original identity and the recorded reference/before/after
hashes. It emits JSON rows containing `function`, `direct`, `proxy`, and `equal`.
Its exit codes are 0 for all equal, 1 for a value mismatch, and 2 for invalid or
incomplete evidence (`parity:null`). Two equal errors are not parity. The saved
checksum records are provenance from the runner, not signatures against tampered
logs. Keep the bundle and results together.

## Meaning and stopping point

Expected observations are false for `IsSteamRunning` and normally zero current
user/pipe handles without initialization. **The success criterion is equality,
not true or nonzero.** In this original, `IsSteamRunning` is a constant-return
stub, so false does not even diagnose whether Steam is running.

For meaningful user/pipe interface work, an initialized Steam API connection and
valid process-local handles are missing: this standalone harness deliberately
never calls initialization. Valve documents additional initialization prerequisites
in the [API reference](https://partner.steamgames.com/doc/api/steam_api#SteamAPI_Init),
but this test does not establish which are available in a particular Lepton dev
context. No authorized game launch identity, Android Java/JNI state, or Steam
setup is fabricated. If loading fails, the complete `dlerror` records the actual
missing library/namespace dependency; if a call fails or hangs, its last stderr
marker identifies the stage. Stop there. Do not compensate by creating
`steam_appid.txt`, setting a game's App ID, joining its context, initializing
Steam, or modifying installed packages.

No real parity result is claimed by a host build. Completed hardware parity,
ABI, and resolution results are recorded separately in
[HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md). No installed Walkabout files are read or modified by this harness.
