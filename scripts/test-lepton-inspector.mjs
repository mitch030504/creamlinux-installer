import assert from 'node:assert/strict'
import { test, after } from 'node:test'
import { mkdir, mkdtemp, rm } from 'node:fs/promises'
import { resolve } from 'node:path'
import { createRequire } from 'node:module'
import { build } from 'esbuild'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

await mkdir(resolve('node_modules/.tmp'), { recursive: true })
const directory = await mkdtemp(resolve('node_modules/.tmp/lepton-report-'))
const output = resolve(directory, 'report.cjs')
await build({ entryPoints: ['src/components/pages/LeptonCompatibilityReport.tsx'], outfile: output,
  bundle: true, jsx: 'automatic', platform: 'node', format: 'cjs', external: ['react', 'react/jsx-runtime'] })
const { LeptonCompatibilityReport, functionProxyLabel } = createRequire(import.meta.url)(output)
after(() => rm(directory, { recursive: true, force: true }))
const target = { assessment: 'candidate', assessment_reasons: [], validated: false,
  generation_status: 'not_generated', local_validation_status: 'not_run', hardware_validation_status: 'not_run',
  binding_validation_status: 'not_run', non_function_coverage: 'omitted-unrequired',
  non_function_export_count: 209, consumer_required_non_function_exports: [], limitations: [], validation_evidence: null }
const fixture = { analyzed: true, steam_api_found: true, architecture: 'ARM64', provider_sha256: 'provider',
  total_public_exports: 1365, function_exports: 1156, supported_function_exports: 1036,
  unsupported_exports: [], required_unsupported_exports: [], proxy_compatible: false, notes: [],
  target_specific_forwarding: target, analysis_exit_code: 1 }
const render = result => renderToStaticMarkup(React.createElement(LeptonCompatibilityReport, { result }))
const hardware = () => ({ ...fixture, target_specific_forwarding: { ...target,
  generation_status: 'hardware_validated', local_validation_status: 'passed_static_parity', hardware_validation_status: 'passed',
  validation_evidence: { source: '/results', provider_sha256: 'provider', proxy_sha256: 'proxy', scope: 'Function harness only' } } })

test('fixed incompatibility stays visible beside a hardware-validated function harness', () => {
  const html = render(hardware())
  assert.match(html, /Incompatible with the current proxy/)
  assert.match(html, /Hardware validated.*function harness/)
  assert.match(html, /Omitted.*no observed requirement/)
  assert.match(html, /does not establish gameplay compatibility/)
})
test('Walkabout keeps its conservative scope', () => {
  const html = render({ ...fixture, proxy_compatible: true, analysis_exit_code: 0 })
  assert.match(html, /Compatible for observed static consumers/)
  assert.doesNotMatch(html, /Fully compatible|Guaranteed compatible/)
})
test('default snapshot cannot inherit existing hardware evidence', () => {
  assert.equal(functionProxyLabel(fixture), 'No generated artifact selected')
  assert.doesNotMatch(render(fixture), /Recorded Steam Frame\/Bionic run/)
})
test('provider mismatch cannot display hardware validation', () => {
  const result = hardware()
  result.provider_sha256 = 'different-provider'
  assert.equal(functionProxyLabel(result), 'Validation evidence incomplete')
  assert.doesNotMatch(render(result), /Recorded Steam Frame\/Bionic run/)
})
test('missing proxy identity cannot display hardware validation', () => {
  const result = hardware()
  result.target_specific_forwarding.validation_evidence.proxy_sha256 = null
  assert.equal(functionProxyLabel(result), 'Validation evidence incomplete')
})
test('operational exit two never becomes a completed compatibility result', () => {
  const html = render({ ...fixture, analysis_exit_code: 2 })
  assert.match(html, /Analysis incomplete/)
  assert.doesNotMatch(html, /Incompatible with the current proxy/)
})
test('unknown future artifact states remain unknown', () => {
  assert.equal(functionProxyLabel({ ...fixture, target_specific_forwarding: { ...target, generation_status: 'future-state' } }), 'Unknown')
})
test('evidence text is escaped and the report exposes no installation controls', () => {
  const result = hardware()
  result.target_specific_forwarding.validation_evidence.source = '<script>unsafe()</script>'
  const html = render(result)
  assert.doesNotMatch(html, /<script>|<button/)
  assert.match(html, /&lt;script&gt;/)
})
