#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
python3 tests/verify.py
ndk_path=${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-/home/diemitchell/.local/share/android-ndk/android-ndk-r30}}
reference=/home/diemitchell/creamlinux-arm64/reference/walkabout-libsteam_api.so
stage=build/frame-bundle
mkdir -p "$stage/mock" "$stage/real" "$stage/runtime"
cp build/abi_test build/abi_static build/load_probe build/mock_load_probe build/run_android.sh "$stage/"
cp build/mock/libsteam_api.so build/mock/libmock_original.so build/mock/libempty.so build/mock/libdependency.so "$stage/mock/"
cp build/real/libsteam_api.so "$stage/real/"
# Byte-for-byte disposable reference copy; SONAME and contents are not patched.
cp "$reference" "$stage/real/libsteam_api_original.so"
cp "$ndk_path/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so" "$stage/runtime/"
cp FRAME.md README.md "$stage/"
cp build/static-verification.json build/runtime-verification.json "$stage/"
(cd "$stage" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
tar -C "$stage" -czf build/android-steam-proxy-poc.tar.gz .
sha256sum build/android-steam-proxy-poc.tar.gz
