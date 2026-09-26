import { useState, useCallback } from 'react'
import { useAppContext } from '@/contexts/useAppContext'
import { getGameRuntime } from '@/types'

/**
 * Main application logic hook
 * Combines various aspects of the app's behavior
 */
export function useAppLogic() {
  // Get values from app context. isInitialLoad/scanProgress are driven by the
  // real scan_steam_games call and its scan-progress events (see useGames),
  // not a simulated one, useGames already kicks off the initial scan itself.
  const { games, loadGames, isLoading, isInitialLoad, scanProgress, error, showToast } =
    useAppContext()

  // Local state for filtering and UI
  const [filter, setFilter] = useState('overview')
  const [searchQuery, setSearchQuery] = useState('')

  // Filter games based on current filter and search
  const filteredGames = useCallback(() => {
    return games.filter((game) => {
      // First filter by Steam runtime type
      const runtime = getGameRuntime(game)

      const platformMatch =
        filter === 'all' ||
        (filter === 'native' && runtime === 'linux_native') ||
        (filter === 'proton' && runtime === 'proton') ||
        (filter === 'lepton' && runtime === 'lepton_android')

      // Then filter by search query
      const searchMatch =
        !searchQuery.trim() || game.title.toLowerCase().includes(searchQuery.toLowerCase())

      return platformMatch && searchMatch
    })
  }, [games, filter, searchQuery])

  // Handle search changes
  const handleSearchChange = useCallback((query: string) => {
    setSearchQuery(query)
  }, [])

  // Force a refresh
  const handleRefresh = useCallback(async () => {
    try {
      await loadGames()
      showToast('Game list refreshed', 'success')
    } catch (error) {
      showToast(`Failed to refresh: ${error}`, 'error')
    }
  }, [loadGames, showToast])

  return {
    filter,
    setFilter,
    searchQuery,
    handleSearchChange,
    isInitialLoad,
    scanProgress,
    filteredGames: filteredGames(),
    handleRefresh,
    isLoading,
    error,
  }
}
