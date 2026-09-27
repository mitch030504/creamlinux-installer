#!/system/bin/sh
# Only run from a disposable, freshly staged POC directory in a dev context.
set -eu
if [ "$#" -gt 1 ]; then echo 'usage: sh run_parity.sh [new-results-name]' >&2; exit 2; fi
out=${1:-parity-results}
case "$out" in ''|.|..|*[!A-Za-z0-9_-]*) echo 'results name must be a simple directory name' >&2; exit 2;; esac
if [ -n "${LD_PRELOAD:-}" ]; then echo 'STOP: LD_PRELOAD must be unset' >&2; exit 2; fi
cd "$(dirname "$0")"
base=$(pwd -P)
# Exclusive creation prevents stale records from masquerading as new results.
mkdir "$out"
if ! sha256sum -c SHA256SUMS > "$out/bundle-check.log" 2>&1; then
    cat "$out/bundle-check.log" >&2
    echo 'STOP: bundle verification failed; no parity calls attempted' >&2
    exit 1
fi
cp reference.sha256 "$out/reference.sha256"
if ! sha256sum -c reference.sha256 > "$out/reference-check.log" 2>&1; then
    cat "$out/reference-check.log" >&2
    echo 'STOP: original is not the reviewed reference; no parity calls attempted' >&2
    exit 1
fi
sha256sum real/libsteam_api_original.so > "$out/original-before.sha256"
run_mode() {
    mode=$1
    shift
    set +e
    env LD_LIBRARY_PATH="$base/runtime" "$base/parity_probe" "$mode" "$@" \
        > "$out/$mode.stdout" 2> "$out/$mode.stderr"
    status=$?
    set -e
    printf '%s\n' "$status" > "$out/$mode.exit"
    cat "$out/$mode.stdout"
    cat "$out/$mode.stderr" >&2
    if [ "$status" -ne 0 ]; then
        sha256sum real/libsteam_api_original.so > "$out/original-after.sha256"
        echo "STOP: $mode exited $status; preserve logs; do not synthesize Steam setup" >&2
        exit "$status"
    fi
}
run_mode direct "$base/real/libsteam_api_original.so"
run_mode proxy "$base/real/libsteam_api.so" "$base/real/libsteam_api_original.so"
sha256sum real/libsteam_api_original.so > "$out/original-after.sha256"
if ! cmp -s "$out/original-before.sha256" "$out/original-after.sha256"; then
    echo 'STOP: original changed during run; results are inconclusive' >&2
    exit 1
fi
printf 'Captured both modes in %s/%s; compare with compare_parity.py on the host.\n' "$base" "$out"
