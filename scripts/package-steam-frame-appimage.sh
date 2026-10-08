#!/usr/bin/env bash
# ==============================================================================
# package-steam-frame-appimage.sh
#
# Reproducible packaging helper for Steam Frame (ARM64 / aarch64) AppImages.
#
# ------------------------------------------------------------------------------
# WHY THESE LIBRARIES ARE REMOVED:
#
# The Steam Frame is an ARM64 standalone VR headset running SteamOS with the
# Gamescope / Wayland compositor and Qualcomm Adreno / Turnip Mesa drivers.
#
# When Tauri packages an AppImage, it bundles shared libraries discovered in the
# build environment. Bundling the following display and windowing libraries
# causes critical runtime issues on Steam Frame:
#
#   1. libwayland-client.so.0
#   2. libwayland-cursor.so.0
#   3. libwayland-egl.so.1
#   4. libwayland-server.so.0
#      -> Bundled Wayland client/server/egl libraries conflict with the host
#         Gamescope compositor sockets, causing protocol errors or crashes in
#         wl_display_connect() and Mesa EGL initialization.
#
#   5. libxkbcommon.so.0
#      -> Bundled XKB library conflicts with SteamOS host keymap definitions
#         and host compositor input handling.
#
#   6. libxcb-randr.so.0
#   7. libxcb-render.so.0
#   8. libxcb-shm.so.0
#   9. libXau.so.6
#  10. libXdmcp.so.6
#      -> Bundled XCB / X11 transport libraries conflict with host Xwayland
#         connections and shared memory access.
#
# Removing these 10 bundled libraries from `usr/lib` in the AppDir forces the
# dynamic linker (ld.so) to resolve them against SteamOS's host system libraries.
# The host libraries are tightly coupled with SteamOS's compositor, kernel, and
# GPU stack, allowing CreamLinux to initialize cleanly without modifying the
# read-only SteamOS system image itself.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Default ARM64 AppDir path produced by Tauri build
DEFAULT_APPDIR="${REPO_ROOT}/src-tauri/target/release/bundle/appimage/Creamlinux.AppDir"
APPDIR="${1:-${DEFAULT_APPDIR}}"

echo "==================================================================="
echo " Steam Frame AppImage Packaging Helper"
echo "==================================================================="
echo "Target AppDir: ${APPDIR}"

# 1. Fail safely if AppDir is missing
if [ ! -d "${APPDIR}" ]; then
  echo "ERROR: Target AppDir does not exist: ${APPDIR}" >&2
  echo "Please build the AppDir first (e.g., via 'npm run tauri build') or specify a valid AppDir path." >&2
  exit 1
fi

LIBDIR="${APPDIR}/usr/lib"
if [ ! -d "${LIBDIR}" ]; then
  echo "ERROR: Target AppDir does not contain 'usr/lib': ${LIBDIR}" >&2
  exit 1
fi

# Tauri resolves Linux resources under usr/lib/<product-name>.
READER_RESOURCE="${LIBDIR}/Creamlinux/compatibility/runtime"
python3 "${SCRIPT_DIR}/prepare-steam-frame-runtime.py" \
  --source "${REPO_ROOT}/src-tauri/resources/compatibility/runtime" \
  --output "$READER_RESOURCE" --restore-appdir-payloads
python3 "${SCRIPT_DIR}/prepare-steam-frame-runtime.py" --source "$READER_RESOURCE" --verify-only

# 2. Targeted libraries that must be excluded to rely on SteamOS host libraries
TARGET_LIBS=(
  "libwayland-client.so.0"
  "libwayland-cursor.so.0"
  "libwayland-egl.so.1"
  "libwayland-server.so.0"
  "libxkbcommon.so.0"
  "libxcb-randr.so.0"
  "libxcb-render.so.0"
  "libxcb-shm.so.0"
  "libXau.so.6"
  "libXdmcp.so.6"
)

echo ""
echo "Cleaning bundled Wayland/XCB/XKB libraries from AppDir/usr/lib..."
echo "-------------------------------------------------------------------"

removed_count=0

for lib in "${TARGET_LIBS[@]}"; do
  # Match exact filename as well as versioned library variants (e.g. libfoo.so.0.1.2)
  # while strictly preserving unrelated libraries.
  base_pattern="${lib%.so*}"
  
  # Check the full bundled library tree, including nested plugin directories.
  matched_files=$(find "${LIBDIR}" \( -type f -o -type l \) -name "${base_pattern}.so*" 2>/dev/null)
  
  if [ -n "${matched_files}" ]; then
    while IFS= read -r file; do
      [ -e "${file}" ] || [ -L "${file}" ] || continue
      fname="$(basename "${file}")"
      rm -f "${file}"
      echo "  [REMOVED] ${fname}"
      removed_count=$((removed_count + 1))
    done <<< "${matched_files}"
  else
    echo "  [SKIPPED] ${lib} (already absent)"
  fi
