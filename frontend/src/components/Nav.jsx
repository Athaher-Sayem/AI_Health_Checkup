import { useLocale } from '../context/LocaleContext.jsx'
import LangToggle from './LangToggle.jsx'
import ThemeToggle from './ThemeToggle.jsx'

export default function Nav() {
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
          <LangToggle />
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}
