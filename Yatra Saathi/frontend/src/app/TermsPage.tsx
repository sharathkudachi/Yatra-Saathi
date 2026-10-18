import React, { useEffect } from 'react'
import { ArrowLeft, CheckCircle2, AlertTriangle, Scale, Info } from 'lucide-react'
import { BrandLogo } from './BrandLogo'

interface TermsPageProps {
  onNavigate: (path: string) => void
}

export const TermsPage: React.FC<TermsPageProps> = ({ onNavigate }) => {
  useEffect(() => {
    document.title = 'Terms of Service — Yatra Saathi'
    const metaDesc = document.querySelector('meta[name="description"]')
    if (metaDesc) {
      metaDesc.setAttribute('content', 'Terms and conditions governing the use of Yatra Saathi, detailing simulated booking disclosures, catalog limitations, and acceptable use.')
    }
    window.scrollTo({ top: 0, behavior: 'smooth' })
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
            <span>Back to Travel Planner</span>
          </button>
        </div>
      </header>

      <main className="legal-content">
        <div className="legal-container">
          <div className="legal-badge">
            <Scale size={14} />
            <span>TERMS &amp; CONDITIONS OF USE</span>
          </div>

          <h1 className="legal-title">Terms of Service</h1>
          <p className="legal-meta">
            Effective Date: October 16, 2026 &nbsp;|&nbsp; Version: 1.0 (Pre-launch Specification)
          </p>

          <div className="legal-callout">
            <div className="legal-callout-icon">
              <Info size={18} />
            </div>
            <div>
              <strong>Demonstration &amp; Simulation Disclosure</strong>
              <p>
                Yatra Saathi is currently operating in a demonstration environment. Bookings confirmed through this
                interface are simulated demonstration records (e.g. <code>YTR-DEMO-...</code>) designed to validate
                full-lifecycle travel planning workflows. No real financial transaction, credit card charge, or
                live carrier reservation has occurred.
              </p>
            </div>
          </div>

          <section className="legal-section">
            <h2>1. Agreement to Terms</h2>
            <p>
              By accessing, browsing, or using the Yatra Saathi platform (&quot;the Service&quot;),
              you acknowledge that you have read, understood, and agreed to be bound by these Terms of Service.
              If you do not agree with any part of these terms, please discontinue use of the platform.
            </p>
          </section>

          <section className="legal-section">
            <h2>2. Nature of the Travel Planning Service</h2>
            <p>
              Yatra Saathi provides an intelligent software companion designed to help travellers compose, organize,
              and review travel itineraries, accommodation choices, and flight options:
            </p>
            <ul>
              <li>
                <strong>Assistant Function:</strong> The AI travel concierge provides suggestions based on user prompts
                and structured preference inputs. Suggestions are intended for trip preparation and exploratory planning.
              </li>
              <li>
                <strong>Catalog Grounding:</strong> Hotel options, airport coordinates, and attraction entries are sourced
                from curated catalog records. Real-world conditions (such as seasonal weather, local holidays, or road works)
                may affect actual travel times.
              </li>
            </ul>
          </section>

          <section className="legal-section">
            <h2>3. Pricing, Estimates &amp; Authoritative Reviews</h2>
            <p>
              Yatra Saathi maintains a strict boundary between initial conversational estimates and authoritative calculations:
            </p>
            <div className="legal-grid">
              <div className="legal-card">
                <div className="legal-card-header">
                  <CheckCircle2 size={16} />
                  <h3>Authoritative Backend Totals</h3>
                </div>
                <p>
                  Prices shown in the Booking Review modal and My Trips summary are calculated authoritatively by
                  the backend service using inventory tariffs, room types, stay durations, and standard taxes.
                  These figures represent the official price breakdown for the simulated booking.
                </p>
              </div>

              <div className="legal-card">
                <div className="legal-card-header">
                  <AlertTriangle size={16} />
                  <h3>Conversational &amp; Search Estimates</h3>
                </div>
                <p>
                  Preliminary figures mentioned in chat briefs or search banners are indicative planning figures.
                  Always verify exact itemized costs in the authoritative Booking Review modal prior to finalizing a plan.
                </p>
              </div>
            </div>
          </section>

          <section className="legal-section">
            <h2>4. Simulated Booking &amp; Cancellation Protocol</h2>
            <p>
              All reservations initiated within the application are strictly local demonstration bookings:
            </p>
            <ul>
              <li>
                <strong>No Real Financial Charges:</strong> Yatra Saathi does not charge your payment card or hold escrow funds.
                Simulated booking codes are issued solely to test booking state lifecycles and verify record integrity.
              </li>
              <li>
                <strong>Cancellation:</strong> You may cancel any simulated booking at any time directly through the
                &quot;My Trips&quot; interface. Cancellation updates the booking status in the local working database
                without incurring penalties.
              </li>
              <li>
                <strong>Real Travel Booking:</strong> Users requiring actual commercial airline tickets or guaranteed hotel
                rooms must book directly through certified airlines, hoteliers, or authorized travel agencies.
              </li>
            </ul>
          </section>

          <section className="legal-section">
            <h2>5. User Responsibilities &amp; Acceptable Use</h2>
            <p>When using the Service, you agree to:</p>
            <ul>
              <li>Provide accurate information when creating an account and configuring travel preferences.</li>
              <li>Maintain the confidentiality of your account credentials and immediately notify us of unauthorized access.</li>
              <li>Refrain from automated scraping, rate-limit evasion, reverse engineering, or exploiting platform APIs.</li>
              <li>Not use the platform to transmit unlawful, harmful, defamatory, or abusive material.</li>
            </ul>
          </section>

          <section className="legal-section">
            <h2>6. Intellectual Property &amp; Map Data Attribution</h2>
            <p>
              The Yatra Saathi software, trademarks, logos, and custom interface designs are the property of the project authors.
              Map visuals and tile data are provided by <strong>OpenStreetMap</strong> contributors under the Open Database
              License (ODbL). All map representations honor OpenStreetMap attribution standards.
            </p>
          </section>

          <section className="legal-section">
            <h2>7. Limitation of Liability</h2>
            <p>
              The Service is provided &quot;as is&quot; and &quot;as available&quot; without warranties of any kind, either express
              or implied. To the maximum extent permitted by applicable law, Yatra Saathi and its maintainers shall not be liable for
              any direct, indirect, incidental, special, or consequential damages resulting from:
            </p>
            <ul>
              <li>Reliance on exploratory itinerary timing or estimated travel buffers.</li>
              <li>Temporary downtime, network interruptions, or external provider outages (including map tiles or LLM endpoints).</li>
              <li>Any decision made or action taken in reliance upon demonstration or simulated travel plans.</li>
            </ul>
          </section>

          <section className="legal-section">
            <h2>8. Owner Review &amp; Governing Law</h2>
            <div className="legal-contact-box">
              <p><strong>Operating Entity:</strong> [Legal Entity Name to be specified prior to production launch]</p>
              <p><strong>Jurisdiction:</strong> [Applicable state/national jurisdiction to be designated prior to launch]</p>
              <p><strong>Legal Contact:</strong> <code>legal@example.com</code> [Placeholder — owner review required]</p>
            </div>
          </section>
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
              className="active-legal-link"
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