done

echo "-------------------------------------------------------------------"
echo "Removed ${removed_count} conflicting library file(s)."

# Verify unrelated libraries remain untouched
remaining_libs=$(find "${LIBDIR}" -maxdepth 1 -name "*.so*" 2>/dev/null | wc -l)
echo "Verified: ${remaining_libs} unrelated libraries remain untouched in ${LIBDIR}."

# 3. Optional packaging with appimagetool if available
APPIMAGETOOL="${APPIMAGETOOL:-}"
if [ -z "${APPIMAGETOOL}" ]; then
  if [ -x "${REPO_ROOT}/../tools/appimagetool-x86_64.AppImage" ]; then
    APPIMAGETOOL="${REPO_ROOT}/../tools/appimagetool-x86_64.AppImage"
  elif command -v appimagetool >/dev/null 2>&1; then
    APPIMAGETOOL="$(command -v appimagetool)"
  fi
fi

RELEASE_VERSION=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "${REPO_ROOT}/package.json")
OUTPUT_NAME="Creamlinux_${RELEASE_VERSION}_steam-frame-inspector_aarch64.AppImage"
OUTPUT_DIR="${REPO_ROOT}/.."
OUTPUT_PATH="${2:-${OUTPUT_DIR}/${OUTPUT_NAME}}"

if [ "${FRAME_PACKAGE_PREPARE_ONLY:-0}" = "1" ]; then
  echo "AppDir prepared; artifact creation was explicitly not requested."
  exit 0
fi

if [ -n "${APPIMAGETOOL}" ] && [ -x "${APPIMAGETOOL}" ]; then
  echo ""
  echo "Packaging final Steam Frame ARM64 AppImage using ${APPIMAGETOOL}..."
  if [ -e "${OUTPUT_PATH}" ]; then
    echo "ERROR: Output already exists; choose a new output path: ${OUTPUT_PATH}" >&2
    exit 1
  fi
  RUNTIME_FILE="${FRAME_APPIMAGE_RUNTIME:-${REPO_ROOT}/tools/android-steam-proxy/build/release-tools/runtime-aarch64}"
  # Check pinned packaging tools, exclusions and reproducible timestamps before
  # invoking appimagetool. Its default moving runtime download is prohibited.
  python3 - "$SCRIPT_DIR" "$APPDIR" "$APPIMAGETOOL" "$RUNTIME_FILE" <<'PY'
import os, pathlib, subprocess, sys
sys.path.insert(0, sys.argv[1])
from frame_release_utils import FORBIDDEN_FAMILIES, normalize, require_elf, sha256, tool_pins
appdir, tool, runtime = map(pathlib.Path, sys.argv[2:])
pins = tool_pins()['tools']
for path, name in [(tool, 'appimagetool-x86_64.AppImage'), (runtime, 'runtime-aarch64')]:
    if not path.is_file() or sha256(path) != pins[name]['sha256']:
        raise SystemExit('Missing/corrupt pinned packaging input: '+str(path)+'; use the high-level release --prepare-tools workflow')
require_elf(runtime)
require_elf(appdir/'usr/bin/creamlinux')
for path in appdir.rglob('*'):
    if any(path.name.startswith(family+'.so') for family in FORBIDDEN_FAMILIES):
        raise SystemExit('Forbidden bundled display library remains: '+str(path))
epoch = int(os.environ.get('SOURCE_DATE_EPOCH') or subprocess.check_output(
    ['git','-C',str(pathlib.Path(sys.argv[1]).parent),'show','-s','--format=%ct','HEAD']))
normalize(appdir, epoch)
PY
  SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "$REPO_ROOT" show -s --format=%ct HEAD)}" \
    ARCH=aarch64 APPIMAGE_EXTRACT_AND_RUN=1 "${APPIMAGETOOL}" \
    --runtime-file "$RUNTIME_FILE" --mksquashfs-opt -processors --mksquashfs-opt 1 \
    "${APPDIR}" "${OUTPUT_PATH}"
  echo "Successfully packaged: ${OUTPUT_PATH}"
else
  echo ""
  echo "ERROR: appimagetool unavailable; prepare checksum-pinned tools with the high-level release workflow." >&2
  exit 2
fi

echo ""
echo "Steam Frame AppDir preparation complete."
