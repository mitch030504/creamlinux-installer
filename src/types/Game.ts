export type GameRuntime =
  | 'linux_native'
  | 'proton'
  | 'lepton_android'

/**
 * Game information interface
 */
export interface Game {
  id: string
  title: string
  path: string
  platform?: string
  runtime: GameRuntime
  native: boolean
  api_files: string[]
  android_package?: string | null
  lepton_context?: string | null
  cream_installed?: boolean
  smoke_installed?: boolean
  installing?: boolean
}

export function getGameRuntime(game: { runtime?: GameRuntime; native?: boolean }): GameRuntime {
  return game.runtime ?? (game.native ? 'linux_native' : 'proton')
}
