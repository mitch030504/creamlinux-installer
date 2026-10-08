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

/**
 * Structured introspection result for a Lepton / Android game
 */
export interface LeptonIntrospection {
  available: boolean
  running: boolean
  context?: string | null
  package?: string | null
  primary_abi?: string | null
  apk_path?: string | null
  steam_api_path?: string | null
}

/** Manual snapshot; null compatibility means inconclusive. */
export interface LeptonCompatibility {
  analyzed: boolean
  steam_api_found: boolean
  architecture: string | null
  total_public_exports: number | null
  function_exports: number | null
  supported_function_exports: number | null
  unsupported_exports: string[]
  required_unsupported_exports: string[]
  proxy_compatible: boolean | null
  compatibility_scope: string | null
  notes: string[]
  analysis_exit_code?: number | null
  provider_sha256?: string | null
  current_proxy?: {
    compatible: boolean | null
    manifest_function_count: number
    target_functions_not_forwarded: string[]
    proxy_targets_absent_from_target: string[]
  } | null
  consumer_evidence?: {
    consumer_elf_count: number
    relevant_abi_consumer_count: number
    direct_libsteam_api_consumer_count: number
    undefined_steam_named_symbols: string[]
  } | null
  runtime_resolution_evidence?: { strong_candidate_count: number; interpretation: string } | null
  target_specific_forwarding?: {
    assessment: string
    assessment_reasons: string[]
    validated: boolean
    generation_status: string
    local_validation_status: string
    hardware_validation_status: string
    binding_validation_status: string
    non_function_coverage: string
    non_function_export_count: number
    consumer_required_non_function_exports: string[]
    non_function_requirement_evidence: string
    limitations: string[]
    validation_evidence: {
      source: string
      provider_sha256: string
      proxy_sha256: string | null
      scope: string
      device?: string
      measured_at?: string
      toolchain?: string
    } | null
  } | null
}

export interface LeptonArtifactOptions {
  target_proxy_dir: string | null
  hardware_bundle: string | null
  hardware_results: string | null
}
