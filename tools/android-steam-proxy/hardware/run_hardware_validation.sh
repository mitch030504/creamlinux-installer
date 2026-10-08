#!/system/bin/sh
# Standalone test processes only, inside the dedicated Lepton test context.
set -eu
fail() { echo "FAIL $*" >&2; exit 1; }
usage() { echo "usage: $0 mock | weak | resolve /data/local/tmp/creamlinux-target-proxy/original-provider.so | all /data/local/tmp/creamlinux-target-proxy/original-provider.so" >&2; exit 2; }
stage=${1:-}
case "$stage" in
    mock|weak) [ "$#" -eq 1 ] || usage ;;
    resolve|all) [ "$#" -eq 2 ] || usage ;;
    *) usage ;;
esac
cd "$(dirname "$0")"
base=$(pwd -P)
[ "$base" = /data/local/tmp/creamlinux-target-proxy ] || fail "run only from /data/local/tmp/creamlinux-target-proxy"
# Do not inherit game/preload search paths, or an original-provider setting.
unset LD_PRELOAD CREAMLINUX_ORIGINAL_STEAM_API
export LD_LIBRARY_PATH="$base:$base/mock:$base/weak"
[ -f SHA256SUMS ] && [ ! -L SHA256SUMS ] || fail "missing checksum manifest"
while read -r digest member; do
    case "$member" in
        ''|/*|*..*) fail "unsafe checksum member" ;;
    esac
    [ -f "$member" ] && [ ! -L "$member" ] || fail "missing/nonregular bundle member: $member"
    canonical=$(readlink -f "$member") || fail "cannot canonicalize $member"
    [ "$canonical" = "$base/$member" ] || fail "bundle member outside expected location: $member"
done < SHA256SUMS
[ ! -L logs ] || fail "logs must not be a symlink"
mkdir -p logs
for logfile in logs/*.log; do
    [ ! -L "$logfile" ] || fail "log file must not be a symlink: $logfile"
done
sha256sum -c SHA256SUMS > logs/checksums.log 2>&1 || { cat logs/checksums.log >&2; fail "bundle checksums"; }
echo 'PASS bundle checksums'
run_logged() {
    label=$1
    shift
    if "$@" > "logs/$label.log" 2>&1; then
        grep -E '^(PASS|FAIL|steam proxy:)' "logs/$label.log" || true
    else
        status=$?
        cat "logs/$label.log" >&2
        fail "$label (exit $status)"
    fi
}
expect_failure() {
    label=$1
    pattern=$2
    shift 2
    status=0
    "$@" > "logs/$label.log" 2>&1 || status=$?
    if [ "$status" -ne 127 ] || ! grep -F "$pattern" "logs/$label.log" >/dev/null; then
        cat "logs/$label.log" >&2
        fail "$label: expected exit 127 and '$pattern', got $status"
    fi
    echo "PASS $label (exit 127)"
}
check_provider() {
    supplied=$1
    [ "$supplied" = "$base/original-provider.so" ] || fail "copy provider separately to $base/original-provider.so"
    [ -f "$supplied" ] && [ ! -L "$supplied" ] || fail "missing/nonregular real provider"
    [ "$(readlink -f "$supplied")" = "$base/original-provider.so" ] || fail "provider outside test directory"
    actual=$(sha256sum "$supplied") || fail "provider checksum unavailable"
    actual=${actual%% *}
    expected=345f62386d8bd342461195cf4f40214a2f2e0b73aa60a45bf5b683a78fe8c700
    if [ "$actual" != "$expected" ]; then
        [ "${CREAMLINUX_ALLOW_PROVIDER_SHA_MISMATCH:-0}" = 1 ] || fail "real-provider checksum: expected $expected; got $actual"
        echo "DEVELOPMENT OVERRIDE real-provider checksum: $actual" | tee logs/provider-checksum.log
    else
        echo "PASS real-provider checksum: $actual" | tee logs/provider-checksum.log
    fi
}
mock_stage() {
    run_logged mock-abi ./abi_test "$base/libsteam_api.so" "$base/mock/libmock_original.so"
    grep -F 'PASS 11156 ABI checks' logs/mock-abi.log >/dev/null || fail "unexpected ABI count"
    grep -F 'resolved 1156 functions' logs/mock-abi.log >/dev/null || fail "unexpected target count"
    expect_failure missing_env 'absolute original path required' ./mock_load_probe "$base/libsteam_api.so"
    expect_failure relative_path 'absolute original path required' ./mock_load_probe "$base/libsteam_api.so" relative.so
    expect_failure nonexistent 'cannot stat original' ./mock_load_probe "$base/libsteam_api.so" "$base/does-not-exist.so"
    expect_failure self_load 'original is proxy itself' ./mock_load_probe "$base/libsteam_api.so" "$base/libsteam_api.so"
    expect_failure missing_symbols 'missing function' ./mock_load_probe "$base/libsteam_api.so" "$base/mock/libempty.so"
    expect_failure dependency_target 'target is not in explicit original' ./mock_load_probe "$base/libsteam_api.so" "$base/mock/libdependency.so"
    expect_failure dependency_failure 'dlopen original' ./mock_load_probe "$base/libsteam_api.so" "$base/mock/libbroken_dependency.so"
    expect_failure missing_weak 'missing function: @MISSING_WEAK@' ./mock_load_probe "$base/libsteam_api.so" "$base/mock/libmissing_weak.so"
    echo 'PASS mock: 1156 targets; 11156 ABI checks; 8 loader rejections'
}
weak_stage() {
    run_logged weak-dynsym ./binding_probe "$base/libsteam_api.so"
    for mode in baseline strong-first strong-middle strong-late; do
        run_logged "weak-$mode" ./weak_probe "$mode" "$base/libsteam_api.so" "$base/mock/libmock_original.so" "$base/weak/libstrong.so" "$base/weak/libconsumer.so"
    done
    echo 'PASS weak: 21 WEAK, 1135 GLOBAL; 4 Bionic load-scope cases; 420 checks'
}
resolve_stage() {
    # Only this executable loads the real provider. It never calls a target.
    run_logged resolve ./resolve_probe "$1"
    grep -F 'PASS resolve: 1156/1156 targets; failures=0; zero Steam API calls' logs/resolve.log >/dev/null || fail "unexpected resolution count"
}
case "$stage" in
    resolve|all) check_provider "$2" ;;
esac
case "$stage" in
    mock) mock_stage ;;
    weak) weak_stage ;;
    resolve) resolve_stage "$2" ;;
    all) mock_stage; weak_stage; resolve_stage "$2" ;;
esac
echo "PASS hardware stage=$stage (logs: $base/logs)"
