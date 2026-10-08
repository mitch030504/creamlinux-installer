import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import { AppProvider } from '@/contexts/index.ts'
import { LeptonInspectorView } from '@/components/pages'
import './styles/main.scss'

/**
 * Detect if this window instance was opened as a dedicated Lepton inspection child window.
 */
function getLeptonInspectorRoute() {
  const searchParams = new URLSearchParams(window.location.search)
  if (searchParams.get('view') === 'lepton-inspect') {
    const appId = searchParams.get('appId')
    if (appId) {
      return {
        appId,
        title: searchParams.get('title') || undefined,
      }
    }
  }

  // Hash-based fallback: #/lepton-inspect?appId=...
  if (window.location.hash.startsWith('#/lepton-inspect')) {
    const hashQuery = window.location.hash.includes('?')
      ? window.location.hash.split('?')[1]
      : ''
    const hashParams = new URLSearchParams(hashQuery)
    const appId = hashParams.get('appId')
    if (appId) {
      return {
        appId,
        title: hashParams.get('title') || undefined,
      }
    }
  }

  return null
}

const inspectorRoute = getLeptonInspectorRoute()

if (inspectorRoute) {
  createRoot(document.getElementById('root')!).render(
    <LeptonInspectorView
      gameId={inspectorRoute.appId}
      gameTitle={inspectorRoute.title}
      isChildWindow={true}
    />
  )
} else {
  createRoot(document.getElementById('root')!).render(
    <AppProvider>
      <App />
    </AppProvider>
  )
}
