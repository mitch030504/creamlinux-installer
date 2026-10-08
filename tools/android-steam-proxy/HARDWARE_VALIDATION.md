# Completed Steam Frame validation

This records previously completed hardware testing reported by the project owner;
these tests were not rerun during the inspector integration.

Hardware: real Steam Frame, Valve Lepton. Standalone POC testing passed in both
`creamlinux-poc` and the real Walkabout context `steamlaunch-1408230`.

- Dynamic mock ABI: **11047 checks passed**.
- Static mock ABI: **11047 checks passed**.
- Six deliberate loader rejection cases passed.
- Real Walkabout original loaded; proxy resolved **1045 / 1045** function exports.
  That resolution test made zero Steam API calls.
- Omitted exports: `g_pSteamClientGameServer`, `__bss_start`, `_edata`, `_end`.

The original reference SHA-256 is
`f424277c8a431542b93bf71215615fa6730edb7968a03f5230d484437f0d4aa4`.

Actual typed function execution was then compared in the real
`steamlaunch-1408230` context:

| Function | Type | Direct original | Proxy → original | equal |
| --- | --- | --- | --- | --- |
| SteamAPI_IsSteamRunning | bool (*)(void) | false | false | true |
| SteamAPI_GetHSteamUser | int32_t (*)(void) | 0 | 0 | true |
| SteamAPI_GetHSteamPipe | int32_t (*)(void) | 0 | 0 | true |

Runner exit: **0**. These calls demonstrate execution through the generated
AArch64 trampolines. False/zero is expected for these separate, uninitialized
processes. No `SteamAPI_Init`, modifying Steam calls, DLC, entitlement,
inventory, achievement, or cloud calls were made. Walkabout was not modified.

The bundled NDK r30 `libc++_shared.so` produced a non-fatal linker warning:
`unused DT entry: unknown processor-specific (type 0x70000001 ...)`.
It did not prevent original/proxy loading, symbol resolution, or parity calls.

Read-only static Walkabout evidence: 15 ARM64 libraries scanned, 14 consumers;
none imported, relocated against, or contained a literal occurrence of
`g_pSteamClientGameServer`. None required the three omitted boundary symbols.
Computed runtime symbol lookups cannot be excluded.

## Limits and new inspector validation

This is bounded ABI, resolution, and three-call pre-initialization evidence,
not universal compatibility or initialized gameplay validation. Other originals,
games, runtime-only behavior, and computed `dlsym` names remain unproven.

The new inspector's host `lepton exec CONTEXT cat PATH` binary transfer still
needs real Frame validation (byte fidelity, permissions, large APK performance,
base/split coverage, host Python 3/LLVM availability, and Gamescope UI behavior).
Its analysis never loads the library or invokes Steam APIs. The existing
hardware results do not establish that this new integration has run on hardware.


## Read-only compatibility analysis: two captured games

The forwarding POC above remains validated on Walkabout hardware. The following
findings concern read-only analysis of captured provider/APK files, separately
from execution validation. The project owner also recorded a known-good live
Walkabout CLI result with these same counts; this analyzer update reran local
files mode, not live hardware tests. It did not install, inject, preload,
replace game files, call Steam APIs, or create a target-specific proxy.

| Result | Walkabout Mini Golf | Job Simulator |
| --- | --- | --- |
| Context / AppID | `steamlaunch-1408230` / 1408230 | `steamlaunch-448280` / 448280 |
| Package | `com.MightyCoconut.WalkaboutMiniGolf` | `com.owlchemylabs.jobsimulator` |
| Architecture / ABI | ARM64 / arm64-v8a | ARM64 / arm64-v8a |
| Public exports / functions / non-functions | 1,049 / 1,045 / 4 | 1,365 / 1,156 / 209 |
| Current manifest / supported intersection | 1,045 / 1,045 | 1,045 / 1,036 |
| Target-only functions / absent manifest targets | 0 / 0 | 120 / 9 |
| Consumer ELFs | 14 | 19 |
| Direct `DT_NEEDED libsteam_api.so` consumers | 0 | 0 |
| Normal Steam-named undefined dynamic symbols | 0 | 0 |
| Hard required unsupported exports | None | None |
| Current fixed proxy / files-mode exit | Compatible for observed static consumers / 0 | Incompatible / 1 |
| Target-specific forwarding | Candidate; not validated by this analysis | Inconclusive; not validated |

