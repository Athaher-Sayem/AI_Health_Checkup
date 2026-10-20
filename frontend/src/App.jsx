import { useCallback, useState } from 'react'
import { ThemeProvider } from './context/ThemeContext.jsx'
import { LocaleProvider } from './context/LocaleContext.jsx'
import HomePage from './pages/HomePage.jsx'
import ProcessingPage from './pages/ProcessingPage.jsx'
import ResultsPage from './pages/ResultsPage.jsx'
import TextReadPage from './pages/TextReadPage.jsx'
import Nav from './components/Nav.jsx'
import Footer from './components/Footer.jsx'
import { useRequest } from './hooks/useRequest.js'
import { getHealth } from './services/api.js'

export default function App() {
  const [view, setView] = useState('home')
  const [reportId, setReportId] = useState(null)

  const { data: health } = useRequest(() => getHealth(), [])

  const handleUploaded = useCallback((id) => { setReportId(id); setView('processing') }, [])
  const handleAnalyzed = useCallback(() => { setView('results') }, [])
  const handleReset = useCallback(() => { setReportId(null); setView('home') }, [])

  return (
    <ThemeProvider>
      <LocaleProvider>
        <Nav
          view={view}
          onHome={() => setView('home')}
          onReadText={() => setView('read-text')}
        />
        {view === 'processing' && (
          <ProcessingPage
            reportId={reportId}
            onDone={handleAnalyzed}
            onFailed={handleReset}
            onCancel={handleReset}
          />
        )}
        {view === 'results' && <ResultsPage reportId={reportId} onReset={handleReset} />}
        {view === 'read-text' && <TextReadPage />}
        {view === 'home' && (
          <HomePage
            health={health}
            maxSizeMb={health?.max_upload_size_mb ?? 12}
            onUploaded={handleUploaded}
          />
        )}
        <Footer />
      </LocaleProvider>
    </ThemeProvider>
  )
}
