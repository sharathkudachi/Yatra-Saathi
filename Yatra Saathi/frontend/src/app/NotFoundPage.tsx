import React, { useEffect } from 'react'
import { Compass, ArrowLeft, MapPin, Search } from 'lucide-react'
import { BrandLogo } from './BrandLogo'

interface NotFoundPageProps {
  onNavigate: (path: string) => void
}

export const NotFoundPage: React.FC<NotFoundPageProps> = ({ onNavigate }) => {
  useEffect(() => {
    document.title = '404 — Page Not Found | Yatra Saathi'
    const metaDesc = document.querySelector('meta[name="description"]')
    if (metaDesc) {
      metaDesc.setAttribute('content', 'The page you requested could not be found. Return to Yatra Saathi to plan your journey.')
    }
  }, [])

  return (
    <div className="legal-page-shell">
      <header className="legal-header">
        <div className="legal-header-inner">
          <a
            className="brand"
            href="/"
            onClick={(e) => {
              e.preventDefault()
              onNavigate('/')
            }}
            aria-label="Yatra Saathi home"
          >
            <BrandLogo size="md" />
          </a>
          <button
            type="button"
            className="legal-back-btn"
            onClick={() => onNavigate('/')}
          >
            <ArrowLeft size={16} />
            <span>Return to Travel Planner</span>
          </button>
        </div>
      </header>

      <main className="not-found-main">
        <div className="not-found-container">
          <div className="not-found-mark">
            <MapPin size={38} />
          </div>

          <span className="not-found-code">404 &middot; DESTINATION UNCHARTED</span>
          <h1 className="not-found-title">This page is off our map</h1>
          <p className="not-found-desc">
            We couldn&#39;t find the route or page you were looking for. It may have been moved, renamed,
            or was entered with a different URL path.
          </p>

          <div className="not-found-actions">
            <button
              type="button"
              className="not-found-primary-btn"
              onClick={() => onNavigate('/')}
            >
              <Compass size={16} />
              <span>Return to Travel Planner</span>
            </button>
            <button
              type="button"
              className="not-found-secondary-btn"
              onClick={() => {
                onNavigate('/')
                window.setTimeout(() => {
                  document.getElementById('explore')?.scrollIntoView({ behavior: 'smooth' })
                }, 100)
              }}
            >
              <Search size={15} />
              <span>Explore Destinations</span>
            </button>
          </div>
        </div>
      </main>

      <footer className="footer legal-footer">
        <div className="legal-footer-inner">
          <span>&copy; 2026 Yatra Saathi. Your Travel Companion.</span>
          <div className="legal-footer-links">
            <a
              href="/"
              onClick={(e) => {
                e.preventDefault()
                onNavigate('/')
              }}
            >
              Travel Planner
            </a>
            <span className="dot-sep">&middot;</span>
            <a
              href="/terms"
              onClick={(e) => {
                e.preventDefault()
                onNavigate('/terms')
              }}
            >
              Terms of Service
            </a>
            <span className="dot-sep">&middot;</span>
            <a
              href="/privacy"
              onClick={(e) => {
                e.preventDefault()
                onNavigate('/privacy')
              }}
            >
              Privacy Policy
            </a>
          </div>
        </div>
      </footer>
    </div>
  )
}
