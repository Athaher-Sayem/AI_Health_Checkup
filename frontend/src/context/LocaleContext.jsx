import { createContext, useContext } from 'react'
import en from '../i18n/en.json'

const english = { locale: 'en', t: (key) => en[key] ?? key }
const LocaleContext = createContext(english)

export function LocaleProvider({ children }) {
  return <LocaleContext.Provider value={english}>{children}</LocaleContext.Provider>
}

export function useLocale() {
  return useContext(LocaleContext)
}
