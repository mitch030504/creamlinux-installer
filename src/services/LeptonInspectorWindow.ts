import { WebviewWindow } from '@tauri-apps/api/webviewWindow'

/**
 * Open or focus a dedicated Lepton inspector WebviewWindow for a given Steam AppID.
 *
 * Requirements:
 * - Uses a unique/reusable window label: lepton-inspect-<appid>
 * - If already open, focuses existing window rather than creating duplicates
 * - Window size: width: 1000, height: 720, minWidth: 700, minHeight: 500, resizable: true
 * - Centers the window where supported
 */
export async function openLeptonInspectorWindow(
  gameId: string,
  gameTitle: string
): Promise<WebviewWindow> {
  const sanitizedAppId = gameId.replace(/[^a-zA-Z0-9_-]/g, '_')
  const label = `lepton-inspect-${sanitizedAppId}`

  // Check if a window with this label already exists
  try {
    const existing = await WebviewWindow.getByLabel(label)
    if (existing) {
      try {
        await existing.show()
      } catch (e) {
        console.warn(`Could not show existing window "${label}":`, e)
      }
      try {
        await existing.unminimize()
      } catch (e) {
        console.warn(`Could not unminimize existing window "${label}":`, e)
      }
      try {
        await existing.setFocus()
      } catch (e) {
        console.warn(`Could not focus existing window "${label}":`, e)
      }
      return existing
    }
  } catch (err) {
    console.warn(`Error while checking for existing window "${label}":`, err)
  }

  // Construct URL with query parameters
  const params = new URLSearchParams({
    view: 'lepton-inspect',
    appId: gameId,
    title: gameTitle,
  })
  const url = `index.html?${params.toString()}`

  const newWindow = new WebviewWindow(label, {
    url,
    title: `Lepton Inspector - ${gameTitle} (${gameId})`,
    width: 1000,
    height: 720,
    minWidth: 700,
    minHeight: 500,
    resizable: true,
    center: true,
    focus: true,
  })

  newWindow.once('tauri://error', (err) => {
    console.error(`Failed to create inspector window "${label}":`, err)
  })

  newWindow.once('tauri://created', async () => {
    try {
      await newWindow.center()
    } catch {
      // Center might not be supported on all window managers / Wayland
    }
    try {
      await newWindow.setFocus()
    } catch {
      // Focus error non-fatal
    }
  })

  return newWindow
}
