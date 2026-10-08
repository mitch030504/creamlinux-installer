import React, { useState, useEffect } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { getCurrentWebviewWindow } from '@tauri-apps/api/webviewWindow'
import { LeptonIntrospection, LeptonCompatibility, LeptonArtifactOptions, Game } from '@/types'
import { open } from '@tauri-apps/plugin-dialog'
import { LeptonCompatibilityReport } from './LeptonCompatibilityReport'
import { Button } from '@/components/buttons'
import { Icon, layers, check, close, refresh, copy, info, warning } from '@/components/icons'

export interface LeptonInspectorViewProps {
  gameId: string
  gameTitle?: string
  isChildWindow?: boolean
  onBack?: () => void
}

export const LeptonInspectorView: React.FC<LeptonInspectorViewProps> = ({
  gameId,
  gameTitle,
  isChildWindow = false,
  onBack,
}) => {
  const [title, setTitle] = useState<string>(gameTitle || `Steam App ${gameId}`)
  const [introspection, setIntrospection] = useState<LeptonIntrospection | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [copiedField, setCopiedField] = useState<string | null>(null)

  const [compatibility, setCompatibility] = useState<LeptonCompatibility | null>(null)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [artifacts, setArtifacts] = useState<LeptonArtifactOptions>({ target_proxy_dir: null, hardware_bundle: null, hardware_results: null })
  const requestGeneration = React.useRef(0)

  useEffect(() => {
    requestGeneration.current += 1
    setCompatibility(null)
    setAnalysisError(null)
    setIsAnalyzing(false)
    setArtifacts({ target_proxy_dir: null, hardware_bundle: null, hardware_results: null })
    return () => { requestGeneration.current += 1 }
  }, [gameId])

  const analyzeCompatibility = async () => {
    const generation = ++requestGeneration.current
    setIsAnalyzing(true)
    setCompatibility(null)
    setAnalysisError(null)
    try {
      const result = await invoke<LeptonCompatibility>('analyze_lepton_compatibility', { gameId, artifacts })
      if (generation === requestGeneration.current) setCompatibility(result)
    } catch (error) {
      if (generation === requestGeneration.current) setAnalysisError(String(error))
    } finally {
      if (generation === requestGeneration.current) setIsAnalyzing(false)
    }
  }

  // Fetch game title if not provided
  useEffect(() => {
    let cancelled = false
    setTitle(gameTitle || `Steam App ${gameId}`)
    if (!gameTitle) {
      invoke<Game>('get_game_info', { gameId })
        .then((g) => {
          if (!cancelled && g?.title) setTitle(g.title)
        })
        .catch(() => {
          // Keep fallback title
        })
    }
    return () => { cancelled = true }
  }, [gameId, gameTitle])

  // Introspection query
  const fetchLeptonInfo = React.useCallback(async () => {
    const generation = ++requestGeneration.current
    setIsLoading(true)
    setIsAnalyzing(false)
    setIntrospection(null)
    setCompatibility(null)
    setAnalysisError(null)
    setErrorMessage(null)
    try {
      const data = await invoke<LeptonIntrospection>('get_lepton_info', { gameId })
      if (generation === requestGeneration.current) setIntrospection(data)
    } catch (err) {
      if (generation !== requestGeneration.current) return
      console.error('Failed to get Lepton info:', err)
      setErrorMessage(typeof err === 'string' ? err : 'Failed to query Lepton runtime info')
      setIntrospection({
        available: false,
        running: false,
        context: `steamlaunch-${gameId}`,
        package: null,
        primary_abi: null,
        apk_path: null,
        steam_api_path: null,
      })
    } finally {
      if (generation === requestGeneration.current) setIsLoading(false)
    }
  }, [gameId])

  const selectArtifact = async (key: keyof LeptonArtifactOptions) => {
    const generation = requestGeneration.current
    try {
      const selected = await open({ directory: key !== 'hardware_bundle', multiple: false,
        title: key === 'target_proxy_dir' ? 'Select generated proxy directory' :
          key === 'hardware_bundle' ? 'Select hardware validation bundle' : 'Select hardware results directory' })
      if (generation !== requestGeneration.current || typeof selected !== 'string') return
      requestGeneration.current += 1
      setCompatibility(null)
      setAnalysisError(null)
      setArtifacts(previous => ({ ...previous, [key]: selected }))
    } catch (error) {
      if (generation === requestGeneration.current) setAnalysisError(String(error))
    }
  }

  useEffect(() => {
    fetchLeptonInfo()
  }, [fetchLeptonInfo])

  const handleCopy = async (text: string, fieldKey: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedField(fieldKey)
      setTimeout(() => {
        setCopiedField((prev) => (prev === fieldKey ? null : prev))
      }, 2000)
    } catch (err) {
      console.error('Failed to copy to clipboard:', err)
    }
  }

  const handleClose = async () => {
    if (isChildWindow) {
      try {
        const win = getCurrentWebviewWindow()
        await win.close()
      } catch (err) {
        console.warn('Failed to close window via getCurrentWebviewWindow:', err)
        window.close()
      }
    } else if (onBack) {
      onBack()
    }
  }

  const isRunning = !!introspection?.running
  const isAvailable = !!introspection?.available

  return (
    <div className={`lepton-inspector-page ${isChildWindow ? 'child-window-mode' : 'embedded-mode'}`}>
      {/* Top Header & Action Bar */}
      <header className="lepton-inspector-header">
        <div className="lepton-inspector-title-area">
          <div className="lepton-inspector-icon">
            <Icon name={layers} variant="solid" size="lg" />
          </div>
          <div className="lepton-inspector-headings">
            <h1 className="lepton-title-text">{title}</h1>
            <div className="lepton-badges">
              <span className="lepton-meta-pill appid">AppID: {gameId}</span>
              <span className="lepton-meta-pill runtime">Steam Frame Lepton (Android)</span>
            </div>
          </div>
        </div>

        <div className="lepton-inspector-actions">
          <Button
            variant="secondary"
            onClick={fetchLeptonInfo}
            disabled={isLoading || isAnalyzing}
            className="lepton-btn-refresh"
            title="Re-query Lepton runtime state"
            leftIcon={
              <Icon
                name={refresh}
                variant="solid"
                size="md"
                className={isLoading ? 'lepton-spin' : ''}
              />
            }
          >
            {isLoading ? 'Checking...' : 'Refresh'}
          </Button>

          <Button
            variant="primary"
            onClick={handleClose}
            className="lepton-btn-close"
            title={isChildWindow ? 'Close this window' : 'Return to game list'}
            leftIcon={<Icon name={close} variant="solid" size="md" />}
          >
            {isChildWindow ? 'Close' : 'Back'}
          </Button>
        </div>
      </header>

      {/* Main Content Body */}
      <main className="lepton-inspector-body">
        {/* Status Banner */}
        {isRunning ? (
          <div className="lepton-banner running">
            <div className="lepton-banner-icon">
              <Icon name={check} variant="solid" size="lg" />
            </div>
            <div className="lepton-banner-content">
              <h3>Container context is running</h3>
              <p>Live package metadata and runtime paths inspected from the Linux host.</p>
            </div>
          </div>
        ) : (
          <div className="lepton-banner not-running">
            <div className="lepton-banner-icon">
              <Icon name={info} variant="solid" size="lg" />
            </div>
            <div className="lepton-banner-content">
              <h3>Lepton game is not currently running.</h3>
              <p>
                Start the game through Steam on the Steam Frame to inspect live container paths
                and native libraries.
              </p>
            </div>
          </div>
        )}

        {errorMessage && (
          <div className="lepton-banner error">
            <div className="lepton-banner-icon">
              <Icon name={warning} variant="solid" size="lg" />
            </div>
            <div className="lepton-banner-content">
              <h3>Introspection Error</h3>
              <p>{errorMessage}</p>
            </div>
          </div>
        )}

        {/* Vertical Section 1: Host & Container Status */}
        <section className="lepton-section">
          <div className="lepton-section-header">
            <h2>Host & Container Environment</h2>
            <p>Overall state of the Valve Lepton execution layer on this system.</p>
          </div>

          <div className="lepton-cards-grid">
            <div className="lepton-card">
              <span className="lepton-card-label">Host CLI</span>
              <div className="lepton-card-value">
                <span className={`status-pill ${isAvailable ? 'available' : 'unavailable'}`}>
                  {isAvailable ? 'Available' : 'Not Found'}
                </span>
                <span className="lepton-card-subtext">
                  {isAvailable
                    ? '~/.local/share/Steam/steamapps/common/Lepton/lepton'
                    : 'Lepton CLI missing on host PATH or Steam directory'}
                </span>
              </div>
            </div>

            <div className="lepton-card">
              <span className="lepton-card-label">Container Status</span>
              <div className="lepton-card-value">
                <span className={`status-pill ${isRunning ? 'running' : 'idle'}`}>
                  {isRunning ? 'Running' : 'Idle / Not Running'}
                </span>
                <span className="lepton-card-subtext">
                  {isRunning
                    ? 'Active container namespace is responsive'
                    : 'Container is not currently loaded in memory'}
                </span>
              </div>
            </div>

            <div className="lepton-card">
              <span className="lepton-card-label">Context</span>
              <div className="lepton-card-value">
                {introspection?.context ? (
                  <div className="lepton-inline-code-box">
                    <code className="lepton-code">{introspection.context}</code>
                    <button
                      type="button"
                      className={`lepton-copy-btn ${copiedField === 'context' ? 'copied' : ''}`}
                      onClick={() => handleCopy(introspection.context!, 'context')}
                      title="Copy context to clipboard"
                    >
                      <Icon
                        name={copiedField === 'context' ? check : copy}
                        variant="solid"
                        size="sm"
                      />
                      <span>{copiedField === 'context' ? 'Copied' : 'Copy'}</span>
                    </button>
                  </div>
                ) : (
                  <span className="lepton-dim">None</span>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* Vertical Section 2: Android Package */}
        <section className="lepton-section">
          <div className="lepton-section-header">
            <h2>Package Details</h2>
            <p>Target Android package identifier and native architecture.</p>
          </div>

          <div className="lepton-cards-grid">
            <div className="lepton-card">
              <span className="lepton-card-label">Android Package</span>
              <div className="lepton-card-value">
                {introspection?.package ? (
                  <div className="lepton-inline-code-box">
                    <code className="lepton-code">{introspection.package}</code>
                    <button
                      type="button"
                      className={`lepton-copy-btn ${copiedField === 'package' ? 'copied' : ''}`}
                      onClick={() => handleCopy(introspection.package!, 'package')}
                      title="Copy package to clipboard"
                    >
                      <Icon
                        name={copiedField === 'package' ? check : copy}
                        variant="solid"
                        size="sm"
                      />
                      <span>{copiedField === 'package' ? 'Copied' : 'Copy'}</span>
                    </button>
                  </div>
                ) : (
                  <span className="lepton-dim">None detected</span>
                )}
              </div>
            </div>

            <div className="lepton-card">
              <span className="lepton-card-label">Primary ABI</span>
              <div className="lepton-card-value">
                {introspection?.primary_abi ? (
                  <code className="lepton-code">{introspection.primary_abi}</code>
                ) : (
                  <span className="lepton-dim">
                    {isRunning ? 'Not detected' : 'Not running'}
                  </span>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* Vertical Section 3: Container Filesystem Paths */}
        <section className="lepton-section">
          <div className="lepton-section-header">
            <h2>Container Filesystem Paths</h2>
            <p>Full path references to application packages and native libraries inside the container.</p>
          </div>

          <div className="lepton-paths-stack">
            {/* APK Path */}
            <div className="lepton-path-block">
              <div className="lepton-path-meta">
                <span className="lepton-path-label">APK Path</span>
                <span className="lepton-path-desc">
                  Location of base.apk within the Android container
                </span>
              </div>
              <div className="lepton-path-box">
                {introspection?.apk_path ? (
                  <>
                    <code className="lepton-path-text">{introspection.apk_path}</code>
                    <button
                      type="button"
                      className={`lepton-copy-btn ${copiedField === 'apk_path' ? 'copied' : ''}`}
                      onClick={() => handleCopy(introspection.apk_path!, 'apk_path')}
                      title="Copy APK path to clipboard"
                    >
                      <Icon
                        name={copiedField === 'apk_path' ? check : copy}
                        variant="solid"
                        size="sm"
                      />
                      <span>{copiedField === 'apk_path' ? 'Copied' : 'Copy'}</span>
                    </button>
                  </>
                ) : (
                  <span className="lepton-path-empty">
                    {isRunning ? 'Not found' : 'Not running'}
                  </span>
                )}
              </div>
            </div>

            {/* Steam API Path */}
            <div className="lepton-path-block highlight">
              <div className="lepton-path-meta">
                <span className="lepton-path-label">Steam API Path</span>
                <span className="lepton-path-desc">
                  Target libsteam_api.so path inside the application package library directory
                </span>
              </div>
              <div className="lepton-path-box highlight">
                {introspection?.steam_api_path ? (
                  <>
                    <code className="lepton-path-text highlight">{introspection.steam_api_path}</code>
                    <button
                      type="button"
                      className={`lepton-copy-btn ${copiedField === 'steam_api_path' ? 'copied' : ''}`}
                      onClick={() => handleCopy(introspection.steam_api_path!, 'steam_api_path')}
                      title="Copy Steam API path to clipboard"
                    >
                      <Icon
                        name={copiedField === 'steam_api_path' ? check : copy}
                        variant="solid"
                        size="sm"
                      />
                      <span>{copiedField === 'steam_api_path' ? 'Copied' : 'Copy'}</span>
                    </button>
                  </>
                ) : (
                  <span className="lepton-path-empty">
                    {isRunning ? 'Not found' : 'Not running'}
                  </span>
                )}
              </div>
            </div>
          </div>
        </section>
        <section className="lepton-section" aria-labelledby="compatibility-title" aria-busy={isAnalyzing}>
          <div className="lepton-section-header">
            <h2 id="compatibility-title">Steam API Compatibility</h2>
            <p>Read-only snapshot of exports and observed static consumers. No game files are changed.</p>
          </div>
          <Button variant="secondary" onClick={analyzeCompatibility}
            disabled={isLoading || isAnalyzing || !isAvailable || !isRunning}>
            {isAnalyzing ? 'Analyzing compatibility…' : 'Analyze compatibility'}
          </Button>
          <details className="lepton-artifact-options">
            <summary>Inspect existing validation artifacts (optional)</summary>
            <p>Select artifacts to verify against this game's provider. Nothing is generated or installed.</p>
            {(['target_proxy_dir', 'hardware_bundle', 'hardware_results'] as const).map(key => <div key={key} className="lepton-artifact-row">
              <Button variant="secondary" size="small" disabled={isAnalyzing || isLoading} onClick={() => selectArtifact(key)}>
                {key === 'target_proxy_dir' ? 'Select generated proxy' : key === 'hardware_bundle' ? 'Select hardware bundle' : 'Select results folder'}
              </Button>
              <code>{artifacts[key] ?? 'Not selected'}</code>
            </div>)}
            <Button variant="secondary" size="small" disabled={isAnalyzing || isLoading} onClick={() => {
              requestGeneration.current += 1
              setCompatibility(null)
              setAnalysisError(null)
              setArtifacts({ target_proxy_dir: null, hardware_bundle: null, hardware_results: null })
            }}>Clear artifact selection</Button>
          </details>
          <div role="status">
            {isAnalyzing && <p>Reading APKs and scanning native libraries. Large packages may take several minutes.</p>}
            {!compatibility && !isAnalyzing && <p>{!isAvailable ? 'Lepton CLI is unavailable.' : !isRunning
              ? 'The Lepton game must already be running to analyze it.' : 'Compatibility has not been analyzed.'}</p>}
            {analysisError && <p>Analysis incomplete: {analysisError}</p>}
            {compatibility && <LeptonCompatibilityReport result={compatibility} />}
          </div>
        </section>
      </main>
    </div>
  )
}

export default LeptonInspectorView
