#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
ndk_path=${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-/home/diemitchell/.local/share/android-ndk/android-ndk-r30}}
toolchain="$ndk_path/toolchains/llvm/prebuilt/linux-x86_64/bin"
cc="$toolchain/aarch64-linux-android21-clang"
test -x "$cc"
mkdir -p build
"$cc" --version > build/toolchain.txt
cat "$ndk_path/source.properties" >> build/toolchain.txt
python3 generate.py
ln -sfn "$toolchain/llvm-objdump" build/llvm-objdump
flags=(-O2 -g -Wall -Wextra -Werror -fvisibility=hidden -fno-omit-frame-pointer -Isrc)
shared=(-shared -fPIC -Wl,-z,now,-z,relro,-z,noexecstack -Wl,--no-undefined)
"$cc" "${flags[@]}" "${shared[@]}" src/mock.c build/mock/pads.c -Wl,-soname,libmock_original.so -Wl,--version-script=build/mock/exports.map -o build/mock/libmock_original.so
for kind in mock real; do
  "$cc" "${flags[@]}" "${shared[@]}" -I"build/$kind" src/proxy.c "build/$kind/stubs.S" -ldl -Wl,-soname,libsteam_api.so -Wl,--version-script="build/$kind/exports.map" -o "build/$kind/libsteam_api.so"
done
"$cc" "${flags[@]}" -fPIE -pie tests/abi_test.c -ldl -o build/abi_test
"$cc" "${flags[@]}" -fPIE -pie -Ibuild/real src/load_probe.c -ldl -o build/load_probe
"$cc" "${flags[@]}" -fPIE -pie -Ibuild/mock src/load_probe.c -ldl -o build/mock_load_probe
# Same Android compiler, C ABI cases and generated stubs; no dynamic-loader claim.
"$cc" "${flags[@]}" -include build/mock/rename.h -c src/mock.c -o build/mock/static_mock.o
"$cc" "${flags[@]}" -include build/mock/rename.h -c build/mock/pads.c -o build/mock/static_pads.o
"$cc" "${flags[@]}" -static -DSTATIC_ABI -Ibuild/mock tests/abi_test.c build/mock/static_bind.c build/mock/stubs.S build/mock/static_mock.o build/mock/static_pads.o -o build/abi_static
"$cc" "${flags[@]}" "${shared[@]}" tests/empty.c -Wl,-soname,libempty.so -o build/mock/libempty.so
"$cc" "${flags[@]}" "${shared[@]}" tests/empty.c -Lbuild/mock -Wl,--no-as-needed -lmock_original -Wl,-soname,libdependency.so -o build/mock/libdependency.so
cp tests/run_android.sh build/run_android.sh
python3 tests/verify.py
