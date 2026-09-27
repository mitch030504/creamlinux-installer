#!/system/bin/sh
# Run only from a newly staged /data/local/tmp POC directory.
set -eu
cd "$(dirname "$0")"
base=$(pwd -P)
export LD_LIBRARY_PATH="$base/mock${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
./abi_test "$base/mock/libsteam_api.so" "$base/mock/libmock_original.so"
./abi_static
expect_failure() {
    label=$1
    pattern=$2
    shift 2
    set +e
    "$@" > "$base/$label.log" 2>&1
    status=$?
    set -e
    cat "$base/$label.log"
    if [ "$status" -ne 127 ] || ! grep -F "$pattern" "$base/$label.log" >/dev/null; then
        echo "FAIL $label: expected exit 127 and '$pattern', got $status" >&2
        exit 1
    fi
    echo "PASS $label (exit 127)"
}
unset CREAMLINUX_ORIGINAL_STEAM_API
expect_failure missing_env 'absolute original path required' ./mock_load_probe "$base/mock/libsteam_api.so"
expect_failure relative_path 'absolute original path required' ./mock_load_probe "$base/mock/libsteam_api.so" relative.so
expect_failure nonexistent 'cannot stat original' ./mock_load_probe "$base/mock/libsteam_api.so" "$base/does-not-exist.so"
expect_failure self_load 'original is proxy itself' ./mock_load_probe "$base/mock/libsteam_api.so" "$base/mock/libsteam_api.so"
expect_failure missing_symbols 'missing function' ./mock_load_probe "$base/mock/libsteam_api.so" "$base/mock/libempty.so"
expect_failure dependency_target 'target is not in explicit original' ./mock_load_probe "$base/mock/libsteam_api.so" "$base/mock/libdependency.so"
echo 'PASS standalone mock ABI and six loader rejection cases; no real Steam API loaded'
