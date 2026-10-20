import { useCallback, useEffect, useState } from 'react'
import { ThemeProvider } from './context/ThemeContext.jsx'
import { LocaleProvider, useLocale } from './context/LocaleContext.jsx'
import HomePage from './pages/HomePage.jsx'
import ProcessingPage from './pages/ProcessingPage.jsx'
import ResultsPage from './pages/ResultsPage.jsx'
import ThemeToggle from './components/ThemeToggle.jsx'
import { getHealth } from './services/api.js'

function LangToggle() {
  const { locale, setLocale } = useLocale()
  return (
    <button className="lang-toggle" onClick={() => setLocale(locale === 'bn' ? 'en' : 'bn')} type="button">
      {locale === 'bn' ? 'EN' : 'BN'}
    </button>
  )
}

export default function App() {
  const [view, setView] = useState('home')
  const [reportId, setReportId] = useState(null)
  const [health, setHealth] = useState(null)

  useEffect(() => {
    let cancelled = false
    getHealth()
      .then((data) => { if (!cancelled) setHealth(data) })
      .catch(() => { if (!cancelled) setHealth(null) })
    return () => { cancelled = true }
  }, [])

  const handleUploaded = useCallback((id) => { setReportId(id); setView('processing') }, [])
  const handleAnalyzed = useCallback(() => { setView('results') }, [])
  const handleReset = useCallback(() => { setReportId(null); setView('home') }, [])

  return (
    <ThemeProvider>
      <LocaleProvider>
        <ThemeToggle />
        <LangToggle />
        {view === 'processing' && (
          <ProcessingPage reportId={reportId} onDone={handleAnalyzed} onFailed={handleReset} onCancel={handleReset} />
        )}
        {view === 'results' && <ResultsPage reportId={reportId} onReset={handleReset} />}
        {view === 'home' && <HomePage health={health} maxSizeMb={health?.max_upload_size_mb ?? 12} onUploaded={handleUploaded} />}
      </LocaleProvider>
    </ThemeProvider>
  )
}