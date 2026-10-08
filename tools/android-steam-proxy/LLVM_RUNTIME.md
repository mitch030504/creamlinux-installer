# ARM64 LLVM reader deployment decision and measured proof

Use **option A: bundle a compatible ARM64 LLVM reader**, with its own private
library directory. Keep LLVM's Android packed-relocation support and JSON
inspection rather than replacing it with a new embedded ELF parser. The existing
Rust backend embeds the Python analyzer/scanner/reference manifest and evidence
validator. `src-tauri/tauri.frame.conf.json` now includes the verified reader as
a resource. The backend selects its absolute launcher path automatically;
`CREAMLINUX_LLVM_READELF` remains an explicit override. The rebuilt AppImage
completed native Frame analysis; see [INSPECTOR_INTEGRATION.md](INSPECTOR_INTEGRATION.md)
for packaging checks, actual results and remaining interactive GUI validation.

The prepared runtime uses LLVM 20.1.8 from the official
[LLVM ARM64 package repository](https://apt.llvm.org/) and two pinned
[Ubuntu Noble ARM64 dependencies](https://ports.ubuntu.com/ubuntu-ports/).
`build_llvm_runtime.py` fetches packages only with `--download`, verifies fixed
SHA256 values, and copies only these selected regular payloads and copyrights:

```text
bin/llvm-readelf                 private launcher
libexec/llvm-readobj             AArch64 reader, ~1.8 MB
lib/libLLVM.so.20.1              ~139 MB
lib/libedit.so.2                ~265 KB
lib/libtinfo.so.6               ~265 KB
licenses/*-copyright
manifest.json
SHA256SUMS
```

It never installs packages, runs package scripts, or writes into a system
directory. It rejects occupied output directories and mismatched packages.
The launcher clears preload settings and replaces the library search path for
the reader subprocess only. No Wayland, XCB, GTK, or graphics library is in the
runtime bundle. All package versions, package hashes, payload hashes and license
files are retained. Pin changes require review and another native capability
and dependency check. This is a target-host-compatible dynamic bundle, not a
universal static executable.

Build on the workstation:

```bash
python3 tools/android-steam-proxy/build_llvm_runtime.py \
  --cache tools/android-steam-proxy/build/llvm-runtime \
  --output tools/android-steam-proxy/build/frame-llvm-runtime-next \
  --download
```

LLVM package payload inspection found `libedit.so.2`, while the Frame has
`libedit.so.0`; substituting those SONAMEs would be unsafe. Its terminfo dependency
was also absent, so the builder includes the matching `libedit.so.2` and
`libtinfo.so.6` privately. Both have regression coverage. Remaining direct host
dependencies include glibc >= 2.38, libstdc++ >= 13.1, libgcc, libffi.so.8,
libxml2.so.2, libz.so.1, libzstd.so.1, libbsd.so.0 and libmd.so.0. Host libxml2 also
pulls the host's ICU/lzma libraries. The Frame measured glibc 2.39 and resolved
the complete native dependency graph successfully. The eventual packaging
check must repeat this closure test against its supported SteamOS images.

## Actual Frame proof (2026-10-07)

The bundle and pure Python CLI were staged temporarily under
`/tmp/creamlinux-analyzer-runtime-2026-10-07/` on the **SteamOS host**. This separate
host directory is necessary because Linux/glibc LLVM does not execute inside
the Android/Bionic namespace. It is a host inspection tool experiment, separate
from all proxy experiments under `/data/local/tmp/creamlinux-target-proxy/`.
Transferred archive and payload checksums passed; LLVM reported 20.1.8; `ldd`
showed every dependency resolved. No immutable-host package installation occurred.

Native `compatibility.py live` used the real Lepton CLI, authoritative
`exec steamlaunch-448280 true`, `pm path`, package ABI/library discovery and
read-only copies. Job Simulator completed with **exit 1**, provider SHA256
`345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700`,
1365 public / 1156 function exports, 1036 fixed-proxy covered functions, no
required unsupported exports, and fixed-proxy `compatible=false`.

Native host `files` analysis of original VRChat, VAIL, Into Black and Dungeons
of Eternity APKs also completed with exit 1. Export coverage, every static
consumer record and runtime-resolution evidence matched workstation results
exactly. The actual consumer ELF/relocation evidence was decoded by LLVM, with
no GNU-readelf substitution or unsupported-relocation suppression.

Workstation evidence is retained at `build/llvm-runtime/`:
`frame-native-reader-console.txt`, `frame-live-jobsimulator.json`, and
`frame-live-jobsimulator.stderr` (empty). Additional native reports are in
`build/frame-game-discovery-2026-10-07/frame-native-reports.tar.gz`.

Reader selection is explicit `--readelf`, then `CREAMLINUX_LLVM_READELF`, then
an adjacent `runtime/bin/llvm-readelf`, then host PATH discovery. An explicitly
selected missing/broken reader fails closed; it never falls back silently to
another reader. The CLI capability probe still verifies its actual JSON
protocol before inspecting a game. Packaging additionally restores private
reader bytes after linuxdeploy's RPATH rewriting, then rechecks the pinned
payload hashes. The Frame verified all ten packaged checksum entries.
