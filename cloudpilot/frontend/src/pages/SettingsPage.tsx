import { useRef, useState } from 'react'
import { fetchSettings, uploadUsageFile } from '../api/endpoints'
import { useApi } from '../hooks/useApi'
import { useAppContext } from '../context/AppContext'
import { useCurrency } from '../context/CurrencyContext'
import { LoadingState, ErrorState } from '../components/StatusStates'
import type { IngestSummary } from '../api/types'

export function SettingsPage() {
  const { provider, setProvider } = useAppContext()
  const { currency, setCurrency, usdToInrRate } = useCurrency()
  const settings = useApi(() => fetchSettings(), [])
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [uploadResult, setUploadResult] = useState<IngestSummary | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)

  async function handleUpload() {
    const file = fileInputRef.current?.files?.[0]
    if (!file) return
    setUploading(true)
    setUploadError(null)
    setUploadResult(null)
    try {
      const result = await uploadUsageFile(file)
      setUploadResult(result)
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Settings</h1>
        <p className="text-sm text-slate-500">System configuration and data ingestion.</p>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="mb-3 text-sm font-semibold text-slate-900">System status</h2>
        {settings.loading && <LoadingState label="Checking system status…" />}
        {settings.error && <ErrorState message={settings.error} />}
        {settings.data && (
          <dl className="grid grid-cols-2 gap-4 text-sm lg:grid-cols-4">
            <div>
              <dt className="text-xs uppercase text-slate-500">App</dt>
              <dd className="font-medium text-slate-900">{settings.data.app_name}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-slate-500">Gemini model</dt>
              <dd className="font-medium text-slate-900">{settings.data.gemini_model}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-slate-500">Gemini API key</dt>
              <dd className={`font-medium ${settings.data.gemini_configured ? 'text-emerald-600' : 'text-amber-600'}`}>
                {settings.data.gemini_configured ? 'Configured' : 'Not configured (agents use template fallback)'}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-slate-500">Database</dt>
              <dd className={`font-medium ${settings.data.database_connected ? 'text-emerald-600' : 'text-red-600'}`}>
                {settings.data.database_connected ? 'Connected' : 'Unreachable'}
              </dd>
            </div>
          </dl>
        )}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="mb-3 text-sm font-semibold text-slate-900">Default provider</h2>
        <p className="mb-2 text-xs text-slate-500">Used to scope resource/pricing lookups across every page.</p>
        <input
          className="w-64 rounded-md border border-slate-300 px-3 py-2 text-sm"
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
        />
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="mb-3 text-sm font-semibold text-slate-900">Display currency</h2>
        <p className="mb-2 text-xs text-slate-500">
          Every value is computed and stored in USD; this only changes how numbers are formatted on screen.
        </p>
        <div className="flex items-center gap-3">
          <div className="flex w-40 overflow-hidden rounded-md border border-slate-300 text-sm font-medium">
            {(['USD', 'INR'] as const).map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setCurrency(c)}
                aria-pressed={currency === c}
                className={`flex-1 px-3 py-2 transition-colors ${
                  currency === c ? 'bg-blue-600 text-white' : 'bg-white text-slate-600 hover:bg-slate-100'
                }`}
              >
                {c}
              </button>
            ))}
          </div>
          <span className="text-xs text-slate-500">Current rate: 1 USD = ₹{usdToInrRate.toFixed(2)}</span>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="mb-1 text-sm font-semibold text-slate-900">Upload usage data</h2>
        <p className="mb-3 text-xs text-slate-500">CSV or JSON matching the usage schema (see the synthetic dataset generator).</p>
        <div className="flex items-center gap-3">
          <input ref={fileInputRef} type="file" accept=".csv,.json" className="text-sm" />
          <button
            onClick={handleUpload}
            disabled={uploading}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {uploading ? 'Uploading…' : 'Upload'}
          </button>
        </div>
        {uploadError && (
          <div className="mt-3">
            <ErrorState message={uploadError} />
          </div>
        )}
        {uploadResult && (
          <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            Ingested {uploadResult.rows_valid}/{uploadResult.rows_received} rows into {uploadResult.usage_records_inserted}{' '}
            usage records ({uploadResult.resources_created} new resources).
            {uploadResult.rows_failed > 0 && ` ${uploadResult.rows_failed} rows failed validation.`}
          </div>
        )}
      </div>
    </div>
  )
}
