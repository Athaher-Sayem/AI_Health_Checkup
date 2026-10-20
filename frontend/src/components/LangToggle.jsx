import { useLocale } from '../context/LocaleContext.jsx'

export default function LangToggle() {
  const { locale, setLocale } = useLocale()
  return (
    <button
      type="button"
      className="icon-btn"
      onClick={() => setLocale(locale === 'bn' ? 'en' : 'bn')}
      aria-label="Change language"
      title="Change language"
    >
      {locale === 'bn' ? 'EN' : 'বাং'}
    </button>
  )
}
