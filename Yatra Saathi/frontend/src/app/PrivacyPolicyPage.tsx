import React, { useEffect } from 'react'
import { ArrowLeft, ShieldCheck, Lock, Database, Eye, Bell, AlertCircle } from 'lucide-react'
import { BrandLogo } from './BrandLogo'

interface PrivacyPolicyPageProps {
  onNavigate: (path: string) => void
}

export const PrivacyPolicyPage: React.FC<PrivacyPolicyPageProps> = ({ onNavigate }) => {
  useEffect(() => {
    document.title = 'Privacy Policy — Yatra Saathi'
    const metaDesc = document.querySelector('meta[name="description"]')
    if (metaDesc) {
      metaDesc.setAttribute('content', 'Read the Yatra Saathi Privacy Policy detailing data handling, account credentials, AI integrations, map tile requests, and simulated booking records.')
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
            <ShieldCheck size={14} />
            <span>TRANSPARENCY &amp; DATA HANDLING</span>
          </div>

          <h1 className="legal-title">Privacy Policy</h1>
          <p className="legal-meta">
            Effective Date: October 16, 2026 &nbsp;|&nbsp; Version: 1.0 (Pre-launch Specification)
          </p>

          <div className="legal-callout">
            <div className="legal-callout-icon">
              <AlertCircle size={18} />
            </div>
            <div>
              <strong>Owner &amp; Entity Notice</strong>
              <p>
                This privacy policy reflects the actual technical implementation and data flows of the Yatra Saathi
                application. Certain legal entity contact items are placeholders marked
                for review prior to public production deployment.
              </p>
            </div>
          </div>

          <section className="legal-section">
            <h2>1. Introduction &amp; Service Scope</h2>
            <p>
              Yatra Saathi (&quot;we&quot;, &quot;our&quot;, or &quot;the Service&quot;) is an AI-assisted travel planning
              and companion platform. This Privacy Policy explains what personal and technical data is processed
              when you create an account, plan itineraries, search flights and stays, interact with our travel companion,
              and manage simulated bookings.
            </p>
            <p>
              We prioritize data minimization: we collect and store only the data required to generate valid
              itineraries, calculate authoritative trip totals, retain saved trips, and deliver travel assistance.
            </p>
          </section>

          <section className="legal-section">
            <h2>2. Information We Process</h2>
            <div className="legal-grid">
              <div className="legal-card">
                <div className="legal-card-header">
                  <Lock size={16} />
                  <h3>Account Credentials</h3>
                </div>
                <p>
                  When you register, we collect your display name, username, and email address. Passwords are
                  never stored in plaintext; they are securely hashed using modern Argon2id cryptographic hashing
                  before being written to the database.
                </p>
              </div>

              <div className="legal-card">
                <div className="legal-card-header">
                  <Database size={16} />
                  <h3>Travel Preferences &amp; Sessions</h3>
                </div>
                <p>
                  Your departure city, destination, travel dates, guest count, budget allowance, preferred pace,
                  and dietary or cultural preferences are stored to customize recommendations and itinerary schedules.
                </p>
              </div>

              <div className="legal-card">
                <div className="legal-card-header">
                  <Eye size={16} />
                  <h3>Itineraries &amp; Simulated Bookings</h3>
                </div>
                <p>
                  Saved trip plans, itinerary revisions, activity selections, and simulated booking records
                  (such as demo booking references) are associated with your authenticated user account.
                </p>
              </div>

              <div className="legal-card">
                <div className="legal-card-header">
                  <Bell size={16} />
                  <h3>Notification Preferences</h3>
                </div>
                <p>
                  Preferences for itinerary alerts, schedule shifts, and advisory reminders are stored locally
                  in browser storage and linked to your session.
                </p>
              </div>
            </div>
          </section>

          <section className="legal-section">
            <h2>3. Voice &amp; Chat Input Processing</h2>
            <p>
              When you use conversational planning or the voice assistant interface:
            </p>
            <ul>
              <li>
                <strong>Voice Recognition:</strong> Voice speech-to-text is performed via your browser&#39;s native Web
                Speech API where supported. Raw audio waveforms are not permanently recorded or uploaded to Yatra Saathi servers.
              </li>
              <li>
                <strong>Conversational Prompts:</strong> Text transcripts of your travel brief (for example: &quot;Plan a 3-day trip
                to Jaipur under ₹50,000&quot;) are processed through our bounded AI travel service.
              </li>
            </ul>
          </section>

          <section className="legal-section">
            <h2>4. Third-Party Integrations &amp; Data Transfers</h2>
            <p>
              To deliver accurate travel mapping and intelligent assistance, the Service communicates with the following external providers:
            </p>
            <ul>
              <li>
                <strong>OpenStreetMap (OSM) Tiles:</strong> Map visual tiles are requested directly by your browser from
                OpenStreetMap servers (<code>tile.openstreetmap.org</code>). OSM receives your IP address and standard HTTP request headers
                necessary to transmit map tiles in accordance with OpenStreetMap&#39;s Tile Usage Policy.
              </li>
              <li>
                <strong>AI Model Providers:</strong> When conversational planning is activated with an external LLM (such as Groq or OpenAI APIs),
                anonymized travel planning prompts are transmitted to the provider to parse trip requirements into structured parameters.
                No user passwords, financial data, or sensitive personal credentials are transmitted to AI providers.
              </li>
              <li>
                <strong>No Live Payment Processors:</strong> The current application operates in demonstration mode. No credit card, debit card,
                or banking details are collected, requested, or transmitted to payment gateways.
              </li>
            </ul>
          </section>

          <section className="legal-section">
            <h2>5. Data Storage, Security &amp; Retention</h2>
            <p>
              Data is stored in an authoritative SQLite database with foreign-key constraints and transactional isolation.
              Session tokens are verified using cryptographic signatures with defined expiry.
            </p>
            <p>
              Account data and saved itineraries are retained for the duration of your account. You can sign out at any time to terminate your
              active session and remove cached session tokens from your browser.
            </p>
          </section>

          <section className="legal-section">
            <h2>6. User Controls &amp; Account Rights</h2>
            <p>
              You maintain direct control over your travel data within Yatra Saathi:
            </p>
            <ul>
              <li><strong>Sign Out:</strong> Terminates the active session and clears local session cache.</li>
              <li><strong>Cancel Bookings:</strong> You can cancel any simulated booking directly from the My Trips portal.</li>
              <li><strong>Clear Preferences:</strong> Reset language, theme, and notification settings at any time in the Preferences panel.</li>
            </ul>
          </section>

          <section className="legal-section">
            <h2>7. Owner Review &amp; Contact Information</h2>
            <p>
              For privacy inquiries, data deletion requests, or questions regarding this policy, contact our privacy administration:
            </p>
            <div className="legal-contact-box">
              <p><strong>Operating Entity:</strong> [Legal Entity Name to be specified prior to production launch]</p>
              <p><strong>Privacy Contact:</strong> <code>privacy@example.com</code> [Placeholder — owner review required]</p>
              <p><strong>Physical Address:</strong> [Registered business address to be specified prior to production launch]</p>
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
              className="active-legal-link"
            >
              Privacy Policy
            </a>
          </div>
        </div>
      </footer>
    </div>
  )
}
