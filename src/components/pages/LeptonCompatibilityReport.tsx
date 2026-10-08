import type { LeptonCompatibility } from '@/types'

export function functionProxyLabel(result: LeptonCompatibility): string {
  if (result.analysis_exit_code === 2) return 'Analysis incomplete'
  const target = result.target_specific_forwarding
  if (!target) return 'Unknown'
  if (target.generation_status === 'hardware_validated') {
    const evidence = target.validation_evidence
    return target.hardware_validation_status === 'passed' && result.provider_sha256 &&
      evidence?.provider_sha256 === result.provider_sha256 && evidence.proxy_sha256
      ? 'Hardware validated — function harness' : 'Validation evidence incomplete'
  }
  return ({ not_generated: 'No generated artifact selected', generated: 'Generated sources',
    locally_validated: 'Locally validated — static checks' } as Record<string, string>)[target.generation_status] ?? 'Unknown'
}

export const LeptonCompatibilityReport = ({ result }: { result: LeptonCompatibility }) => {
  const target = result.target_specific_forwarding
  const evidence = target?.validation_evidence
  const fixed = result.analysis_exit_code === 2 ? null : result.current_proxy?.compatible ?? result.proxy_compatible
  const coverage = ({ complete: 'No non-function exports to omit', 'omitted-unrequired': 'Omitted — no observed requirement',
    blocked: 'Blocked by observed requirements', unknown: 'Unknown' } as Record<string, string>)[target?.non_function_coverage ?? 'unknown'] ?? 'Unknown'
  return <div className="lepton-compatibility-report">
    <dl className="lepton-compatibility-data">
      <dt>Architecture</dt><dd>{result.architecture ?? 'Unknown'}</dd>
      <dt>Provider SHA256</dt><dd><code>{result.provider_sha256 ?? 'Unknown'}</code></dd>
      <dt>Public / function exports</dt><dd>{result.total_public_exports ?? '?'} / {result.function_exports ?? '?'}</dd>
    </dl>
    <div className="lepton-compatibility-panels">
      <section className="lepton-compatibility-panel" aria-labelledby="fixed-proxy-title">
        <h3 id="fixed-proxy-title">Current fixed proxy</h3>
        <p className={`lepton-compatibility-status ${fixed === true ? 'compatible' : fixed === false ? 'incompatible' : ''}`}>
          {fixed === true ? 'Compatible for observed static consumers' : fixed === false ? 'Incompatible with the current proxy' : 'Analysis incomplete'}
        </p>
        <dl className="lepton-compatibility-data">
          <dt>Functions covered</dt><dd>{result.supported_function_exports ?? '?'} / {result.function_exports ?? '?'}</dd>
          <dt>Target functions uncovered</dt><dd>{result.current_proxy?.target_functions_not_forwarded?.length ?? 'Unknown'}</dd>
          <dt>Proxy targets absent</dt><dd>{result.current_proxy?.proxy_targets_absent_from_target?.length ?? 'Unknown'}</dd>
          <dt>Required unsupported exports</dt><dd>{result.analyzed
            ? result.required_unsupported_exports.length || 'None observed' : 'Unknown'}</dd>
        </dl>
      </section>
      <section className="lepton-compatibility-panel" aria-labelledby="target-proxy-title">
        <h3 id="target-proxy-title">Target-specific function proxy</h3>
        <p className="lepton-compatibility-status">{functionProxyLabel(result)}</p>
        <dl className="lepton-compatibility-data">
          <dt>Local validation</dt><dd>{target?.local_validation_status === 'passed_static_parity'
            ? 'Static surface and ABI checks passed' : target?.local_validation_status === 'not_run' ? 'Not run' : 'Unknown'}</dd>
          <dt>Hardware validation</dt><dd>{functionProxyLabel(result).startsWith('Hardware validated')
            ? 'Recorded Steam Frame/Bionic run' : target?.hardware_validation_status === 'not_run' ? 'Not run' : 'Evidence incomplete'}</dd>
          <dt>Non-function coverage</dt><dd>{coverage}{target ? ` (${target.non_function_export_count} exports)` : ''}</dd>
          <dt>Observed non-function requirements</dt><dd>{target?.consumer_required_non_function_exports?.length ?? 'Unknown'}</dd>
        </dl>
        <p>Function-only validation does not establish gameplay compatibility or a complete library ABI.</p>
      </section>
    </div>
    <dl className="lepton-compatibility-data">
      <dt>Native consumers inspected</dt><dd>{result.consumer_evidence?.consumer_elf_count ?? 'Unknown'}</dd>
      <dt>Direct Steam dependencies</dt><dd>{result.consumer_evidence?.direct_libsteam_api_consumer_count ?? 'Unknown'}</dd>
      <dt>Runtime lookup candidates</dt><dd>{result.runtime_resolution_evidence?.strong_candidate_count ?? 'Unknown'}</dd>
    </dl>
    <p>Runtime strings indicate possible lookups; they do not prove individual API calls.</p>
    {evidence && <details>
      <summary>Validation evidence and identity</summary>
      <dl className="lepton-compatibility-data">
        <dt>Evidence source</dt><dd><code>{evidence.source}</code></dd>
        <dt>Provider SHA256</dt><dd><code>{evidence.provider_sha256}</code></dd>
        <dt>Proxy SHA256</dt><dd><code>{evidence.proxy_sha256 ?? 'No binary'}</code></dd>
        {evidence.measured_at && <><dt>Measured at</dt><dd>{evidence.measured_at}</dd></>}
        {evidence.toolchain && <><dt>Toolchain</dt><dd>{evidence.toolchain}</dd></>}
      </dl>
      <p>{evidence.scope}</p>
    </details>}
    <details><summary>Current proxy unsupported exports ({result.unsupported_exports.length})</summary>
      <ul>{result.unsupported_exports.map(name => <li key={name}><code>{name}</code></li>)}</ul>
    </details>
    <details><summary>Notes and analysis limitations</summary>
      <ul>{[...result.notes, ...(target?.assessment_reasons ?? []), ...(target?.limitations ?? [])]
        .map((note, index) => <li key={index}>{note}</li>)}</ul>
    </details>
    <p>Refresh clears this snapshot. No proxy is installed and no game process is injected.</p>
  </div>
}
