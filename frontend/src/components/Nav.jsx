import { useLocale } from '../context/LocaleContext.jsx'
import LangToggle from './LangToggle.jsx'
import ThemeToggle from './ThemeToggle.jsx'

export default function Nav({ view, onHome, onReadText }) {
  const { t } = useLocale()

  return (
    <header className="nav">
      <div className="nav-inner">
        <div className="nav-brand">
          <span className="nav-mark" aria-hidden="true">
            R
          </span>
          <span className="nav-title">{t('app_title')}</span>
        </div>
        <div className="nav-actions">
          <nav className="nav-links" aria-label={t('app_title')}>
            <button
              type="button"
              className={`nav-link${view === 'home' ? ' nav-link--active' : ''}`}
              onClick={onHome}
            >
              {t('nav_analyse')}
            </button>
            <button
              type="button"
              className={`nav-link${view === 'read-text' ? ' nav-link--active' : ''}`}
              onClick={onReadText}
            >
              {t('nav_read_text')}
            </button>
          </nav>
          <LangToggle />
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}
