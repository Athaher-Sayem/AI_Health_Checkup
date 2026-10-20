import { useTheme } from '../context/ThemeContext.jsx'

export default function ThemeToggle() {
  const { theme, toggle } = useTheme()
  return (
    <button className="theme-toggle" onClick={toggle} aria-label="Toggle theme" type="button">
      {theme === 'dark' ? '☀ Light' : '☾ Dark'}
    </button>
  )
}