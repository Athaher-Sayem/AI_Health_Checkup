import { useLocale } from '../context/LocaleContext.jsx'
import ThemeToggle from './ThemeToggle.jsx'

export default function Nav({ view, onHome, onReadText }) {
  const { t } = useLocale()

  return (
    <header className="nav">
      <div className="nav-inner">
        <button type="button" className="nav-brand" onClick={onHome} aria-label="AI Health home">
          <span className="nav-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M3 12h4l3-7 4 14 3-7h4" /></svg>
          </span>
          <span className="nav-title">AI Health<span className="nav-subtitle">Report explainer</span></span>
        </button>
        <div className="nav-actions">
          <nav className="nav-links" aria-label={t('app_title')}>
            <button
              type="button"
              className={`nav-link${view !== 'read-text' ? ' nav-link--active' : ''}`}
              onClick={onHome}
              aria-current={view !== 'read-text' ? 'page' : undefined}
            >
              {t('nav_analyse')}
            </button>
            <button
              type="button"
              className={`nav-link${view === 'read-text' ? ' nav-link--active' : ''}`}
              onClick={onReadText}
              aria-current={view === 'read-text' ? 'page' : undefined}
            >
              {t('nav_read_text')}
            </button>
          </nav>
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}
