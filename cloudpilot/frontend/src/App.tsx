import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { AppProvider } from './context/AppContext'
import { CurrencyProvider } from './context/CurrencyContext'
import { DashboardPage } from './pages/DashboardPage'
import { ForecastPage } from './pages/ForecastPage'
import { CostAnalysisPage } from './pages/CostAnalysisPage'
import { OptimizationPage } from './pages/OptimizationPage'
import { WhatIfPage } from './pages/WhatIfPage'
import { AgentTracePage } from './pages/AgentTracePage'
import { SettingsPage } from './pages/SettingsPage'

export default function App() {
  return (
    <AppProvider>
      <CurrencyProvider>
        <BrowserRouter>
          <Layout>
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/forecast" element={<ForecastPage />} />
              <Route path="/cost-analysis" element={<CostAnalysisPage />} />
              <Route path="/optimization" element={<OptimizationPage />} />
              <Route path="/what-if" element={<WhatIfPage />} />
              <Route path="/agent-trace" element={<AgentTracePage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Routes>
          </Layout>
        </BrowserRouter>
      </CurrencyProvider>
    </AppProvider>
  )
}
