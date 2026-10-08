#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
ndk_path=${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-/home/diemitchell/.local/share/android-ndk/android-ndk-r30}}
toolchain="$ndk_path/toolchains/llvm/prebuilt/linux-x86_64/bin"
cc="$toolchain/aarch64-linux-android21-clang"
test -x "$cc"
mkdir -p build/parity
"$cc" --version > build/parity/toolchain.txt
cat "$ndk_path/source.properties" >> build/parity/toolchain.txt
"$cc" -std=c11 -O2 -g -Wall -Wextra -Werror -fvisibility=hidden \
    -fno-omit-frame-pointer -fPIE -pie -Wl,-z,now,-z,relro,-z,noexecstack \
    -Wl,-z,max-page-size=16384 src/parity_probe.c -ldl -o build/parity_probe
python3 tests/verify_parity.py "$toolchain"
python3 tests/test_parity.py
