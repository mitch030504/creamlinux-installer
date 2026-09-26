import { useState, useEffect } from 'react'
import { findBestGameImage } from '@/services/ImageService'
import { Game, getGameRuntime } from '@/types'
import { ActionButton, ActionType, Button } from '@/components/buttons'
import { Icon } from '@/components/icons'
import { openLeptonInspectorWindow } from '@/services/LeptonInspectorWindow'
import { useAppContext } from '@/contexts/useAppContext'

interface GameItemProps {
  game: Game
  onAction: (gameId: string, action: ActionType) => Promise<void>
  onEdit?: (gameId: string) => void
  onSmokeAPISettings?: (gameId: string) => void
  onRate?: (gameId: string) => void
  reportingEnabled?: boolean // When false/undefined, rate button is not rendered at all.
}

/**
 * Individual game card component
 * Displays game information and action buttons
 */
const GameItem = ({ game, onAction, onEdit, onSmokeAPISettings, onRate, reportingEnabled }: GameItemProps) => {
  const { inspectLeptonGame } = useAppContext()
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isInspecting, setIsInspecting] = useState(false)

  useEffect(() => {
    // Function to fetch the game cover/image
    const fetchGameImage = async () => {
      // First check if we already have it (to prevent flickering on re-renders)
      if (imageUrl) return

      setIsLoading(true)
      try {
        // Try to find the best available image for this game
        const bestImageUrl = await findBestGameImage(game.id)

        if (bestImageUrl) {
          setImageUrl(bestImageUrl)
        }
      } catch (error) {
        console.error('Error fetching game image:', error)
      } finally {
        setIsLoading(false)
      }
    }

    if (game.id) {
      fetchGameImage()
    }
  }, [game.id, imageUrl])

  const runtime = getGameRuntime(game)
  const isLinuxNative = runtime === 'linux_native'
  const isProton = runtime === 'proton'
  const isLepton = runtime === 'lepton_android'

  // Determine if we should show CreamLinux buttons (only for native Linux games)
  const shouldShowCream = isLinuxNative && game.cream_installed

  // SmokeAPI DLL flow is currently only valid for Proton games.
  const shouldShowSmoke =
    isProton && game.api_files && game.api_files.length > 0

  // Generic unlocker selection is currently only valid for native Linux.
  const shouldShowUnlocker =
    isLinuxNative && !game.cream_installed && !game.smoke_installed

  // Only Proton games should ever show the Windows Steam API DLL warning.
  const isProtonNoApi =
    isProton && (!game.api_files || game.api_files.length === 0)

  const handleCreamAction = () => {
    if (game.installing) return
    const action: ActionType = game.cream_installed ? 'uninstall_cream' : 'install_cream'
    onAction(game.id, action)
  }

  const handleSmokeAction = () => {
    if (game.installing) return
    const action: ActionType = game.smoke_installed ? 'uninstall_smoke' : 'install_smoke'
    onAction(game.id, action)
  }

  const handleUnlockerAction = () => {
    if (game.installing) return
    onAction(game.id, 'install_unlocker')
  }

  // Handle edit button click
  const handleEdit = () => {
    if (onEdit && game.cream_installed) {
      onEdit(game.id)
    }
  }

  // SmokeAPI settings handler
  const handleSmokeAPISettings = () => {
    if (onSmokeAPISettings && game.smoke_installed) {
      onSmokeAPISettings(game.id)
    }
  }

  // Rating handler
  const handleRate = () => {
    if (onRate && (game.cream_installed || game.smoke_installed)) {
      onRate(game.id)
    }
  }

  // Lepton introspection handler
  const handleInspect = async () => {
    setIsInspecting(true)
    try {
      await openLeptonInspectorWindow(game.id, game.title)
    } catch (err) {
      console.warn('Failed to open dedicated inspector window, falling back to in-window view:', err)
      inspectLeptonGame({ id: game.id, title: game.title })
    } finally {
      setIsInspecting(false)
    }
  }


  // Determine background image
  const backgroundImage =
    !isLoading && imageUrl ? `url(${imageUrl})` : 'linear-gradient(135deg, #232323, #1A1A1A)'

  return (
    <div
      className="game-item-card"
      style={{
        backgroundImage,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }}
    >
      <div className="game-item-overlay">
        <div className="game-badges">
          <span
            className={`status-badge ${
              isLinuxNative ? 'native' : isProton ? 'proton' : 'lepton'
            }`}
          >
            {isLinuxNative
              ? 'Native Linux'
              : isProton
                ? 'Proton'
                : 'Lepton / Android'}
          </span>
          {game.cream_installed && <span className="status-badge cream">CreamLinux</span>}
          {game.smoke_installed && <span className="status-badge smoke">SmokeAPI</span>}
        </div>

        <div className="game-title">
          <h3>{game.title}</h3>
        </div>

        <div className="game-actions">
          {/* Show generic "Install" button for native games with nothing installed */}
          {shouldShowUnlocker && (
            <ActionButton
              action="install_unlocker"
              isInstalled={false}
              isWorking={!!game.installing}
              onClick={handleUnlockerAction}
            />
          )}

          {/* Show CreamLinux uninstall button if CreamLinux is installed */}
          {shouldShowCream && (
            <ActionButton
              action="uninstall_cream"
              isInstalled={true}
              isWorking={!!game.installing}
              onClick={handleCreamAction}
            />
          )}

          {/* Show SmokeAPI button for Proton games OR native games with SmokeAPI installed */}
          {shouldShowSmoke && (
            <ActionButton
              action={game.smoke_installed ? 'uninstall_smoke' : 'install_smoke'}
              isInstalled={!!game.smoke_installed}
              isWorking={!!game.installing}
              onClick={handleSmokeAction}
            />
          )}

          {/* Show SmokeAPI uninstall for native Linux games if installed */}
          {isLinuxNative && game.smoke_installed && (
            <ActionButton
              action="uninstall_smoke"
              isInstalled={true}
              isWorking={!!game.installing}
              onClick={handleSmokeAction}
            />
          )}

          {/* Show message for Proton games without API files */}
          {isProtonNoApi && (
            <div className="api-not-found-message">
              <span>Steam API DLL not found</span>
              <Button
                variant="warning"
                size="small"
                onClick={() => onAction(game.id, 'install_smoke')}
                title="Attempt to scan again"
              >
                Rescan
              </Button>
            </div>
          )}

          {isLepton && (
            <div
              className="lepton-detected-message"
              title={
                game.android_package
                  ? `Package: ${game.android_package}${
                      game.lepton_context ? ` (${game.lepton_context})` : ''
                    }`
                  : undefined
              }
            >
              <span>Steam Frame Android game</span>
              <Button
                variant="secondary"
                size="small"
                onClick={handleInspect}
                disabled={isInspecting}
                className="inspect-button"
                title="Inspect Lepton runtime"
              >
                {isInspecting ? 'Inspecting...' : 'Inspect'}
              </Button>
            </div>
          )}

          {/* Rate button */}
          {(game.cream_installed || game.smoke_installed) && onRate && reportingEnabled && (
            <Button
              variant="primary"
              size="small"
              onClick={handleRate}
              disabled={!!game.installing}
              title="Rate compatibility"
              className="edit-button rate-button"
              leftIcon={<Icon name="Star" variant="solid" size="md" />}
              iconOnly
            />
          )}

          {/* Edit button - only enabled if CreamLinux is installed */}
          {game.cream_installed && (
            <Button
              variant="secondary"
              size="small"
              onClick={handleEdit}
              disabled={!game.cream_installed || !!game.installing}
              title="Manage DLCs"
              className="edit-button settings-icon-button"
              leftIcon={<Icon name="Settings" variant="solid" size="md" />}
              iconOnly
            />
          )}

          {/* Edit button - only enabled if SmokeAPI is installed */}
          {game.smoke_installed && (
            <Button
              variant="secondary"
              size="small"
              onClick={handleSmokeAPISettings}
              disabled={!game.smoke_installed || !!game.installing}
              title="Configure SmokeAPI"
              className="edit-button settings-icon-button"
              leftIcon={<Icon name="Settings" variant="solid" size="md" />}
              iconOnly
            />
          )}
        </div>
      </div>
    </div>
  )
}

export default GameItem
