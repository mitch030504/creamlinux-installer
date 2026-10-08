# Steam Frame dependency security and release review — 2026-10-08

This reviews the complete accumulated worktree against
`fce1fe42ecffea80711ca3d7bdb8bc5f773d715d`, before its first commit. No files
were staged; no commit, push, tag, publication or production signing occurred.
It supersedes the dependency-security next-step text in the CI handoff.

## Readiness decisions

| Decision | Status |
|---|---|
| A. Source commit | Ready for an explicitly authorized reviewed source commit, subject to final measured release evidence in the security handoff. Residual advisories are disclosed. |
| B. Test-branch push / hosted CI | Code prepared; not executed. Current GitHub account has pull=true, push=false on Novattz/creamlinux-installer; owner write access or an authorized fork/remote is needed. |
| C. Release candidate | Local non-publishing validation candidate only; hosted CI and residual dependency acceptance/remediation remain gates. |
| D. Protected production signing | Not ready: separate inspector key/channel, protected environment, artifact approval, residual security review and explicit authorization are required. |
| E. Public distribution | Not ready: no publication authorization, hosted CI not run, remaining dependency/toolchain review and distribution policy required. |

A successful build is not a clean security audit. No npm or Rust advisory was
ignored, downgraded, hidden, or suppressed to obtain a passing audit.

## Audit baseline and evidence

Actual commands ran with Node 22.16.0/npm 10.9.2 in the approved ARM64 SDK:
`npm audit --json`, `npm ls --all --json`, `npm explain tar --json`, then the
same audits after targeted lock updates. npm's nonzero advisory exit is retained.
The initial 32 entries are affected **package nodes**, not 32 unique advisories:
there are 71 unique GHSAs. Initial severities: critical 1, high 25, moderate 5,
low 1. Registry results were collected on 2026-10-08.

The inventory [security/dependency-review-2026-10-08.json](security/dependency-review-2026-10-08.json)
contains every installed before/after version, actual lockfile dependency ancestry
(one shortest complete path per direct parent), npm prod/dev/bundled flags,
original advisory ID/range/severity/patch floor, and runtime/build exposure.
Parent entries propagate underlying advisories; they do not each represent a
separate vulnerability in the parent. Exploit descriptions below summarize
preconditions; upstream advisory links provide authoritative detail.

Rust was audited with **cargo-audit 0.22.2**, installed with `cargo install
cargo-audit --version 0.22.2 --locked` in an isolated ignored controller prefix,
using Cargo/Rust 1.96.0. This did not install anything into SteamOS or change the
old SDK. RustSec database commit is
`550efd3d587a29b2e2c2b21b17a440da4fede999` (1,295 entries at initial audit).
Both vulnerability findings and informational warnings are retained in JSON.
Cargo registry checksums and the audit tool's locked dependencies authenticate
its build inputs; this is not a claim of signed audit-tool provenance.

Raw audits, tree/explain records, official advisory JSON, tool installation logs,
repository read-only API results and test logs are retained under
`tools/android-steam-proxy/build/security-review/` and selected in the final
handoff. No proprietary game capture is in security evidence.

## Critical tar analysis

Installed ancestry is `semantic-release@25.0.3 -> @semantic-release/npm@13.1.5
-> npm@11.13.0 -> tar@7.5.13`. npm's other bundled clients (pacote, node-gyp,
cacache, libnpmdiff and libnpmpack) also resolve that same tar. It is an npm
development dependency, not the system GNU tar utility. It is absent from the
AppImage; generated proxy/provider/APK files are also absent.

