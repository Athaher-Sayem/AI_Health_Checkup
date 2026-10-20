import { useLocale } from '../context/LocaleContext.jsx'
import ThemeToggle from './ThemeToggle.jsx'

export default function Nav() {
  const { t } = useLocale()
  return (
    <nav style={{
      position: 'sticky', top: 0, zIndex: 20,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: 'var(--space-3) var(--space-6)',
      background: 'var(--surface)', borderBottom: '1px solid var(--border)',
      backdropFilter: 'blur(8px)',
    }}>
      <span style={{ fontFamily: 'var(--font-display)', fontWeight: 600, fontSize: 'var(--fs-18)' }}>
        {t('app_title')}
      </span>
      <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
        <ThemeToggle />
      </div>
    </nav>
  )
}