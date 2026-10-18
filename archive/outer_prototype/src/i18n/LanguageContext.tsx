import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import languageData from '../mocks/languages.json'
import { translate } from './translations'

type Language = { id: string; tag: string; englishName: string; nativeName: string; script: string; rtl: boolean; ttsSupported: boolean }
const languages = languageData as Language[]
const supportedTags = new Set(languages.map((language) => language.tag))
const supportedLanguages = languages.filter((language) => supportedTags.has(language.tag))
type LanguageContextValue = { language: Language; options: Language[]; setLanguage: (tag: string) => void; t: (key: string) => string }
const Context = createContext<LanguageContextValue | null>(null)

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [tag, setTag] = useState(() => {
    const saved = window.localStorage.getItem('yatra-language')
    return supportedTags.has(saved ?? '') ? saved! : 'en-IN'
  })
  const language = supportedLanguages.find((item) => item.tag === tag) ?? supportedLanguages[0]
  useEffect(() => {
    document.documentElement.lang = language.tag
    document.documentElement.dir = language.rtl ? 'rtl' : 'ltr'
    window.localStorage.setItem('yatra-language', language.tag)
  }, [language])
  const value = useMemo(() => ({ language, options: supportedLanguages, setLanguage: (next: string) => { if (supportedTags.has(next)) setTag(next) }, t: (key: string) => translate(language.tag, key) }), [language])
  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useLanguage() {
  const context = useContext(Context)
  if (!context) throw new Error('useLanguage must be used inside LanguageProvider')
  return context
}
