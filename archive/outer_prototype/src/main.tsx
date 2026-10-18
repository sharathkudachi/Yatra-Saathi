import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './app/App'
import { LanguageProvider } from './i18n/LanguageContext'
import './styles/index.css'
import './styles/features.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><LanguageProvider><App /></LanguageProvider></React.StrictMode>,
)
