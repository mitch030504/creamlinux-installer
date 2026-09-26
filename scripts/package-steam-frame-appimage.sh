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
  
  # Find matching files in the library directory (without descending into subdirectories)
  matched_files=$(find "${LIBDIR}" -maxdepth 1 -type f -name "${base_pattern}.so*" -o -type l -name "${base_pattern}.so*" 2>/dev/null || true)
  
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

OUTPUT_NAME="Creamlinux_1.7.1_steam-frame-lepton-fixed_aarch64.AppImage"
OUTPUT_DIR="${REPO_ROOT}/.."
OUTPUT_PATH="${2:-${OUTPUT_DIR}/${OUTPUT_NAME}}"

if [ -n "${APPIMAGETOOL}" ] && [ -x "${APPIMAGETOOL}" ]; then
  echo ""
  echo "Packaging final Steam Frame ARM64 AppImage using ${APPIMAGETOOL}..."
  rm -f "${OUTPUT_PATH}"
  ARCH=aarch64 "${APPIMAGETOOL}" "${APPDIR}" "${OUTPUT_PATH}"
  echo "Successfully packaged: ${OUTPUT_PATH}"
else
  echo ""
  echo "NOTE: appimagetool not found automatically. To generate the final AppImage, run:"
  echo "  ARCH=aarch64 appimagetool \"${APPDIR}\" \"${OUTPUT_PATH}\""
fi

echo ""
echo "Steam Frame AppDir preparation complete."
