import { createContext, useContext, useState } from 'react'
import bn from '../i18n/bn.json'
import en from '../i18n/en.json'

const DICTS = { bn, en }
const LocaleContext = createContext({ locale: 'bn', setLocale: () => {}, t: (k) => k })

export function LocaleProvider({ children }) {
  const [locale, setLocale] = useState(() => localStorage.getItem('locale') || 'bn')
  const dict = DICTS[locale] || DICTS.bn
  const t = (key) => (dict[key] !== undefined ? dict[key] : key)
  const value = {
    locale,
    setLocale: (l) => { localStorage.setItem('locale', l); setLocale(l) },
    t,
  }
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
}

export function useLocale() {
  return useContext(LocaleContext)
}