[GHSA-23hp-3jrh-7fpw](https://github.com/advisories/GHSA-23hp-3jrh-7fpw),
CVE-2026-59873, is critical: extraction/parse accepts attacker-controlled expanded
archive data without cumulative resource bounds, permitting CPU/disk exhaustion.
It affects <=7.5.18 and is patched in 7.5.19. The complete six-advisory tar set
needs **7.5.21** because the later member-selection recursion issue affects
<=7.5.20. This remediation uses **7.5.22**.

A hostile registry/Git/archive input is the relevant precondition. Merely being
in devDependencies is insufficient: npm installers extract fetched archives in
trusted manual and untrusted PR builds. Registry SRI and HTTPS reduce tampering
but do not justify keeping a known vulnerable extractor. The semantic-release
CLI and its bundled npm are not invoked by Frame release workflows, but ordinary
npm installation itself is an additional extractor exposure.

Targeted compatible `npm update --package-lock-only --ignore-scripts` updates npm's
**published parent bundle** to npm 11.21.0 (within its declared ^11 range), carrying
tar 7.5.22. No forced npm fix, major override, vendored npm patch or advisory
suppression was used. The fixed parent preserves semantic-release interfaces.
A dry-run confirmed that npm cannot individually repair dependencies inside its
published bundle; forceful parent downgrades suggested by audit are rejected.

The frozen Node archive independently embeds npm 10.9.2 / tar 6.2.1. That is now
replaced in a **new SDK image** by checksum-pinned npm **10.9.9**, carrying tar
7.5.22; the old containers/images are preserved. Python's filtered extraction
verifies the complete npm archive SHA256 before installation and does not invoke
the old npm extractor. CI Node jobs use the same pin in a private prefix via
`scripts/release/prepare-npm.py`, never a global install. Failure propagates before
npm ci. Licenses remain in npm's package. The apt inventory, Ubuntu snapshot,
Node/Rust archive pins and ARM64 target stay unchanged.

## npm package finding disposition

Final project audit: **14 affected entries: 12 high, 2 moderate, zero critical**.
Eighteen initial package findings are fixed. **59 original GHSAs are fixed;
12 original GHSAs remain**, plus one newly exposed npm-bundled ip-address advisory
(GHSA-2vr4-cq9g-pvrc): 13 unique final project GHSAs. `npm audit --omit=dev` reports
zero findings. Sass/immutable are labelled npm-production dependencies but execute
at build time; UUID is bundled frontend code, using only v4 toast identifiers.

| Initial package | Installed before → after | Initial severity | Disposition |
|---|---|---|---|
| @babel/core | 7.29.0 → 7.29.7 | low | fixed |
| @babel/plugin-transform-modules-systemjs | 7.29.0 → 7.29.8 | high | fixed |
| @semantic-release/changelog | 6.0.3 → 6.0.3 | high | unresolved |
| @semantic-release/commit-analyzer | 13.0.1 → 13.0.1 | high | unresolved |
| @semantic-release/git | 10.0.1 → 10.0.1 | high | unresolved |
| @semantic-release/github | 11.0.6, 12.0.6 → 11.0.6, 12.0.6 | high | unresolved |
| @semantic-release/npm | 13.1.5 → 13.1.5 | high | unresolved |
| @semantic-release/release-notes-generator | 14.1.0 → 14.1.0 | high | unresolved |
| @sigstore/core | 3.2.0 → 3.2.1 | moderate | fixed |
| @sigstore/verify | 3.1.0 → 3.1.1 | moderate | fixed |
| baseline-browser-mapping | 2.10.24 → 2.11.27 | moderate | fixed |
| brace-expansion | 1.1.14, 5.0.5 → 1.1.21, 5.0.12, 5.0.9 | high | unresolved |
| braces | 3.0.3 → 3.0.3 | high | unresolved |
| browserslist | 4.28.2 → 4.29.3 | high | fixed |
| http-cache-semantics | 4.2.0 → 4.2.0 | high | unresolved |
| immutable | 5.1.5 → 5.1.9 | high | fixed |
| ip-address | 10.1.0 → 10.5.0 | high | unresolved |
| js-yaml | 4.1.1 → 4.3.2 | high | fixed |
| micromatch | 4.0.8 → 4.0.8 | high | unresolved |
| nanoid | 3.3.11 → 3.3.20 | high | fixed |
| npm | 11.13.0 → 11.21.0 | high | fixed |
| pacote | 21.5.0 → 21.5.1 | high | fixed |
| postcss | 8.5.12 → 8.5.29 | high | fixed |
| postcss-selector-parser | 7.1.1 → 7.1.4 | moderate | unresolved |
| semantic-release | 25.0.3 → 25.0.3 | high | unresolved |
| sigstore | 4.1.0 → 4.1.1 | high | fixed |
| source-map-js | 1.2.1 → 1.2.2 | high | fixed |
| svgo | 3.3.3 → 3.3.5 | high | fixed |
| tar | 7.5.13 → 7.5.22 | critical | fixed |
| undici | 6.25.0, 7.25.0 → 6.28.0, 6.29.0, 7.30.0 | high | unresolved |
| uuid | 11.1.0 → 11.1.1 | moderate | fixed |
| vite | 6.4.2 → 6.4.4 | high | fixed |

### Exploit preconditions and remaining risk

- Babel/PostCSS/source-map tooling: attacker-controlled source or sourceMappingURL
  can trigger file disclosure/code generation/DoS in a compiler. Source is built
  only on disposable CI without signing keys; all reported compatible patches
  were applied. Updated SystemJS compiler is not an assumption that compiling
  arbitrary PR code becomes safe for production signing.
- Browserslist/baseline/immutable/nanoid/brace expansion: crafted query, YAML,
  nested glob or oversized collection/size inputs can cause crashes or resource
  exhaustion. Compiler/lint/SVG assets come from the checked-out source. Fixed
  compatible versions are used wherever available.
- SVG sanitizer flaws require treating optimized untrusted SVG as sanitized safe
  content. SVG tooling is build-time and repo assets are trusted; SVGO's compatible
  patches were still applied. Inspector strings render through React escaping,
  with no new raw-HTML injection sink.
- Vite advisories require its Windows development server/editor paths. Frame
  bundles a production frontend and runs no Vite server. Compatible 6.4.4 fixes
  them without a Vite-major migration.
- UUID's vulnerable buffer-taking v3/v5/v6 routines are not used; the frontend
  uses v4 without an output buffer. The compatible 11.1.1 patch was applied.
- Sigstore verification weaknesses require depending on affected certificate/OID
  or DSSE authenticity checks. Patched project copies are present. SRI locks
  are the build download integrity gate; neither npm audit signatures nor unsigned
  release provenance is claimed to authenticate a distributor.
- **Unpatched braces 3.0.3 / GHSA-vfj7-8cjw-p6xm:** deeply nested external glob
  patterns can exhaust the stack. Latest published braces remains 3.0.3 and
  has no first-patched version. It propagates through micromatch and the
  semantic-release family. No inspector HTTP/API accepts glob patterns; repo
  patterns/configs run on disposable, secret-free CI. This limits exposure,
  but the finding remains **unresolved**, not fixed. Forking the parser or
  downgrading semantic-release is not a safe minimal change.
- **npm 11.21.0's vendor bundle** still includes affected brace-expansion,
  http-cache-semantics, ip-address, postcss-selector-parser and undici copies.
  Individual patch floors are listed below. npm bundling prevents normal
  compatible overrides from replacing these copies. No unpublished npm fork
  or uncontrolled major upgrade was introduced. Shared cross-user HTTP caches,
  externally supplied IP/selector/glob data, hostile proxy/network/WebSocket
  behavior are the advisory preconditions. Frame scripts invoke no npm query,
  SOCKS proxy, WebSocket, or shared application cache; semantic-release's bundled
  npm is not invoked. This reduces reachable surfaces, not an audit exemption.
- **SDK npm 10.9.9** separately has 18 affected entries (14 high, 4 moderate,
  zero critical) in its older published vendor bundle. These are recorded in
  JSON, not confused with the project's 14 entries. pacote's Git-SHA DoS requires
  attacker-controlled Git input; locked project dependencies have registry URLs,
  not Git dependencies. Build jobs have no registry/signing secrets, use exact
  SRI-pinned packages, no shared release caches, and bounded disposable runners.
  The same network/parser/verification cautions apply; patched tar does not
  mean the entire npm toolchain is vulnerability-free.

Private fixtures are never uploaded. No production credential is present in
normal Frame jobs. Do not enable production signing/distribution on the strength
of these exposure reductions alone. Review upstream npm bundle refreshes and the
braces fix when available, without replacing reviewed hashes merely to silence
checks. This review is npm/Rust focused, not a complete OS/Node/LLVM CVE scan;
Node 22.16.0 and the pinned apt/LLVM closure need ongoing separate security
maintenance before public distribution.

## Full original advisory inventory

This table covers all 71 initial IDs. Package ancestry and installed versions are
in the package table and machine inventory. Patch floors are ecosystem versions;
not every floor is a compatible branch (for example Undici 6 vs 7). “Unresolved”
means the affected package is still present after remediation; mitigation notes
above never overwrite this state.

| Advisory | Package / severity | Preconditions (upstream summary) | First patched versions | Status |
|---|---|---|---|---|
| [GHSA-23hp-3jrh-7fpw](https://github.com/advisories/GHSA-23hp-3jrh-7fpw) | tar / critical | node-tar: Decompression/parse DoS via unlimited input | 7.5.19 | fixed |
| [GHSA-2883-xcg3-v3hh](https://github.com/advisories/GHSA-2883-xcg3-v3hh) | js-yaml / high | js-yaml: maxTotalMergeKeys does not limit CPU use for empty merge sources | 3.15.2, 4.3.2 | fixed |
| [GHSA-28wg-ghj8-5hjv](https://github.com/advisories/GHSA-28wg-ghj8-5hjv) | nanoid / high | nanoid: non-secure generators can loop indefinitely with negative size | 3.3.16, 5.1.16 | fixed |
| [GHSA-2gqq-gqf2-x968](https://github.com/advisories/GHSA-2gqq-gqf2-x968) | undici / low | undici vulnerable to response truncation via oversized chunked responses in the dump interceptor | 7.29.1, 8.10.2 | fixed |
| [GHSA-2jfj-6hjv-fm6j](https://github.com/advisories/GHSA-2jfj-6hjv-fm6j) | undici / moderate | undici vulnerable to cross-user cookie disclosure via Set-Cookie caching in shared caches | 7.29.1, 8.10.2 | fixed |
| [GHSA-2p49-hgcm-8545](https://github.com/advisories/GHSA-2p49-hgcm-8545) | svgo / high | SVGO removeScripts plugin leaves some executable scripts intact | 2.8.3, 3.3.4, 4.0.2 | fixed |
| [GHSA-2v37-7h3g-55p8](https://github.com/advisories/GHSA-2v37-7h3g-55p8) | nanoid / high | nanoid: custom generators can loop indefinitely when size is zero | 3.3.18, 5.1.6 | fixed |
| [GHSA-35p6-xmwp-9g52](https://github.com/advisories/GHSA-35p6-xmwp-9g52) | undici / low | undici vulnerable to HTTP response queue poisoning via keep-alive socket reuse | 6.27.0, 7.28.0, 8.5.0 | fixed |
| [GHSA-3jxr-9vmj-r5cp](https://github.com/advisories/GHSA-3jxr-9vmj-r5cp) | brace-expansion / high | brace-expansion: DoS via exponential-time expansion of consecutive non-expanding {} groups | 1.1.16, 2.1.2, 5.0.7 | fixed |
| [GHSA-3wwx-pv8p-q78v](https://github.com/advisories/GHSA-3wwx-pv8p-q78v) | undici / moderate | undici vulnerable to Denial of Service via unhandled error in WebSocket permessage-deflate decompression | 6.28.1, 7.29.1, 8.10.2 | unresolved |
| [GHSA-3xpg-4rpp-hhhm](https://github.com/advisories/GHSA-3xpg-4rpp-hhhm) | undici / moderate | undici vulnerable to Denial of Service via unbounded decompression of compressed responses | 7.29.1, 8.10.2 | fixed |
| [GHSA-4cwx-7wf7-3272](https://github.com/advisories/GHSA-4cwx-7wf7-3272) | undici / high | undici vulnerable to cross-user information disclosure and parse-time crash via degenerate private cache directives | 7.29.0, 8.9.0 | fixed |
| [GHSA-4vpr-x523-8j87](https://github.com/advisories/GHSA-4vpr-x523-8j87) | svgo / moderate | SVGO: removeScripts incompletely sanitizes executable HTML in SVG foreignObject elements | 2.8.4, 3.3.5, 4.1.0 | fixed |
| [GHSA-4x5r-pxfx-6jf8](https://github.com/advisories/GHSA-4x5r-pxfx-6jf8) | @babel/core / low | @babel/core: Arbitrary File Read via sourceMappingURL Comment | 7.29.6, 8.0.0-rc.6 | fixed |
| [GHSA-52cp-r559-cp3m](https://github.com/advisories/GHSA-52cp-r559-cp3m) | js-yaml / high | js-yaml: YAML merge-key chains can force quadratic CPU consumption | 3.15.0, 4.3.0 | fixed |
| [GHSA-52v5-jr5w-gjxr](https://github.com/advisories/GHSA-52v5-jr5w-gjxr) | sigstore / high | sigstore's `certificateOIDs` verification constraints are silently dropped and never enforced | 4.1.1 | fixed |
| [GHSA-5p4m-2wfm-xmqj](https://github.com/advisories/GHSA-5p4m-2wfm-xmqj) | js-yaml / high | JS-YAML: Quadratic CPU consumption in !!omap resolution (3.x and 4.x) — CVE-2026-59870 fix not backported | 3.15.1, 4.3.1 | fixed |
| [GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q) | source-map-js / high | source-map-js allows event-loop denial of service through indexed source-map section offsets | 1.2.2 | fixed |
| [GHSA-6j4f-fj2g-mc7p](https://github.com/advisories/GHSA-6j4f-fj2g-mc7p) | brace-expansion / high | brace-expansion: DoS via uncontrolled recursion in parseCommaParts causing stack exhaustion | 1.1.19, 2.1.5, 3.0.7, 5.0.10 | unresolved |
| [GHSA-73wf-gq98-2v4g](https://github.com/advisories/GHSA-73wf-gq98-2v4g) | browserslist / high | Browserslist: Uncaught crash / prototype write via untrusted browserslist-stats.json custom stats (normalizeStats) | 4.28.7 | fixed |
| [GHSA-8436-99hf-9mmv](https://github.com/advisories/GHSA-8436-99hf-9mmv) | undici / low | undici vulnerable to caching and replay of unsafe HTTP method responses | 7.29.1, 8.10.2 | fixed |
| [GHSA-8x88-c5mf-7j5w](https://github.com/advisories/GHSA-8x88-c5mf-7j5w) | tar / high | node-tar: Negative tar entry size causes infinite loop in archive replace | 7.5.18 | fixed |
| [GHSA-8xcm-r25x-g524](https://github.com/advisories/GHSA-8xcm-r25x-g524) | undici / moderate | undici vulnerable to downstream response desynchronization via retry interceptor | 6.28.0, 7.29.0, 8.9.0 | fixed |
| [GHSA-c83g-rgw3-j3cx](https://github.com/advisories/GHSA-c83g-rgw3-j3cx) | browserslist / high | Browserslist: Unbounded memory growth (no cache eviction) via distinct query results, leading to eventual OOM | 4.28.7 | fixed |
| [GHSA-ch52-4w7c-c8xp](https://github.com/advisories/GHSA-ch52-4w7c-c8xp) | http-cache-semantics / high | http-cache-semantics max-stale handling can disclose cross-user cached responses | none published | unresolved |
| [GHSA-fv7c-fp4j-7gwp](https://github.com/advisories/GHSA-fv7c-fp4j-7gwp) | @babel/plugin-transform-modules-systemjs / high | @babel/plugin-transform-modules-systemjs generates arbitrary code when compiling malicious input | 7.29.4, 8.0.0-alpha.13 | fixed |
| [GHSA-fx2h-pf6j-xcff](https://github.com/advisories/GHSA-fx2h-pf6j-xcff) | vite / high | vite: `server.fs.deny` bypass on Windows alternate paths | 6.4.3, 7.3.5, 8.0.16 | fixed |
| [GHSA-fxqj-rqcc-2cmp](https://github.com/advisories/GHSA-fxqj-rqcc-2cmp) | postcss / moderate | PostCSS: incomplete fix of GHSA-6g55-p6wh-862q — attacker-controlled sourceMappingURL reads arbitrary .map files when `from` is unset | 8.5.23 | fixed |
| [GHSA-g8m3-5g58-fq7m](https://github.com/advisories/GHSA-g8m3-5g58-fq7m) | undici / low | undici vulnerable to Set-Cookie SameSite attribute downgrade via permissive substring matching | 6.27.0, 7.28.0, 8.5.0 | fixed |
| [GHSA-gvwx-54wh-qm9j](https://github.com/advisories/GHSA-gvwx-54wh-qm9j) | tar / moderate | node-tar: Uncaught Exception DoS via NUL byte in PAX path/linkpath records | 7.5.17 | fixed |
| [GHSA-h3mg-xc3c-68pw](https://github.com/advisories/GHSA-h3mg-xc3c-68pw) | ip-address / moderate | ip-address: Address6 builds a parse diagnostic proportional to the input with no length bound, allowing a single long string to stall or crash the process | 10.7.1 | unresolved |
| [GHSA-h67p-54hq-rp68](https://github.com/advisories/GHSA-h67p-54hq-rp68) | js-yaml / moderate | JS-YAML: Quadratic-complexity DoS in merge key handling via repeated aliases | 3.15.0, 4.2.0 | fixed |
| [GHSA-hm92-r4w5-c3mj](https://github.com/advisories/GHSA-hm92-r4w5-c3mj) | undici / high | undici vulnerable to cross-origin request routing via SOCKS5 proxy pool reuse | 7.28.0, 8.2.0 | fixed |
| [GHSA-j6r3-76f7-8jcv](https://github.com/advisories/GHSA-j6r3-76f7-8jcv) | ip-address / moderate | ip-address: isInSubnet() and isHostInSubnet() compare addresses of different families as if they shared an address space, allowing an allowlist check to admit an address outside its range | 10.7.1 | unresolved |
| [GHSA-jfc7-64v2-mr8c](https://github.com/advisories/GHSA-jfc7-64v2-mr8c) | @sigstore/core / moderate | @sigstore/core has DSSE payloadType type-binding failure | 3.2.1 | fixed |
| [GHSA-jr45-8vmc-qm54](https://github.com/advisories/GHSA-jr45-8vmc-qm54) | undici / moderate | undici vulnerable to cross-user information disclosure via whitespace around equals in Cache-Control directives | 7.29.0, 8.9.0 | fixed |
| [GHSA-jxxr-4gwj-5jf2](https://github.com/advisories/GHSA-jxxr-4gwj-5jf2) | brace-expansion / moderate | brace-expansion: Large numeric range defeats documented `max` DoS protection | 5.0.6 | fixed |
| [GHSA-m8rv-5g2x-5cg5](https://github.com/advisories/GHSA-m8rv-5g2x-5cg5) | undici / moderate | undici vulnerable to CRLF Injection via blob-like body 'type' property | 6.28.0, 7.29.0, 8.9.0 | fixed |
| [GHSA-mh99-v99m-4gvg](https://github.com/advisories/GHSA-mh99-v99m-4gvg) | brace-expansion / high | brace-expansion: DoS via unbounded expansion length causing an out-of-memory process crash | 1.1.17, 2.1.3, 3.0.3, 5.0.8 | fixed |
| [GHSA-mwp4-54f8-5fhr](https://github.com/advisories/GHSA-mwp4-54f8-5fhr) | ip-address / high | ip-address: Address4 decodes leading-zero octets as decimal while resolvers decode them as octal, allowing SSRF and trust-boundary bypass | 10.3.1 | fixed |
| [GHSA-p88m-4jfj-68fv](https://github.com/advisories/GHSA-p88m-4jfj-68fv) | undici / moderate | undici vulnerable to HTTP header injection via Set-Cookie percent-decoding | 6.27.0, 7.28.0, 8.5.0 | fixed |
| [GHSA-pmjh-fq2x-6v4x](https://github.com/advisories/GHSA-pmjh-fq2x-6v4x) | undici / moderate | undici vulnerable to Denial of Service via orphaned RetryHandler response body | 7.29.1, 8.10.2 | fixed |
| [GHSA-pr7r-676h-xcf6](https://github.com/advisories/GHSA-pr7r-676h-xcf6) | undici / moderate | undici vulnerable to cross-user information disclosure via shared cache whitespace bypass | 7.28.0, 8.5.0 | fixed |
| [GHSA-q2hr-2g5m-vwhr](https://github.com/advisories/GHSA-q2hr-2g5m-vwhr) | brace-expansion / moderate | brace-expansion: Quadratic-time expansion of the `{a},b}` rewrite causes CPU denial of service | 1.1.21, 2.1.7, 3.0.9, 5.0.12 | unresolved |
| [GHSA-qhr7-859c-m2p7](https://github.com/advisories/GHSA-qhr7-859c-m2p7) | brace-expansion / high | brace-expansion: DoS via uncontrolled recursion on nested brace groups causing stack exhaustion | 1.1.20, 2.1.6, 3.0.8, 5.0.11 | unresolved |
| [GHSA-r28c-9q8g-f849](https://github.com/advisories/GHSA-r28c-9q8g-f849) | postcss / high | PostCSS: Path Traversal in Previous Source Map Auto-Loading (sourceMappingURL) leads to Arbitrary .map File Disclosure | 8.5.18 | fixed |
| [GHSA-r292-9mhp-454m](https://github.com/advisories/GHSA-r292-9mhp-454m) | tar / high | node-tar: Uncontrolled recursion in mapHas/filesFilter allows uncatchable stack-overflow DoS via crafted long-path tar with member selection | 7.5.21 | fixed |
| [GHSA-r53p-7pc4-xj5r](https://github.com/advisories/GHSA-r53p-7pc4-xj5r) | undici / low | undici vulnerable to downstream response splitting via retry interceptor | 6.28.1, 7.29.1, 8.10.2 | unresolved |
| [GHSA-rfgv-xxqx-mfg5](https://github.com/advisories/GHSA-rfgv-xxqx-mfg5) | undici / high | undici vulnerable to Denial of Service via unrequested WebSocket subprotocol | 6.28.1, 7.29.1, 8.10.2 | unresolved |
| [GHSA-rgw5-rvv9-x895](https://github.com/advisories/GHSA-rgw5-rvv9-x895) | brace-expansion / high | brace-expansion: DoS via unbounded intermediate arrays, bypassing the CVE-2026-14257 mitigation | 1.1.18, 2.1.4, 3.0.6, 5.0.9 | fixed |
| [GHSA-rj75-hqrm-r3gf](https://github.com/advisories/GHSA-rj75-hqrm-r3gf) | postcss-selector-parser / moderate | PostCSS: Quadratic complexity in flat selector parsing allows CPU exhaustion | 7.1.6 | unresolved |
| [GHSA-rpw4-54j3-4h4q](https://github.com/advisories/GHSA-rpw4-54j3-4h4q) | ip-address / moderate | ip-address: Address6.isLinkLocal() recognizes fe80::/64 rather than fe80::/10, allowing SSRF and trust-boundary bypass to on-link hosts | 10.5.1 | unresolved |
| [GHSA-rx4f-c7p8-82vq](https://github.com/advisories/GHSA-rx4f-c7p8-82vq) | undici / moderate | undici vulnerable to Denial of Service via WebSocketStream unclean close | 7.29.1, 8.10.2 | fixed |
| [GHSA-v2v4-37r5-5v8g](https://github.com/advisories/GHSA-v2v4-37r5-5v8g) | ip-address / moderate | ip-address has XSS in Address6 HTML-emitting methods | 10.1.1 | fixed |
| [GHSA-v3r7-h72x-cjcm](https://github.com/advisories/GHSA-v3r7-h72x-cjcm) | undici / moderate | undici vulnerable to cookie attribute injection via unsanitized domain and unparsed setCookie fields | 6.28.0, 7.29.0, 8.9.0 | fixed |
| [GHSA-v56q-mh7h-f735](https://github.com/advisories/GHSA-v56q-mh7h-f735) | immutable / high | Immutable.js `List` 32-bit trie overflow → unrecoverable DoS | 3.8.4, 4.3.9, 5.1.8 | fixed |
| [GHSA-v6wh-96g9-6wx3](https://github.com/advisories/GHSA-v6wh-96g9-6wx3) | vite / moderate | launch-editor: NTLMv2 hash disclosure via UNC path handling on Windows | 6.4.3, 7.3.5, 8.0.16 | fixed |
| [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) | braces / high | braces vulnerable to stack-exhaustion denial of service through deeply nested patterns | none published | unresolved |
| [GHSA-vmf3-w455-68vh](https://github.com/advisories/GHSA-vmf3-w455-68vh) | tar / moderate | node-tar applies PAX size override to intermediary GNU long-name/long-link headers, causing tar parser interpretation differential (file smuggling) | 7.5.16 | fixed |
| [GHSA-vmh5-mc38-953g](https://github.com/advisories/GHSA-vmh5-mc38-953g) | undici / high | undici vulnerable to TLS certificate validation bypass via dropped requestTls in SOCKS5 ProxyAgent | 7.28.0, 8.5.0 | fixed |
| [GHSA-vxpw-j846-p89q](https://github.com/advisories/GHSA-vxpw-j846-p89q) | undici / high | undici WebSocket client vulnerable to denial of service via fragment count bypass | 6.27.0, 7.28.0, 8.5.0 | fixed |
| [GHSA-w27v-7q3p-w38r](https://github.com/advisories/GHSA-w27v-7q3p-w38r) | svgo / high | SVGO: removeScripts allows executable links through namespace and control-character bypasses | 2.8.4, 3.3.5, 4.1.0 | fixed |
| [GHSA-w293-vg96-wgc3](https://github.com/advisories/GHSA-w293-vg96-wgc3) | undici / high | undici vulnerable to TLS certificate validation bypass via dropped connect options in BalancedPool | 7.29.1, 8.10.2 | fixed |
| [GHSA-w4pp-8pjf-rmxw](https://github.com/advisories/GHSA-w4pp-8pjf-rmxw) | pacote / high | pacote is vulnerable to Denial of Service (DoS) via the addGitSha function | 21.5.1 | fixed |
| [GHSA-w5hq-g745-h8pq](https://github.com/advisories/GHSA-w5hq-g745-h8pq) | uuid / moderate | uuid: Missing buffer bounds check in v3/v5/v6 when buf is provided | 11.1.1, 12.0.1, 13.0.1 | fixed |
| [GHSA-w5vr-8v7q-w6rv](https://github.com/advisories/GHSA-w5vr-8v7q-w6rv) | baseline-browser-mapping / moderate | baseline-browser-mapping process termination on invalid input causes denial of service | 2.11.0 | fixed |
| [GHSA-w8wr-v893-vjvp](https://github.com/advisories/GHSA-w8wr-v893-vjvp) | tar / moderate | node-tar: Process crash via PAX numeric path type confusion | 7.5.18 | fixed |
| [GHSA-w9m9-85wc-3x92](https://github.com/advisories/GHSA-w9m9-85wc-3x92) | postcss-selector-parser / low | postcss-selector-parser allows denial of service through uncontrolled AST recursion | 6.1.3, 7.1.3 | fixed |
| [GHSA-xgjw-pm74-86q4](https://github.com/advisories/GHSA-xgjw-pm74-86q4) | @sigstore/verify / moderate | sigstore-js has Insufficient Verification of Data Authenticity | 3.1.1 | fixed |
| [GHSA-xvcm-6775-5m9r](https://github.com/advisories/GHSA-xvcm-6775-5m9r) | immutable / high | Immutable: Hash-collision algorithmic complexity denial of service in Immutable.Map/Set | 3.8.4, 4.3.9, 5.1.8 | fixed |
| [GHSA-xwg4-73v4-xw9w](https://github.com/advisories/GHSA-xwg4-73v4-xw9w) | nanoid / high | nanoid: Integer Overflow or Wraparound | 3.3.12, 5.1.11 | fixed |

Additional findings exposed after updates or by auditing SDK npm:

- [GHSA-2vr4-cq9g-pvrc](https://github.com/advisories/GHSA-2vr4-cq9g-pvrc): project-after; ip-address: no classifier recognizes the NAT64 local-use range 64:ff9b:1::/48, allowing SSRF and trust-boundary bypass; affected >=10.2.0 <=10.5.0; patches 10.5.1; unresolved.
- [GHSA-f886-m6hf-6m8v](https://github.com/advisories/GHSA-f886-m6hf-6m8v): sdk-npm-10.9.9; brace-expansion: Zero-step sequence causes process hang and memory exhaustion; affected >=2.0.0 <2.0.3; patches 5.0.5, 3.0.2, 2.0.3, 1.1.13; unresolved.
- [GHSA-3v7f-55p6-f55p](https://github.com/advisories/GHSA-3v7f-55p6-f55p): sdk-npm-10.9.9; Picomatch: Method Injection in POSIX Character Classes causes incorrect Glob Matching; affected >=4.0.0 <4.0.4; patches 4.0.4, 3.0.2, 2.3.2; unresolved.
- [GHSA-c2c7-rcm5-vvqj](https://github.com/advisories/GHSA-c2c7-rcm5-vvqj): sdk-npm-10.9.9; Picomatch has a ReDoS vulnerability via extglob quantifiers; affected >=4.0.0 <4.0.4; patches 4.0.4, 3.0.2, 2.3.2; unresolved.

## Rust audit and runtime exposure

Initial vulnerabilities: **2**; final vulnerabilities: **0**.

| ID | Chain / installed | Fix / precondition |
|---|---|---|
| [RUSTSEC-2026-0258](https://rustsec.org/advisories/RUSTSEC-2026-0258.html) | direct reqwest 0.11.27 → hyper 0.14.32 → h2 0.3.27 | reqwest 0.12.28 / h2 0.4.20 (patch >=0.4.16); a peer sends unlimited empty HTTP/2 DATA frames to an undrained stream. No patched h2 0.3 branch exists. |
| [RUSTSEC-2026-0285](https://rustsec.org/advisories/RUSTSEC-2026-0285.html) | tauri-plugin-updater 2.10.1 → reqwest 0.13.4 → rustls 0.23.41 | targeted rustls 0.23.45 / webpki 0.103.15; malformed TLS 1.3 encryption-level boundaries. Transcript remains authenticated; not a claim of arbitrary network handshake forgery. |

reqwest 0.12 is the smallest parent migration removing unpatched h2 0.3. Existing
Client/get/json/download code compiles unchanged and json/default TLS features
are preserved. No installer/unlocker business logic was modified or exercised
against games. Both dependencies are normal Rust dependencies compiled/linked
as needed into the application. Inspector startup/IPC skips legacy networking and
the Frame updater is disabled, but the dependency audit was still remediated.
Rustls changes also protect existing legacy updater builds.

Seven warnings remain explicitly disclosed:

- RUSTSEC-2024-0370 proc-macro-error 1.0.4: build-time unmaintained macro
  dependency through GTK/Tauri; no compatible maintained replacement in that
  fixed upstream stack.
- RUSTSEC-2025-0075 unic-char-range, -0081 unic-char-property, -0080 unic-common,
  -0100 unic-ucd-ident, -0098 unic-ucd-version (0.9.0): unmaintained Unicode
  components in Tauri URL/HTML processing dependencies. Compiled consumers are
  runtime/build dependent; “unmaintained” is not automatically a CVE.
- RUSTSEC-2024-0429 glib 0.18.5: VariantStrIter unsound mutable C out-pointer,
  fixed >=0.20.0. Tauri/Wry/GTK use the 0.18 ABI family. Project and reviewed
  Tauri/Wry source contain no observed call to array_iter_str/VariantStrIter;
  that is a reachability observation, not proof of universal non-exposure.
  Stack-wide major upgrade or a reviewed upstream backport/vendor maintenance
  would be needed; no silent warning ignore or casual GTK ABI migration occurred.

rustls-pemfile 1.0.4's initial unmaintained warning disappeared with reqwest 0.11.
The warning list does not become “zero advisories” merely because cargo-audit's
vulnerability count is zero. The audit tool itself and OS SDK closure also need
normal independent maintenance.

## CI security review

All five workflows pass actionlint 1.7.7 after fixing the legacy Node 16
GitHub-script actions. Every action now uses an actual resolved commit SHA;
Swatinem's annotated v2.8.1 tag was peeled to its **commit** f13886b9…, not used
as a tag-object pin. GitHub-script v8 uses Node 24. Nix installer v23 is pinned.
New security-sensitive third-party archive downloads use immutable SHA256 pins.
The legacy x86 helper now consumes the same appimagetool pin rather than a moving
unverified continuous binary.

| Workflow | Events / trust | Permissions / boundary |
|---|---|---|
| steam-frame-tests.yml | path-filtered pull_request + manual; untrusted code runs on hosted disposable x86 runner | contents:read, persist-credentials:false, no secrets, no Docker/socket/cache, pinned tools, patched npm |
| steam-frame-release.yml | manual only; hosted x86 or explicit isolated self-hosted label | contents:read, no keys/publication; privileged binfmt confined to a pinned provisioning image; canonical release implementation; fresh SDK/container; allowlisted artifacts 14d, failure logs 7d |
| steam-frame-signing-preparation.yml | manual; producer must be successful manual exact-source release workflow run | contents:read/actions:read; verify hash/source/builder/provenance before ephemeral signing; no production keys; no artifact execution; public rehearsal outputs only 7d |
| test-build.yml | manual legacy x86 build | now contents:read, no production secrets, credentials not persisted; immutable actions/Node/Rust/appimagetool; no publication |
| build.yml | manual **main only**, explicitly labelled publishing | legacy contents:write and existing production signing secrets remain; package.nix commit/push, separate main checkout and publication remain legacy behavior, not approved for Frame validation |

No pull_request_target, automatic tag/release event or secret-enabled PR job is
introduced. PR code can execute arbitrary code by design, so it must stay on an
unprivileged disposable runner; private fixture/secrets/self-hosted machines must
never be attached to fork PR builds. Frame Docker builds are manual trusted-source
operations on disposable/isolated controllers. Docker controller integrity is an
assumption; SDK rootfs/source/inventory verification is not cryptographic remote
attestation. No build/sign job shared cache is used in the Frame release path;
legacy manual cache is separate and is not inherited by Frame jobs.

Artifact poisoning mitigations: producer workflow/event/success/head identity,
run-scoped download, checksum plus source snapshot check against exact checkout,
frozen builder verification, no execution of downloaded artifact, new regular-file
and symlink-directory rejection, allowlisted payloads, and explicit no-hardware
semantics. JSON remains unsigned; these checks do not independently authenticate
a compromised trusted build job. Attestations/OIDC remain intentionally disabled.
Production signing must use an authorized protected environment and independent
artifact approval; it cannot be attached to the general build or PR job.

A bounded in-memory 16 MiB tar parser probe (16,397 compressed bytes, no file
extraction) confirms old SDK tar 6.2.1 accepts the input while both patched
7.5.22 copies reject it at the default ratio limit 1000. This measures that patch's
behavior, not a claim of unlimited extraction resource safety.

A malformed/null provenance report reproduced exit 1 with a traceback. The CI
CLI now returns operational exit 2 and clean stderr for invalid input types;
regressions cover null, array and invalid filename shapes. Strict SDK execution
also uses the approved /opt Node/Rust paths, no login shell or home-bin prefix,
and clears shell startup injection variables. Preflight rejects compiler/loader/
Node/shell runtime overrides before container execution; development mode records
only override names, never potentially secret values. Provenance records those
names and official verification rejects them. This prevents a mutable home wrapper
from silently replacing the frozen compiler. A trusted Docker controller and
reviewed source/cache remain necessary; no remote attestation is claimed.

New tests cover symlink payload/root/log rejection, pinned npm extraction/checksum/
version/path escapes/license/executable links, failure propagation, security floors,
read-only command whitelist, all workflow action pins, and legacy publication's
main guard. The legacy publishing workflow still needs a separately authorized
production-environment/source-locking review; this task did not configure repository
settings or invoke it. No newly introduced Frame path can call that workflow.

## Complete accumulated worktree review

All changed and untracked source files since baseline were inspected. No unrelated
workspace file was deleted. The exact proposed inventory is emitted to
`tools/android-steam-proxy/build/security-review/proposed-commit-files.txt` and
`proposed-commit-inventory.json`; the final handoff retains these and a binary git
patch/status. No staging command was executed.

- Required source: analyzer/runtime evidence separation, function-only generator,
  CLI/backend/read-only inspector, release orchestrator/guards, pinned LLVM,
  SDK/controller/bootstrap/provenance/rehearsal tools; frontend/types/styles.
- Required tests: Python ABI/loader/parser/evidence/release/CI/bootstrap/security
  regressions, Rust command/ACL/probe tests, rendering/native GUI utilities.
- Required docs/definitions: release/CI/security notes, research logs clearly dated,
  five workflows, Dockerfile/source pins/apt inventory, small evidence JSON and this
  reviewed dependency inventory. No AppImage/SDK binary is proposed for commit.
- Ignore/retain locally: proxy build outputs, source captures, providers/APKs,
  AppDirs, release artifacts/logs, tool/NDK archives, npm modules, Rust targets,
  dist and caches, external handoff ZIPs. These are neither source nor CI payloads.
- Five core files are already tracked in the **baseline** and remain untouched.
  They are excluded from source snapshots/handoffs. Their removal/history review
  is separate work requiring authorization; this review does not erase them.

No new private keys, access tokens, credentials, APK/provider binaries or oversized
build artifacts were found in proposed commit inputs. Public Tauri updater keys,
API names, SHA256 provider identities and disposable public test placeholders are
not private key material. Historical source-evidence local paths/addresses are
retained as observations; release/SSH runtime defaults do not hardcode a private
Frame IP. SDK/container/DNS examples are explicitly configurable. Source executable
bits are correct for direct shell entrypoints; Python utilities invoked by python3
need not be executable. Linux/QEMU test utilities are referenced by suite/build/docs.
MIT project licensing and private LLVM/npm third-party license notices are preserved.
New security evidence is JSON/text, not an accidental binary dependency.

Legacy mutations are limited to a security-compatible HTTP dependency migration,
workflow pinning/no-secret Test Build/main-only publication guard, and prior close
permission regression fix. Frame-only entry/CSP/updater/ACL changes are scoped to
its separate configuration/feature. No installation/unlocker behavior was added.

## Tests, frozen release and hardware measurement

Local full regression baseline after review additions: **305 Python tests**, zero
skips; Rust **53**, zero ignored; rendering **8**; TypeScript/Vite production build,
actionlint across all five workflows, and git diff --check pass. The canonical
release pipeline repeats the complete gate in the freshly rebuilt strict SDK,
with CARGO_PROFILE_DEV_DEBUG=0 / TEST_DEBUG=0 / INCREMENTAL=0.

The first security candidate was actually measured before the final CI operational
hardening: 163,678,728 bytes, SHA256
`e35da8a0dce01ebf48b9af3dac7858c742a86f3bfe96d3a7ad5c4c3e4025d89c`,
source snapshot `8bfe135333816383be3581dd0928f683f1c78cf15b34a9a9a5973a47af1b4e48`.
It passed 300 Python / 53 Rust / 8 rendering, all six captured games, and exact
Frame 15/15 GUI / 5/5 backend on 2026-10-08. The final operational hardening
adds five tests and is revalidated in the final repeated candidates below; the
first hash must not be presented as the final artifact hash.

Final measured release manifests are generated under
`tools/android-steam-proxy/build/releases/security-reviewed/` and `security-repeat/`:
AppImage, SHA256SUMS, source-inputs.json, package inventory, AppDir inventory,
private LLVM identity, test summary, captures and unsigned in-toto provenance.
To avoid a self-referential source-hash/artifact-hash cycle, final artifact hash,
size, image ID, reproducibility and native Frame measurements are recorded in
**STEAM_FRAME_SECURITY_HANDOFF.md** outside this source checkout and those exact
release manifests. This source report freezes before packaging; final evidence
must not be inferred from historical accepted artifact 4c676005….

One intermediate attempt (`security-final/`) failed closed at rendering because
the operator started npm ci in a second container sharing node_modules while the
first pipeline was testing. It produced a failed manifest and no successful
artifact. Dependency preparation and complete builds are now serialized; the
failed evidence remains intact. This was orchestration misuse, not a suppressed
product test or a justification to weaken gates.

Both complete builds must pass static packaging gates (AArch64 ELFs, all private
LLVM/license payloads, no ten-family display conflicts, WebKit helper staging,
extraction inventory parity, production assets/close ACL/CSP/inspector-only startup,
no captures/keys/bloat). The compare path requires same source/SDK/epoch/tool pins
and byte-identical AppImage/AppDir inventory. Exact Frame smoke runs only the
read-only inspector/backend, never legacy startup or installed-game mutation.
Missing hardware/captures are reported as not performed; historical Bionic proxy
validation remains a separate provider/toolchain-specific state.

Six captured regressions are rerun through this exact packaged ARM64 reader:
Walkabout fixed-compatible/exit 0 with “Compatible for observed static consumers”;
Job fixed-incompatible/exit 1; VRChat, VAIL (direct import evidence), Into Black,
Dungeons of Eternity remain fixed-incompatible. Job's generated function proxy
hardware evidence does not change fixed-proxy compatibility. Its 209 non-function
exports remain omitted/unrequired for observed consumers; no complete ABI clone
is claimed. Real split-install evidence remains optional; synthetic tests pass.
No new Bionic proxy injection or API forwarding experiment is needed for dependency
changes. Exact-artifact native GUI/backend smoke is conditional on actual reachability
and running-state probes; production contexts are never started/stopped.

## Proposed commit structure and hosted CI preparation

Suggested test branch: `test/steam-frame-inspector-security-ci`.
Recommended reviewable commits (execute only with separate authorization):

1. Read-only analyzer/backend, provider-specific function generator, LLVM resource
   preparation and CLI/tests/docs/evidence; preserve fixed-proxy semantics.
2. Native read-only inspector UI/ACL/distribution feature and its validation tests.
3. Canonical release pipeline, frozen SDK/controller locks, CI verification,
   signing rehearsal, workflows/docs and release tests.
4. Dependency patch locks, pinned npm bootstrap, CI/security hardening and this
   security review/inventory. Some files span groups: use reviewed patch hunks;
   a single cohesive commit from the exact full inventory is also acceptable.

No git add/commit/push has been executed. An exact future single-commit sequence
from the reviewed checkout (after inventory/hash and remote authorization) is:

```bash
git switch -c test/steam-frame-inspector-security-ci
python3 - <<'PYCOMMIT'
from pathlib import Path
import subprocess
files=Path('tools/android-steam-proxy/build/security-review/proposed-commit-files.txt').read_text().splitlines()
subprocess.run(['git','add','--',*files],check=True)
PYCOMMIT
git diff --cached --check
git diff --cached --stat
git commit -m "Add validated read-only Steam Frame inspector release pipeline and security review"
git push -u AUTHORIZED_REMOTE test/steam-frame-inspector-security-ci
```

Replace AUTHORIZED_REMOTE with an explicitly authorized write-capable remote;
no owner fork/repository/settings were created here. Re-run current tests before
push if code changes. Open a PR only after authorization; path filters trigger
Steam Frame tests. Dispatch Frame release validation with optional reproducibility,
then the **ephemeral** signing rehearsal only. Do not dispatch the legacy main
publishing workflow. Expected workflow permissions are read-only contents and
rehearsal actions:read, plus Docker provisioning privilege limited to manual
isolated release jobs; no attestation/write publication/key permission is needed.

Read-only GitHub CLI inspection confirms the current account has **no push/admin
permission** on the upstream repository. Actions settings and self-hosted runner
APIs return 403; branch protection returns 404 (not proof that protection is
absent). Owner confirmation of Actions enablement/action policies/artifact retention,
write access/fork strategy and hosted runner availability is needed. Hosted disk
space/runtime remain unmeasured (large SDK; isolated 30 GB builder recommended).
No successful GitHub Actions execution is claimed without an authorized push.
[GitHub's manual-run documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)
requires the workflow definition to exist on the default branch and repository
write access. New manual workflows on a test branch alone are not dispatchable;
a maintainer-approved default-branch registration (or an authorized fork whose
default branch contains them) is needed before --ref testing. No automatic full
release-on-PR trigger was added to work around that authorization boundary.
The legacy package.nix npmDeps hash predates this lockfile update; Nix/prefetch
is unavailable locally. Its existing legacy publication job recalculates that
hash, but standalone Nix packaging still needs a separate authorized/tool-provisioned
refresh and validation. Nix is not a Frame build dependency; no fabricated Nix
build/hash result is reported.

Next milestone: authorized source commit/test-branch push and hosted non-publishing
CI verification, followed by upstream residual dependency/toolchain remediation
and an explicit protected signing/distribution review. Neither production signing
nor public distribution is authorized by this report.
