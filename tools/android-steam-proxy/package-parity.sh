#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
# Preserve the previous bundle and all existing ABI/loader sources and scripts.
./build-parity.sh
python3 tests/verify.py
ndk_path=${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-/home/diemitchell/.local/share/android-ndk/android-ndk-r30}}
reference=/home/diemitchell/creamlinux-arm64/reference/walkabout-libsteam_api.so
stage=$(mktemp -d "$PWD/build/frame-parity-bundle.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT
mkdir -p "$stage/mock" "$stage/real" "$stage/runtime" "$stage/parity-evidence"
cp build/abi_test build/abi_static build/load_probe build/mock_load_probe build/run_android.sh "$stage/"
cp build/mock/libsteam_api.so build/mock/libmock_original.so build/mock/libempty.so build/mock/libdependency.so "$stage/mock/"
cp build/real/libsteam_api.so "$stage/real/"
cp "$reference" "$stage/real/libsteam_api_original.so"
cp "$ndk_path/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so" "$stage/runtime/"
cp build/parity_probe tests/run_parity.sh tests/compare_parity.py "$stage/"
cp build/parity/reference.sha256 "$stage/"
cp build/parity/static-verification.json build/parity/reference-disassembly.txt build/parity/toolchain.txt "$stage/parity-evidence/"
cp FRAME.md README.md PARITY.md "$stage/"
cp build/static-verification.json build/runtime-verification.json "$stage/"
(cd "$stage" && sha256sum -c reference.sha256)
(cd "$stage" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
tar -C "$stage" -czf build/android-steam-proxy-parity-poc.tar.gz .
sha256sum build/android-steam-proxy-parity-poc.tar.gz