Job Simulator original SHA-256:
`345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700`.
The captured original is ELF64 AArch64, Android API 21, stripped, NDK r29
(14206865). It needs `libandroid.so`, `liblog.so`, `libdl.so`, and `libc.so`,
and does **not** need `libc++_shared.so`; it exports a substantial C++ runtime
surface itself.

The nine constructor targets absent from Job Simulator are exactly:

```text
SteamAPI_ISteamUtils_IsSteamRunningOnSteamDeck
SteamAPI_SteamApps_v008
SteamAPI_SteamGameServerNetworkingSockets_SteamAPI_v012
SteamAPI_SteamGameServerUtils_v010
SteamAPI_SteamInput_v006
SteamAPI_SteamMatchmakingServers_v002
SteamAPI_SteamNetworkingSockets_SteamAPI_v012
SteamAPI_SteamRemotePlay_v003
SteamAPI_SteamUtils_v010
```

Job Simulator exports newer variants (Apps v009, Input v007, Utils v011,
RemotePlay v004, MatchmakingServers v003, NetworkingSockets v013,
GameServerNetworkingSockets v013, GameServerUtils v011). Exact-name constructor
resolution still fails with the current fixed proxy. None of the nine old names
occurs in the captured `libil2cpp.so` exact-string set; that does not rescue the
fixed proxy or prove anything about runtime use of newer helper/interface exports.

The earlier analyzer's 19 hard C++ requirements were a provider-attribution
false positive. All 19 are also exported by the APK's packaged
`libc++_shared.so`, leaving zero after subtraction. The revised analyzer reports
the overlaps and alternate provider, never inferring the exact provider from
undefined-symbol overlap alone. Even a direct Steam dependency only supports a
bounded conservative requirement when no alternate packaged export is observed;
Android binding, system providers, and load scopes remain unknown.

Job Simulator packages 20 ARM64 libraries, including its provider, and none
needs `libsteam_api.so`. Its consumers have no normal Steam-named undefined
imports. `libil2cpp.so` contains `steam_api`, the
`com.rlabrecque.steamworks.net.dll` marker, hundreds of Steam entry-point strings,
and undefined `dlopen`/`dlsym` imports. `libgame.so` lacks comparable evidence.
This strongly suggests Steamworks.NET/IL2CPP PInvoke-style resolution; it does
not mathematically prove `dlsym` usage for any individual entry point. Walkabout's
captured `libil2cpp.so` also has this kind of runtime-resolution evidence.

The original Job Simulator string comparison found 927 Steam-related strings,
1,020/1,156 function-name matches and 105/120 target-only function matches.
The scanner's printable-string counter uses its documented filtering and can
count differently from an external `strings` command. Of the 105 target-only
matches, only 14 are SteamAPI names; C++ symbol/string-table matches must not be
counted as proven dynamic calls. The analyzer separates raw exact strings from
its own dynsym/symtab-excluded literal candidates. It also retains the 13 new
Steam-named provider exports with no raw exact match as possible exports, not
proven-unused functions.

All 1,156 ordinary function shapes can use AArch64 tail-call trampolines, but 21
weak function exports require a binding/interposition policy that the current
global-only generator does not implement. Together with 209 non-function
exports, this keeps the target-specific assessment **inconclusive**. No observed
consumer evidence requires those non-functions; absence of observed evidence
is not proof they are dispensable. Storage identity, TLS, aliases, symbol scopes,
runtime/computed lookup behavior, constructors, and initialized game behavior
remain separate validation questions. The current fixed proxy remains
**incompatible** regardless of future target-specific feasibility.

See [README.md](README.md#separate-compatibility-and-evidence-models) for the
additive JSON schema, confidence rules, exact commands, and test invocation.
Future hardware work would need a separately authorized target-specific design
and validation; none was generated or executed in this analysis milestone.
