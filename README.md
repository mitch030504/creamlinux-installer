# CreamLinux — Steam Frame / Lepton fork

> [!IMPORTANT]
> **AI-assisted development notice**
>
> The Steam Frame/Lepton work in this fork has been developed with substantial assistance from AI tools, including **OpenAI Codex and ChatGPT**. AI has been used for code generation and modification, architecture research, debugging, test development, CI configuration, and documentation.
>
> **AI-generated or AI-assisted contributions may contain mistakes, security weaknesses, or unverified assumptions.** Passing automated tests or selected Steam Frame hardware checks does not constitute a complete security audit or guarantee functionality. Review the source, validate important behavior independently, and use experimental builds at your own risk.
>
> This disclosure applies to **work carried out in this fork**; it does not imply that the original upstream CreamLinux project was AI-generated.

> **Experimental, unofficial fork. Not a complete CreamLinux port for Steam Frame.**
>
> This fork extends [Novattz/CreamLinux](https://github.com/Novattz/creamlinux-installer) with research and tooling for Valve's **Steam Frame**, **SteamOS (Linux ARM64)**, and the **Lepton Android compatibility environment**. The Steam Frame-specific application currently operates as a **read-only compatibility inspector**. It does **not** install CreamAPI into Lepton games, enable DLC, replace a game's Steam API, or provide feature parity with the original Linux desktop installer.

**Project status (9 October 2026):** The Steam Frame test workflow has passed on GitHub Actions. A complete hosted AppImage release build is still being debugged; no public Frame release has been published. Previously built inspector artifacts and function-forwarding experiments have been tested on actual Steam Frame hardware, but those results must not be attributed to future builds without revalidation.

| Navigate | Link |
| --- | --- |
| **Current Steam Frame development source** | [`test/steam-frame-inspector-security-ci`](https://github.com/mitch030504/creamlinux-installer/tree/test/steam-frame-inspector-security-ci) |
| **Open development review** | [Draft PR #1](https://github.com/mitch030504/creamlinux-installer/pull/1) |
| **Hosted inspector tests** | [Latest verified passing test run](https://github.com/mitch030504/creamlinux-installer/actions/runs/37906375947) |
| **AppImage build validation** | [Release-validation workflow](https://github.com/mitch030504/creamlinux-installer/actions/workflows/steam-frame-release.yml) |
| **Original desktop project** | [Novattz/creamlinux-installer](https://github.com/Novattz/creamlinux-installer) |

## Which branch contains what?

- **`main` (the default branch):** original/inherited CreamLinux desktop source, this fork status README, and registration of the non-publishing Steam Frame CI workflows. **It is not the complete Steam Frame implementation.**
- **`test/steam-frame-inspector-security-ci`:** the actual Steam Frame inspector, Lepton backend integration, compatibility scanner, ARM64 function-forwarding research, pinned build infrastructure, regression tests, and technical documentation. **Use this branch to evaluate or contribute to the Frame work.**
- **Draft PR #1:** a development review, **not** an approved merge or a release. Workflow-registration differences have caused a merge conflict; the branch can still be tested by explicitly dispatching workflows.

## What is implemented?

The statuses below describe the **Steam Frame development branch**, except where explicitly labelled *inherited*. “Validated” describes the stated test scope, not general compatibility with all games.

| Component / capability | Status | Actual scope |
| --- | --- | --- |
| Original Linux desktop CreamLinux GUI and Steam/Proton/Epic integrations | **Inherited; not revalidated here** | Upstream desktop code remains available. Original workflows and supported environments should be checked against upstream documentation. |
| Steam Frame / Lepton game and package discovery | **Implemented and tested** | Inspects installed metadata through the Lepton CLI and validates relevant context identity without starting stopped games. |
| Read-only Steam API compatibility inspector | **Implemented and device-tested** | Analyzes the installed `libsteam_api.so` and native consumers in base/split APKs. Distinguishes compatible, incompatible, and incomplete results. |
| Native Steam Frame inspector GUI | **Implemented and device-tested** | Inspector window, analysis, evidence selection, refresh and close interactions; historical packaged UI validation covered 15/15 checks. |
| Host-side ARM64 ELF analysis | **Implemented and tested** | Uses a privately bundled, pinned LLVM 20.1.8 reader on SteamOS; handles supported Android ELF metadata without modifying packages. |
| Six-game static compatibility evidence | **Analyzed** | Walkabout Mini Golf, Job Simulator, VRChat, VAIL, Into Black, and Dungeons of Eternity. These are scoped ELF/APK analyses, **not** evidence of running modified games. |
| Android ARM64 Steam API **function forwarding** | **Experimental; hardware-validated in isolated tests** | Target-specific generator and fail-closed loader. Job Simulator's synthetic/mock test surface covered **1,156/1,156 functions** and **11,156 ABI assertions**, with controlled zero-call resolution checks. This is **not** complete Steam API or CreamAPI equivalence. |
| Generated proxy data/object exports | **Not implemented** | In particular, Job Simulator's provider exposes **209 non-function symbols** outside the current function-only approach. |
| Frozen ARM64 SDK, pinned toolchains, source/artifact provenance | **Implemented** | Locked SDK, LLVM/runtime and controller inputs, manifests, integrity checks and non-publishing release tooling. |
| GitHub-hosted Python, Rust and rendering tests | **Passing** | [Verified test run](https://github.com/mitch030504/creamlinux-installer/actions/runs/37906375947). Test results do not prove completed release packaging or device behavior for a new artifact. |
| Full GitHub-hosted ARM64 AppImage assembly | **In progress** | Compilation/packaging infrastructure is being repaired and measured. [Workflow runs](https://github.com/mitch030504/creamlinux-installer/actions/workflows/steam-frame-release.yml) show the current status. |
| Steam Frame installer, live game integration, CreamAPI port, DLC management | **Not implemented for Lepton** | No supported install/uninstall or activation flow; existing inspector actions remain read-only. |
| Production signing, public Frame releases and automatic updates | **Not available** | No production signing key or published Frame artifact. Legacy desktop release actions must not be used as Frame releases. |

### Important distinction: SteamOS host vs. Lepton Android

The inspector is a **Linux ARM64 application on the Steam Frame's SteamOS host**. It queries and reads information from games managed by **Lepton**, which provides an Android environment. It does not mean the Linux CreamLinux desktop application or CreamAPI has been ported to Android/Bionic.

The **Android ARM64 proxy generator** is a separate compatibility experiment. It forwards supported native functions to the original provider in controlled tests; it neither reproduces arbitrary ELF data-symbol semantics nor establishes reliable gameplay integration or Steam entitlement behavior.

A result such as **“Compatible for observed static consumers”** is limited to the inspected files and identified symbols. It is not a promise that a game will run with a proxy installed. In the documented captures, Walkabout meets that limited criterion for the fixed proxy; Job Simulator does not.

## What is not included / not yet supported?

- **No full CreamLinux or CreamAPI functionality on Steam Frame.** The upstream desktop capabilities must not be confused with Frame compatibility.
- **No installed-game patching, injection, or replacement** of Steam API libraries. Real production Lepton game contexts and their files are not altered by the inspector workflow.
- **No complete ABI parity.** Function forwarding alone does not preserve data-object identity, every linker-visible export, all dynamic lookup behavior, or arbitrary application runtime requirements.
- **No broad game compatibility guarantee.** Six-game static analysis and isolated mock/forwarding validation do not replace live end-to-end game testing.
- **No consumer-ready Frame installation package or public download.** Existing Frame build outputs are validation artifacts, not supported upstream releases.
- **No claim of a current clean security audit.** See the dependency/security review for outstanding advisories and release gates.
- **No proprietary APKs, game binaries, entitlement material, production signing credentials or private game captures** are distributed in this repository.

## Roadmap / TODO

This is a working roadmap, not a promised release schedule. Tasks require separate evidence and review before they are marked complete.

### A. Stabilize the inspector release

- [x] Implement read-only Lepton discovery, analyzer and inspector UI.
- [x] Validate the inspector and controlled forwarding experiments on real Steam Frame hardware.
- [x] Establish pinned LLVM 20.1.8 tooling and frozen ARM64 build/test inputs.
- [x] Obtain a successful hosted Python/Rust/rendering test run.
- [ ] Finish a **successful end-to-end hosted ARM64 AppImage build** on the exact test branch revision.
- [ ] Verify the produced artifact, AppDir inventory, hashes and source provenance.
- [ ] Repeat the build and demonstrate reproducibility for that **exact** source/toolchain combination.
- [ ] Perform an exact-artifact Steam Frame smoke test for the new hosted build.
- [ ] Resolve the development PR's workflow-registration merge conflict before any considered merge.

### B. Feature parity and ARM64 compatibility research

- [ ] Create a complete upstream **CreamLinux/CreamAPI/SmokeAPI/ScreamAPI feature inventory** and mark each item implemented, partial, unsupported or unverified on Steam Frame.
- [ ] Investigate the architectural requirements and feasibility of an **ARM64/Bionic CreamAPI port**, including compatibility with Lepton and the original Steamworks interfaces.
- [ ] Resolve required non-function exports, data-symbol identity, versioning, symbol visibility, loading order and Android linker-namespace differences.
- [ ] Extend target-specific function forwarding beyond isolated fixtures only after demonstrating the exact target ABI and loader behavior.
- [ ] Build explicit per-game compatibility and evidence reports, including split APKs and runtime-generated consumers.
- [ ] Define safe, explicit opt-in integration, verification, backup and rollback requirements; **do not assume live game modification is supported**.
- [ ] Investigate whether and how upstream desktop features can be adapted to Steam Frame while respecting licensing and platform constraints.

### C. User experience and hardware testing

- [ ] Add a user-friendly launcher/game selector so users do not need to supply an AppID manually.
- [ ] Improve inspector feedback for missing contexts, incomplete APK scans, incompatible providers and stale evidence.
- [ ] Validate additional game versions, devices and SteamOS/Lepton updates.
- [ ] Add regression coverage for any new integration behavior and collect exact-artifact device results.
- [ ] Design and validate any future installation/rollback UI independently of the read-only inspector.

### D. Security, distribution and maintenance

- [ ] Reassess outstanding project/SDK dependency advisories before public distribution.
- [ ] Finish non-publishing CI release verification and documented resource/runner requirements.
- [ ] Audit the complete Frame-specific package contents, permissions and update behavior.
- [ ] Establish a separately approved signing identity and distribution process if a public inspector release is planned.
- [ ] Maintain upstream credit, license compliance, technical documentation and release notes.

## Try the development branch (developers)

Clone the branch containing the Steam Frame code:

```bash
git clone --branch test/steam-frame-inspector-security-ci --single-branch \
  https://github.com/mitch030504/creamlinux-installer.git
cd creamlinux-installer
```

**Do not run the old desktop installation instructions expecting a Lepton-capable CreamAPI installer.** Follow the branch's [Steam Frame release guide](https://github.com/mitch030504/creamlinux-installer/blob/test/steam-frame-inspector-security-ci/STEAM_FRAME_RELEASE.md) for exact pinned prerequisites and build procedures.

The purpose-built inspector AppImage, **when built and deployed onto a compatible Steam Frame host**, uses explicit read-only launch modes:

```bash
./Creamlinux_1.7.1_steam-frame-inspector_aarch64.AppImage --lepton-release-info
./Creamlinux_1.7.1_steam-frame-inspector_aarch64.AppImage --lepton-inspector 448280
./Creamlinux_1.7.1_steam-frame-inspector_aarch64.AppImage --lepton-compatibility 448280
```

The filename is an example of the documented local validation artifact, **not a download link or a guarantee that this exact binary is published**. AppIDs must correspond to games available to the inspector. Argumentless execution of the Frame-specific application deliberately rejects legacy startup.

## Technical documentation

The following files live on the **development branch**:

| Document | Subject |
| --- | --- |
| [Steam Frame release workflow](https://github.com/mitch030504/creamlinux-installer/blob/test/steam-frame-inspector-security-ci/STEAM_FRAME_RELEASE.md) | Build controller, frozen ARM64 SDK, AppImage output, smoke validation and release limitations |
| [CI and security architecture](https://github.com/mitch030504/creamlinux-installer/blob/test/steam-frame-inspector-security-ci/STEAM_FRAME_CI.md) | Non-publishing workflows, pinned inputs, provenance and diagnostic boundaries |
| [Security review](https://github.com/mitch030504/creamlinux-installer/blob/test/steam-frame-inspector-security-ci/STEAM_FRAME_SECURITY_REVIEW.md) | Dependency advisories, mitigations and outstanding release risks |
| [Inspector integration](https://github.com/mitch030504/creamlinux-installer/blob/test/steam-frame-inspector-security-ci/tools/android-steam-proxy/INSPECTOR_INTEGRATION.md) | Native packaged inspector GUI/backend results and limitations |
| [Proxy validation status](https://github.com/mitch030504/creamlinux-installer/blob/test/steam-frame-inspector-security-ci/tools/android-steam-proxy/VALIDATION_STATUS.md) | Target-specific function coverage, Bionic tests, six-game analysis and gaps |
| [LLVM runtime](https://github.com/mitch030504/creamlinux-installer/blob/test/steam-frame-inspector-security-ci/tools/android-steam-proxy/LLVM_RUNTIME.md) | ARM64 private LLVM reader, dependencies, native measurements |
| [Android forwarding research](https://github.com/mitch030504/creamlinux-installer/blob/test/steam-frame-inspector-security-ci/tools/android-steam-proxy/README.md) | Detailed standalone proxy design, ABI verification and experimental boundaries |

## Original CreamLinux desktop project

This fork preserves code originating from [Novattz/creamlinux-installer](https://github.com/Novattz/creamlinux-installer). Upstream describes a Linux desktop GUI for managing Steam DLC-related configurations with CreamAPI, SmokeAPI (Proton) and ScreamAPI (Epic/Heroic/Legendary), alongside game discovery and a Tauri/React interface.

See the **[upstream README](https://github.com/Novattz/creamlinux-installer#readme)** for the original desktop installation, Nix, builds, usage and troubleshooting instructions. **Those instructions describe the original desktop software, not a finished Lepton/Steam Frame port.** This fork does not guarantee that upstream behaviors have been independently tested or adapted to ARM64.

## License, attribution and contributions

See [LICENSE.md](LICENSE.md) for the repository license and preserve the notices applicable to upstream and included third-party components. Original CreamLinux, the referenced API projects, [Tauri](https://tauri.app/) and [React](https://react.dev/) remain credited to their respective authors.

For Frame-specific bugs or improvements, use [this fork's issues](https://github.com/mitch030504/creamlinux-installer/issues) and include the branch/commit, SteamOS and Lepton versions, exact CLI mode and a redacted diagnostic report. Never upload proprietary game files, private captures, or credentials.

**Valve, Steam, SteamOS, Steam Frame, Lepton and the referenced games belong to their respective owners. This project is an unofficial experiment and is not affiliated with or endorsed by Valve.**
