import { createContext, useContext, useState, type ReactNode } from 'react'

interface AppContextValue {
  provider: string
  setProvider: (p: string) => void
  resourceId: string
  setResourceId: (id: string) => void
}

const AppContext = createContext<AppContextValue | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const [provider, setProvider] = useState('aws')
  const [resourceId, setResourceId] = useState('')

  return (
    <AppContext.Provider value={{ provider, setProvider, resourceId, setResourceId }}>
      {children}
    </AppContext.Provider>
  )
}

export function useAppContext() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useAppContext must be used within AppProvider')
  return ctx
}
