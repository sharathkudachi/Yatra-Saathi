import { useEffect, useState } from 'react'
import {
  AlertOctagon,
  AlertTriangle,
  Calendar,
  Check,
  Compass,
  Copy,
  Edit2,
  FileText,
  HeartHandshake,
  Hotel,
  Info,
  MapPin,
  Navigation,
  Phone,
  PhoneCall,
  Plus,
  RefreshCw,
  Search,
  Share2,
  Shield,
  ShieldAlert,
  Ticket,
  Trash2,
  User,
  Users,
  X,
} from 'lucide-react'
import { phase6Service } from '../services/phase6Service'
import type {
  ActivateSosResponse,
  EmergencyInfoResponse,
  EmergencyOfficialNumber,
  GeocodePlaceResult,
  LocationCoordinates,
  TrustedContact,
} from '../types/travel'

interface EmergencyAssistanceModalProps {
  isOpen: boolean
  onClose: () => void
  currentTripId?: string | null
}

type SosFlowState = 'idle' | 'confirming' | 'activating' | 'active' | 'failed'
type GeoStatus = 'idle' | 'detecting' | 'captured' | 'denied' | 'unavailable' | 'timeout'

export interface ConfirmedEmergencyLocation {
  source: 'gps' | 'geocoded' | 'manual_unverified'
  displayLabel: string
  coordinates?: {
    latitude: number
    longitude: number
    accuracy_meters?: number | null
  } | null
  placeId?: string | null
  capturedAt?: string | null
}

/** Authoritative verified official emergency numbers for India. */
const AUTHORITATIVE_OFFICIAL_SERVICES: EmergencyOfficialNumber[] = [
  {
    name: 'National Emergency Helpline',
    service_name: 'National Emergency Helpline',
    number: '112',
    description: 'Unified all-in-one helpline for Police, Fire, Ambulance, and Disaster Management across India.',
    is_toll_free: true,
  },
  {
    name: 'Police',
    service_name: 'Police',
    number: '100',
    description: 'Immediate law enforcement and safety assistance.',
    is_toll_free: true,
  },
  {
    name: 'Medical Ambulance',
    service_name: 'Medical Ambulance',
    number: '102',
    description: 'Emergency ambulance and medical response service.',
    is_toll_free: true,
  },
  {
    name: 'Fire & Rescue Services',
    service_name: 'Fire & Rescue Services',
    number: '101',
    description: 'Fire emergency and immediate hazard response.',
    is_toll_free: true,
  },
  {
    name: 'Women Safety Helpline',
    service_name: 'Women Safety Helpline',
    number: '1091',
    description: 'Dedicated safety helpline for women travellers.',
    is_toll_free: true,
  },
  {
    name: 'Incredible India Tourist Helpline',
    service_name: 'Incredible India Tourist Helpline',
    number: '1363',
    description: '24x7 multi-lingual tourist helpline by Ministry of Tourism, India.',
    is_toll_free: true,
  },
]

export default function EmergencyAssistanceModal({
  isOpen,
  onClose,
  currentTripId,
}: EmergencyAssistanceModalProps) {
  const [info, setInfo] = useState<EmergencyInfoResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Contacts state
  const [contacts, setContacts] = useState<TrustedContact[]>([])

  // Add contact form state
  const [showAddContact, setShowAddContact] = useState(false)
  const [contactName, setContactName] = useState('')
  const [contactRel, setContactRel] = useState('')
  const [contactPhone, setContactPhone] = useState('')
  const [contactIsPrimary, setContactIsPrimary] = useState(true)
  const [addingContact, setAddingContact] = useState(false)

  // Edit contact state
  const [editingContact, setEditingContact] = useState<TrustedContact | null>(null)
  const [editName, setEditName] = useState('')
  const [editRel, setEditRel] = useState('')
  const [editPhone, setEditPhone] = useState('')
  const [editIsPrimary, setEditIsPrimary] = useState(false)
  const [updatingContact, setUpdatingContact] = useState(false)

  // Delete contact confirmation state
  const [deletingContact, setDeletingContact] = useState<TrustedContact | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  // Geolocation & Manual Location state
  const [geoStatus, setGeoStatus] = useState<GeoStatus>('idle')
  const [geoError, setGeoError] = useState<string | null>(null)
  const [confirmedLocation, setConfirmedLocation] = useState<ConfirmedEmergencyLocation | null>(null)
  const [manualLocationText, setManualLocationText] = useState('')
  const [isSearchingLocation, setIsSearchingLocation] = useState(false)
  const [searchResults, setSearchResults] = useState<GeocodePlaceResult[]>([])
  const [searchAttribution, setSearchAttribution] = useState('Data © OpenStreetMap contributors, ODbL 1.0')
  const [searchError, setSearchError] = useState<string | null>(null)
  const [hasSearched, setHasSearched] = useState(false)
  const [isRateLimited, setIsRateLimited] = useState(false)
  const [lastSearchedQuery, setLastSearchedQuery] = useState('')

  // Share confirmation dialog state
  const [shareTargetContact, setShareTargetContact] = useState<TrustedContact | null>(null)
  const [sharing, setSharing] = useState(false)

  // SOS activation state machine: idle -> confirming -> activating -> active | failed
  const [sosFlowState, setSosFlowState] = useState<SosFlowState>('idle')
  const [sosActiveResult, setSosActiveResult] = useState<ActivateSosResponse | null>(null)
  const [sosFailReason, setSosFailReason] = useState<string | null>(null)
  const [sosReasonNote, setSosReasonNote] = useState('')

  // Toast / feedback message timer
  useEffect(() => {
    if (message) {
      const timer = setTimeout(() => setMessage(null), 6000)
      return () => clearTimeout(timer)
    }
  }, [message])

  // Prevent background scroll while open and handle Escape key
  useEffect(() => {
    if (!isOpen) return

    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        if (deletingContact) {
          setDeletingContact(null)
        } else if (editingContact) {
          setEditingContact(null)
        } else if (shareTargetContact) {
          setShareTargetContact(null)
        } else if (showAddContact) {
          setShowAddContact(false)
        } else if (sosFlowState === 'confirming') {
          setSosFlowState('idle')
        } else {
          onClose()
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = originalOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen, deletingContact, editingContact, shareTargetContact, showAddContact, sosFlowState, onClose])

  // Load backend info upon opening
  useEffect(() => {
    if (isOpen) {
      void loadInfo()
      setSosFlowState('idle')
      setSosActiveResult(null)
      setSosFailReason(null)
      setShowAddContact(false)
      setEditingContact(null)
      setDeletingContact(null)
      setShareTargetContact(null)
      setGeoStatus('idle')
      setGeoError(null)
      setConfirmedLocation(null)
      setSearchResults([])
      setSearchError(null)
      setHasSearched(false)
      setIsRateLimited(false)
      setIsSearchingLocation(false)
    }
  }, [isOpen, currentTripId])

  async function loadInfo() {
    setLoading(true)
    setError(null)
    try {
      const data = await phase6Service.getEmergencyInfo(currentTripId || undefined)
      setInfo(data)
      const list = data.user_contacts || data.trusted_contacts || []
      setContacts(list)
    } catch (err: any) {
      setError(err?.message || 'Could not load emergency information. Authoritative numbers remain accessible.')
    } finally {
      setLoading(false)
    }
  }

  // Geolocation detection logic
  function handleDetectLocation() {
    if (!('geolocation' in navigator)) {
      setGeoStatus('unavailable')
      setGeoError('Geolocation is not supported by your browser.')
      return
    }

    setGeoStatus('detecting')
    setGeoError(null)

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = Number(pos.coords.latitude.toFixed(6))
        const lon = Number(pos.coords.longitude.toFixed(6))
        const acc = Math.round(pos.coords.accuracy)
        const nowIso = new Date(pos.timestamp).toISOString()

        setConfirmedLocation({
          source: 'gps',
          displayLabel: `GPS Coordinates (${lat.toFixed(4)}, ${lon.toFixed(4)})`,
          coordinates: { latitude: lat, longitude: lon, accuracy_meters: acc },
          capturedAt: nowIso,
        })
        setGeoStatus('captured')
        setMessage(`Current GPS location captured via device hardware (±${acc}m).`)
      },
      (err) => {
        if (err.code === 1) {
          setGeoStatus('denied')
          setGeoError('Location permission denied. You can search or enter your landmark below.')
        } else if (err.code === 2) {
          setGeoStatus('unavailable')
          setGeoError('Location position unavailable. Please search or enter location manually.')
        } else if (err.code === 3) {
          setGeoStatus('timeout')
          setGeoError('GPS signal timed out. Please search or enter location manually.')
        } else {
          setGeoStatus('unavailable')
          setGeoError('Failed to capture GPS coordinates. Please search or enter location manually.')
        }
      },
      {
        enableHighAccuracy: true,
        timeout: 12000,
        maximumAge: 10000,
      },
    )
  }

  // Manual Location search via Geocoding
  async function handleSearchLocation() {
    const query = manualLocationText.trim()
    if (query.length < 2) {
      setSearchError('Please type at least 2 characters to search for a location.')
      return
    }

    setIsSearchingLocation(true)
    setSearchError(null)
    setHasSearched(true)
    setIsRateLimited(false)
    setLastSearchedQuery(query)

    try {
      const resp = await phase6Service.searchLocation(query)
      setSearchResults(resp.results || [])
      if (resp.attribution) {
        setSearchAttribution(resp.attribution)
      }
      if (resp.rate_limited) {
        setIsRateLimited(true)
        setMessage('Geocoding rate limit reached. Displaying available or local results.')
      }
    } catch (err: any) {
      setSearchResults([])
      setSearchError(err?.message || 'Location search service is currently unavailable. You can click "Attach as Unverified Note" to attach your location without coordinates.')
    } finally {
      setIsSearchingLocation(false)
    }
  }

  // Confirm geocoded place selection
  function handleConfirmGeocodedPlace(place: GeocodePlaceResult) {
    const nowIso = new Date().toISOString()
    setConfirmedLocation({
      source: 'geocoded',
      displayLabel: place.display_name,
      coordinates: {
        latitude: place.latitude,
        longitude: place.longitude,
        accuracy_meters: null,
      },
      placeId: place.place_id,
      capturedAt: nowIso,
    })
    setGeoStatus('idle')
    setSearchResults([])
    setMessage(`Confirmed location: ${place.name} (Resolved via Map Geocoding).`)
  }

  // Attach manual landmark as unverified note
  function handleAttachManualNote() {
    const text = manualLocationText.trim()
    if (!text) {
      setSearchError('Please type a landmark or address first.')
      return
    }

    const nowIso = new Date().toISOString()
    setConfirmedLocation({
      source: 'manual_unverified',
      displayLabel: text,
      coordinates: null,
      capturedAt: nowIso,
    })
    setSearchResults([])
    setGeoStatus('idle')
    setMessage(`Attached "${text}" as unverified landmark note (No GPS coordinates).`)
  }

  // Clear confirmed location
  function handleClearLocation() {
    setConfirmedLocation(null)
    setGeoStatus('idle')
    setGeoError(null)
    setSearchResults([])
    setHasSearched(false)
  }

  // Helper to build location payload for SOS and Trip Share
  function getPreparedLocationPayload(): {
    locationPayload: LocationCoordinates | null
    locationTextPayload: string | undefined
  } {
    if (confirmedLocation?.source === 'gps' && confirmedLocation.coordinates) {
      return {
        locationPayload: {
          latitude: confirmedLocation.coordinates.latitude,
          longitude: confirmedLocation.coordinates.longitude,
          accuracy_meters: confirmedLocation.coordinates.accuracy_meters,
          source: 'gps',
          display_label: confirmedLocation.displayLabel,
          captured_at: confirmedLocation.capturedAt,
        },
        locationTextPayload: manualLocationText.trim() || undefined,
      }
    }
    if (confirmedLocation?.source === 'geocoded' && confirmedLocation.coordinates) {
      return {
        locationPayload: {
          latitude: confirmedLocation.coordinates.latitude,
          longitude: confirmedLocation.coordinates.longitude,
          accuracy_meters: null,
          source: 'geocoded',
          display_label: confirmedLocation.displayLabel,
          place_id: confirmedLocation.placeId,
          captured_at: confirmedLocation.capturedAt,
        },
        locationTextPayload: confirmedLocation.displayLabel,
      }
    }
    if (confirmedLocation?.source === 'manual_unverified') {
      return {
        locationPayload: null,
        locationTextPayload: confirmedLocation.displayLabel,
      }
    }
    if (manualLocationText.trim()) {
      return {
        locationPayload: null,
        locationTextPayload: manualLocationText.trim(),
      }
    }
    return {
      locationPayload: null,
      locationTextPayload: undefined,
    }
  }

  // Add Contact handler
  async function handleAddContact(e: React.FormEvent) {
    e.preventDefault()
    const cleanName = contactName.trim()
    const cleanRel = contactRel.trim()
    const cleanPhone = contactPhone.trim()

    if (cleanName.length < 2) {
      setError('Contact name must be at least 2 characters.')
      return
    }
    if (cleanRel.length < 2) {
      setError('Relationship must be at least 2 characters.')
      return
    }
    const digitsOnly = cleanPhone.replace(/[\s\-\(\)\+]/g, '')
    if (digitsOnly.length < 5 || !/^\d+$/.test(digitsOnly)) {
      setError('Please enter a valid phone number with at least 5 digits.')
      return
    }

    setAddingContact(true)
    setError(null)
    try {
      const created = await phase6Service.addTrustedContact({
        contact_name: cleanName,
        relationship: cleanRel,
        phone_number: cleanPhone,
        is_primary: contactIsPrimary,
      })
      const updatedList = [created, ...contacts]
      setContacts(updatedList)
      setInfo((prev) => (prev ? { ...prev, user_contacts: updatedList, trusted_contacts: updatedList } : prev))
      setContactName('')
      setContactRel('')
      setContactPhone('')
      setShowAddContact(false)
      setMessage(`Trusted contact ${created.contact_name || created.name} added successfully.`)
    } catch (err: any) {
      setError(err?.message || 'Could not add trusted contact. Please check details.')
    } finally {
      setAddingContact(false)
    }
  }

  // Open Edit Contact Form
  function openEditModal(contact: TrustedContact) {
    setEditingContact(contact)
    setEditName(contact.contact_name || contact.name || '')
    setEditRel(contact.relationship || '')
    setEditPhone(contact.phone_number || '')
    setEditIsPrimary(!!contact.is_primary)
  }

  // Save Edit Contact
  async function handleUpdateContact(e: React.FormEvent) {
    e.preventDefault()
    if (!editingContact) return

    const cleanName = editName.trim()
    const cleanRel = editRel.trim()
    const cleanPhone = editPhone.trim()

    if (cleanName.length < 2) {
      setError('Contact name must be at least 2 characters.')
      return
    }
    if (cleanRel.length < 2) {
      setError('Relationship must be at least 2 characters.')
      return
    }
    const digitsOnly = cleanPhone.replace(/[\s\-\(\)\+]/g, '')
    if (digitsOnly.length < 5 || !/^\d+$/.test(digitsOnly)) {
      setError('Please enter a valid phone number with at least 5 digits.')
      return
    }

    setUpdatingContact(true)
    setError(null)
    try {
      const updated = await phase6Service.updateTrustedContact(editingContact.contact_id, {
        contact_name: cleanName,
        relationship: cleanRel,
        phone_number: cleanPhone,
        is_primary: editIsPrimary,
      })
      const newList = contacts.map((c) => (c.contact_id === updated.contact_id ? updated : c))
      setContacts(newList)
      setInfo((prev) => (prev ? { ...prev, user_contacts: newList, trusted_contacts: newList } : prev))
      setEditingContact(null)
      setMessage(`Contact ${updated.contact_name || updated.name} updated successfully.`)
    } catch (err: any) {
      setError(err?.message || 'Could not update contact.')
    } finally {
      setUpdatingContact(false)
    }
  }

  // Delete Contact handler
  async function handleDeleteContact() {
    if (!deletingContact) return

    setIsDeleting(true)
    setError(null)
    try {
      await phase6Service.deleteTrustedContact(deletingContact.contact_id)
      const newList = contacts.filter((c) => c.contact_id !== deletingContact.contact_id)
      setContacts(newList)
      setInfo((prev) => (prev ? { ...prev, user_contacts: newList, trusted_contacts: newList } : prev))
      setMessage(`Removed ${deletingContact.contact_name || deletingContact.name} from trusted contacts.`)
      setDeletingContact(null)
    } catch (err: any) {
      setError(err?.message || 'Could not delete contact.')
    } finally {
      setIsDeleting(false)
    }
  }

  // Share trip confirmation handler
  async function handleConfirmShare() {
    const tripCtx = info?.trip_context || info?.current_trip_context
    if (!shareTargetContact || !tripCtx) return
    const { locationPayload, locationTextPayload } = getPreparedLocationPayload()
    setSharing(true)
    setError(null)
    try {
      const res = await phase6Service.shareTripDetails({
        trip_id: tripCtx.trip_id,
        trusted_contact_id: shareTargetContact.contact_id,
        explicit_user_confirmation: true,
        explicit_share_consent: true,
        location: locationPayload,
        location_text: locationTextPayload,
      })
      setMessage(
        `Trip details securely shared with ${shareTargetContact.contact_name || shareTargetContact.name} (Event: ${res.share_event_id}).`,
      )
      setShareTargetContact(null)
    } catch (err: any) {
      setError(err?.message || 'Failed to share trip details.')
    } finally {
      setSharing(false)
    }
  }

  // SOS Activation Handler
  async function handleConfirmSOS() {
    setSosFlowState('activating')
    setError(null)
    setSosFailReason(null)
    try {
      const tripCtx = info?.trip_context || info?.current_trip_context
      const { locationPayload, locationTextPayload } = getPreparedLocationPayload()
      const res = await phase6Service.activateSOS({
        trip_id: tripCtx?.trip_id,
        explicit_confirmation: true,
        location: locationPayload,
        location_text: locationTextPayload,
        reason: sosReasonNote.trim() || 'Explicit user activation from emergency modal',
        notes: locationTextPayload ? `Location note: ${locationTextPayload}` : undefined,
      })
      setSosActiveResult(res)
      setSosFlowState('active')
      setMessage('Authoritative Emergency Audit Event created (# ' + (res.sos_event_id || res.event_id) + ').')
    } catch (err: any) {
      setSosFlowState('failed')
      const msg = err?.message || 'Failed to record SOS event with backend.'
      setSosFailReason(msg)
      setError(msg)
    }
  }

  // Copy emergency text to clipboard
  function handleCopyEmergencySummary() {
    const tripCtx = info?.trip_context || info?.current_trip_context
    let text = `🚨 EMERGENCY ASSISTANCE ALERT (Yatra Saathi Companion)\n`
    if (tripCtx) {
      text += `Destination: ${tripCtx.destination || tripCtx.destination_city}\n`
      if (tripCtx.hotel_name) text += `Accommodation: ${tripCtx.hotel_name}\n`
      if (tripCtx.booking_reference) text += `Booking Ref: ${tripCtx.booking_reference}\n`
      if (tripCtx.start_date) text += `Dates: ${tripCtx.start_date} to ${tripCtx.end_date}\n`
    }
    if (confirmedLocation?.source === 'gps' && confirmedLocation.coordinates) {
      text += `GPS Coordinates: ${confirmedLocation.coordinates.latitude}, ${confirmedLocation.coordinates.longitude} (±${confirmedLocation.coordinates.accuracy_meters || 15}m) [Verified via device GPS hardware]\n`
      text += `Google Maps Link: https://maps.google.com/?q=${confirmedLocation.coordinates.latitude},${confirmedLocation.coordinates.longitude}\n`
    } else if (confirmedLocation?.source === 'geocoded' && confirmedLocation.coordinates) {
      text += `Geocoded Location: ${confirmedLocation.displayLabel}\n`
      text += `Coordinates: ${confirmedLocation.coordinates.latitude}, ${confirmedLocation.coordinates.longitude} [Resolved via Map Search, not device GPS]\n`
      text += `Google Maps Link: https://maps.google.com/?q=${confirmedLocation.coordinates.latitude},${confirmedLocation.coordinates.longitude}\n`
    } else if (confirmedLocation?.source === 'manual_unverified') {
      text += `Landmark Note: ${confirmedLocation.displayLabel} [Unverified manual text, no GPS coordinates]\n`
    } else if (manualLocationText.trim()) {
      text += `Landmark Note: ${manualLocationText.trim()} [Unverified manual text, no GPS coordinates]\n`
    }
    if (sosActiveResult) {
      text += `Audit Event Ref: ${sosActiveResult.sos_event_id || sosActiveResult.event_id}\n`
    }
    text += `National Emergency Helpline (India): 112\n`

    if (navigator?.clipboard?.writeText) {
      navigator.clipboard
        .writeText(text)
        .then(() => setMessage('Emergency details & coordinates copied to clipboard!'))
        .catch(() => setMessage('Copy failed. Please copy text manually.'))
    }
  }

  if (!isOpen) return null

  const displayServices =
    info?.official_numbers && info.official_numbers.length > 0
      ? info.official_numbers
      : info?.official_services && info.official_services.length > 0
        ? info.official_services
        : AUTHORITATIVE_OFFICIAL_SERVICES

  const tripContext = info?.trip_context || info?.current_trip_context

  return (
    <div
      className="modal-backdrop emergency-modal-backdrop"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <section
        className="confirm-modal emergency-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="emergency-modal-title"
      >
        <button className="modal-close" aria-label="Close emergency assistance" onClick={onClose}>
          <X size={19} />
        </button>

        {/* Modal Header */}
        <div className="emergency-header">
          <div className="emergency-alert-icon">
            <ShieldAlert size={28} />
          </div>
          <div>
            <span className="mini-label danger-label">Safety & Crisis Support</span>
            <h2 id="emergency-modal-title">Emergency Assistance</h2>
          </div>
        </div>

        {/* Life Safety Disclaimer */}
        <div className="emergency-banner-disclaimer" role="alert">
          <AlertOctagon size={22} className="disclaimer-icon" />
          <div>
            <strong>If you are in immediate danger, dial 112 directly on your phone.</strong>
            <p>
              In India, <strong>112</strong> connects you to unified Police, Medical Ambulance, Fire, and Disaster
              Management. Yatra Saathi is a supplementary trip companion and does not replace official emergency dispatch.
            </p>
          </div>
        </div>

        {/* Status / Error Toast Notifications */}
        {message && (
          <div className="modal-result emergency-success" role="status">
            <Check size={16} /> {message}
          </div>
        )}
        {error && (
          <div className="modal-result signin-error" role="alert">
            <AlertTriangle size={16} /> {error}
          </div>
        )}

        {/* SOS ACTIVE BANNER */}
        {sosFlowState === 'active' && sosActiveResult && (
          <div className="sos-active-card" role="alert">
            <div className="sos-active-header">
              <Shield size={24} className="shield-active-icon" />
              <div>
                <strong>SOS Assistance Logged</strong>
                <small>Audit Reference: {sosActiveResult.sos_event_id || sosActiveResult.event_id}</small>
              </div>
              <span className="status-badge live-badge">Audit Logged</span>
            </div>

            <p className="sos-active-notice">{sosActiveResult.emergency_notice}</p>

            <div className="sos-honest-disclosure">
              <Info size={16} />
              <span>
                <strong>Capability Disclosure:</strong> External automated SMS dispatch is in Demo Simulation mode.
                Dial 112 immediately on your device for emergency service dispatch.
              </span>
            </div>

            <div className="sos-active-actions">
              <a href="tel:112" className="sos-dial-112-btn" title="Call 112 National Emergency Helpline">
                <PhoneCall size={18} /> Call 112 Directly Now
              </a>
              <button type="button" className="sos-copy-btn" onClick={handleCopyEmergencySummary}>
                <Copy size={16} /> Copy Emergency & Location Details
              </button>
            </div>

            {sosActiveResult.instructions && sosActiveResult.instructions.length > 0 && (
              <div className="sos-instructions-box">
                <h4>Crisis Assistance Steps:</h4>
                <ul className="sos-instructions-list">
                  {sosActiveResult.instructions.map((inst, idx) => (
                    <li key={idx}>{inst}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* SOS FAILED BANNER WITH RETRY */}
        {sosFlowState === 'failed' && (
          <div className="sos-failed-card" role="alert">
            <div className="sos-failed-header">
              <AlertTriangle size={20} />
              <div>
                <strong>SOS Activation Incomplete</strong>
                <p>{sosFailReason || 'Could not contact the emergency audit service.'}</p>
              </div>
            </div>
            <div className="sos-failed-actions">
              <a href="tel:112" className="emergency-call-btn danger" title="Call 112 directly">
                <PhoneCall size={16} /> Call 112 Directly
              </a>
              <button type="button" className="modal-primary retry-btn" onClick={() => void handleConfirmSOS()}>
                <RefreshCw size={15} /> Retry SOS Activation
              </button>
            </div>
          </div>
        )}

        {loading ? (
          <div className="emergency-loading">
            <span className="spinner" /> Loading emergency services and contacts...
          </div>
        ) : (
          <div className="emergency-content-scroll">
            {/* Section 1: Official Verified Emergency Numbers */}
            <section className="emergency-section">
              <div className="section-title-row">
                <PhoneCall size={16} />
                <h3>Official Emergency Contacts (India)</h3>
              </div>
              <p className="section-subtitle">
                Authoritative numbers configured and verified. Tapping a call button opens your device&apos;s phone
                dialer:
              </p>

              <div className="emergency-numbers-grid">
                {displayServices.map((item) => {
                  const sName = item.name || item.service_name
                  return (
                    <a
                      key={item.number}
                      href={`tel:${item.number}`}
                      className="emergency-number-card"
                      title={`Open phone dialer to call ${sName} on ${item.number}`}
                    >
                      <div className="number-dial-badge">
                        <Phone size={14} />
                        <span className="dial-digit">{item.number}</span>
                      </div>
                      <div className="number-details">
                        <strong>{sName}</strong>
                        <span>{item.description}</span>
                        <span className="dialer-note">Tap to open dialer</span>
                      </div>
                    </a>
                  )
                })}
              </div>
            </section>

            {/* Section 2: Active Trip Context for Emergency */}
            {tripContext && (
              <section className="emergency-section trip-context-section">
                <div className="section-title-row">
                  <Ticket size={16} />
                  <h3>Active Trip Context for Emergency</h3>
                </div>
                <div className="trip-context-card">
                  <div className="trip-context-item">
                    <MapPin size={14} />
                    <span>Destination:</span>
                    <strong>{tripContext.destination || tripContext.destination_city}</strong>
                  </div>
                  {tripContext.booking_reference && (
                    <div className="trip-context-item">
                      <Ticket size={14} />
                      <span>Booking Reference:</span>
                      <code>{tripContext.booking_reference}</code>
                    </div>
                  )}
                  {tripContext.hotel_name && (
                    <div className="trip-context-item">
                      <Hotel size={14} />
                      <span>Accommodation:</span>
                      <strong>{tripContext.hotel_name}</strong>
                    </div>
                  )}
                  {tripContext.start_date && (
                    <div className="trip-context-item">
                      <Calendar size={14} />
                      <span>Trip Dates:</span>
                      <strong>
                        {tripContext.start_date} → {tripContext.end_date}
                      </strong>
                    </div>
                  )}
                  {tripContext.traveller_count && (
                    <div className="trip-context-item">
                      <Users size={14} />
                      <span>Travellers:</span>
                      <strong>{tripContext.traveller_count}</strong>
                    </div>
                  )}
                </div>
              </section>
            )}

            {/* Section 3: Geolocation Sharing & Privacy */}
            <section className="emergency-section location-section">
              <div className="section-title-row">
                <Compass size={16} />
                <h3>Location Coordinates & Landmark</h3>
              </div>
              <p className="section-subtitle">
                Location is collected only when you explicitly tap &quot;Detect GPS Location&quot; or search a place, and is shared only with your emergency audit record.
              </p>

              <div className="location-control-card">
                {/* Active Confirmed Location Display */}
                {confirmedLocation && (
                  <div className={`confirmed-location-card confirmed-${confirmedLocation.source}`}>
                    <div className="confirmed-loc-header">
                      {confirmedLocation.source === 'gps' && (
                        <div className="loc-badge-group">
                          <Navigation size={16} className="loc-icon-gps" />
                          <span className="loc-status-pill pill-gps">
                            <Compass size={12} /> GPS Confirmed Coordinates
                          </span>
                        </div>
                      )}
                      {confirmedLocation.source === 'geocoded' && (
                        <div className="loc-badge-group">
                          <MapPin size={16} className="loc-icon-geocoded" />
                          <span className="loc-status-pill pill-geocoded">
                            <MapPin size={12} /> Geocoding Confirmed Location
                          </span>
                        </div>
                      )}
                      {confirmedLocation.source === 'manual_unverified' && (
                        <div className="loc-badge-group">
                          <FileText size={16} className="loc-icon-manual" />
                          <span className="loc-status-pill pill-manual">
                            <FileText size={12} /> Unverified Landmark Text
                          </span>
                        </div>
                      )}
                      <button
                        type="button"
                        className="location-clear-btn"
                        onClick={handleClearLocation}
                        title="Change or remove confirmed location"
                      >
                        Change / Remove
                      </button>
                    </div>

                    <div className="confirmed-loc-body">
                      {confirmedLocation.source === 'gps' && confirmedLocation.coordinates && (
                        <>
                          <strong>
                            Coordinates: {confirmedLocation.coordinates.latitude.toFixed(4)},{' '}
                            {confirmedLocation.coordinates.longitude.toFixed(4)}
                          </strong>
                          <small>
                            Accuracy: ±{confirmedLocation.coordinates.accuracy_meters}m · Verified directly via device GPS hardware.
                          </small>
                        </>
                      )}
                      {confirmedLocation.source === 'geocoded' && confirmedLocation.coordinates && (
                        <>
                          <strong>{confirmedLocation.displayLabel}</strong>
                          <small>
                            Coordinates: {confirmedLocation.coordinates.latitude.toFixed(4)},{' '}
                            {confirmedLocation.coordinates.longitude.toFixed(4)} · Resolved via Map Search (not device GPS).
                          </small>
                        </>
                      )}
                      {confirmedLocation.source === 'manual_unverified' && (
                        <>
                          <strong>&quot;{confirmedLocation.displayLabel}&quot;</strong>
                          <small>
                            Manual text note only. No GPS coordinates attached to this note.
                          </small>
                        </>
                      )}
                    </div>
                  </div>
                )}

                {/* GPS Status feedback when detecting or error */}
                {!confirmedLocation && (
                  <div className="location-status-row">
                    {geoStatus === 'detecting' && (
                      <span className="loc-status-pill detecting">
                        <span className="spinner dark-spinner" /> Detecting GPS signal...
                      </span>
                    )}
                    {geoStatus === 'denied' && (
                      <div className="loc-error-box">
                        <AlertTriangle size={15} />
                        <span>Permission Denied: Please search or provide your landmark below.</span>
                      </div>
                    )}
                    {(geoStatus === 'unavailable' || geoStatus === 'timeout') && (
                      <div className="loc-error-box">
                        <AlertTriangle size={15} />
                        <span>{geoError || 'GPS coordinates unavailable. Please search or enter landmark manually.'}</span>
                      </div>
                    )}
                  </div>
                )}

                {/* GPS Detection Action */}
                <div className="location-buttons-row">
                  <button
                    type="button"
                    className="location-detect-btn"
                    onClick={handleDetectLocation}
                    disabled={geoStatus === 'detecting'}
                  >
                    <Compass size={14} />{' '}
                    {confirmedLocation?.source === 'gps' ? 'Re-detect GPS Location' : 'Detect GPS Location'}
                  </button>
                </div>

                {/* Manual Location Search and Attachment Controls */}
                <div className="manual-location-field">
                  <label htmlFor="manual-location-input">
                    Or specify Landmark / Place / Address manually:
                  </label>
                  <div className="manual-location-input-group">
                    <input
                      id="manual-location-input"
                      type="text"
                      placeholder="e.g. Hoskote, Bangalore or Near Hawa Mahal, Jaipur"
                      value={manualLocationText}
                      onChange={(e) => setManualLocationText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault()
                          void handleSearchLocation()
                        }
                      }}
                    />
                    <button
                      type="button"
                      id="find-location-btn"
                      className="location-action-btn search-btn"
                      onClick={() => void handleSearchLocation()}
                      disabled={isSearchingLocation || !manualLocationText.trim()}
                      title="Search places matching this location"
                    >
                      {isSearchingLocation ? (
                        <>
                          <span className="spinner dark-spinner" /> Searching...
                        </>
                      ) : (
                        <>
                          <Search size={14} /> Find Location
                        </>
                      )}
                    </button>
                    <button
                      type="button"
                      id="attach-manual-landmark-btn"
                      className="location-action-btn manual-btn"
                      onClick={handleAttachManualNote}
                      disabled={!manualLocationText.trim()}
                      title="Attach as unverified text note without GPS coordinates"
                    >
                      <FileText size={14} /> Attach as Unverified Note
                    </button>
                  </div>
                </div>

                {/* Geocoding Loading Indicator */}
                {isSearchingLocation && (
                  <div className="location-search-loading">
                    <span className="spinner dark-spinner" /> Searching OpenStreetMap places for &quot;
                    {manualLocationText.trim()}&quot;...
                  </div>
                )}

                {/* Selectable Search Results */}
                {searchResults.length > 0 && (
                  <div className="location-search-results">
                    <div className="search-results-header">
                      <span>Found {searchResults.length} location{searchResults.length > 1 ? 's' : ''}:</span>
                      {isRateLimited && (
                        <span className="rate-limit-badge" title="Provider rate limit reached; showing cached or local database results">
                          Cached / Local Results
                        </span>
                      )}
                      <small>Choose a place to confirm coordinates</small>
                    </div>
                    <div className="search-results-list">
                      {searchResults.map((place) => (
                        <div key={place.place_id} className="search-result-item">
                          <div className="result-place-info">
                            <strong>{place.name}</strong>
                            <span className="result-locality">
                              {place.locality ? `${place.locality}, ` : ''}{place.state || place.country}
                            </span>
                            <small className="result-display-name">{place.display_name}</small>
                            <span className="result-coords">
                              {place.latitude.toFixed(4)}, {place.longitude.toFixed(4)}
                            </span>
                          </div>
                          <button
                            type="button"
                            className="use-location-btn"
                            onClick={() => handleConfirmGeocodedPlace(place)}
                          >
                            <Check size={14} /> Use This Location
                          </button>
                        </div>
                      ))}
                    </div>
                    <div className="osm-attribution-note">
                      <Info size={12} /> {searchAttribution}
                    </div>
                  </div>
                )}

                {/* No Results Notice */}
                {hasSearched && searchResults.length === 0 && !isSearchingLocation && !searchError && (
                  <div className="location-no-results-box" role="status">
                    <AlertTriangle size={15} />
                    <div>
                      <strong>No matching places found for &quot;{lastSearchedQuery}&quot;</strong>
                      <p>
                        You can refine your search query, or click <strong>Attach as Unverified Note</strong> above to submit this landmark as a text description without coordinates.
                      </p>
                    </div>
                  </div>
                )}

                {/* Search Error / Rate Limit Notice */}
                {searchError && (
                  <div className="location-search-error-box" role="alert">
                    <AlertTriangle size={15} />
                    <div>
                      <strong>Location Search Notice:</strong> {searchError}
                      <p>
                        You can still click <strong>Attach as Unverified Note</strong> above to submit your text landmark directly.
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </section>

            {/* Section 4: Trusted Personal Contacts */}
            <section className="emergency-section">
              <div className="section-title-row header-with-action">
                <div className="title-left">
                  <HeartHandshake size={16} />
                  <h3>Trusted Contacts</h3>
                </div>
                {!showAddContact && (
                  <button
                    type="button"
                    className="notif-text-btn add-contact-btn"
                    onClick={() => {
                      setShowAddContact(true)
                      setEditingContact(null)
                    }}
                  >
                    <Plus size={14} /> Add Contact
                  </button>
                )}
              </div>

              {/* Add Contact Form */}
              {showAddContact && (
                <form className="add-contact-form" onSubmit={handleAddContact}>
                  <h4>Add New Trusted Person</h4>
                  <p className="form-subnote">Contacts are saved to your secure profile and reloaded automatically.</p>
                  <div className="contact-form-inputs">
                    <div>
                      <label htmlFor="contact-name-input">Full Name *</label>
                      <input
                        id="contact-name-input"
                        type="text"
                        placeholder="e.g. Ramesh Sharma"
                        value={contactName}
                        onChange={(e) => setContactName(e.target.value)}
                        required
                        minLength={2}
                      />
                    </div>
                    <div>
                      <label htmlFor="contact-rel-input">Relationship *</label>
                      <input
                        id="contact-rel-input"
                        type="text"
                        placeholder="e.g. Spouse, Sibling, Friend"
                        value={contactRel}
                        onChange={(e) => setContactRel(e.target.value)}
                        required
                        minLength={2}
                      />
                    </div>
                    <div>
                      <label htmlFor="contact-phone-input">Phone Number *</label>
                      <input
                        id="contact-phone-input"
                        type="tel"
                        placeholder="+91 98765 43210"
                        value={contactPhone}
                        onChange={(e) => setContactPhone(e.target.value)}
                        required
                        minLength={5}
                      />
                    </div>
                    <label className="primary-toggle-label">
                      <input
                        type="checkbox"
                        checked={contactIsPrimary}
                        onChange={(e) => setContactIsPrimary(e.target.checked)}
                      />
                      <span>Set as primary emergency contact</span>
                    </label>
                  </div>
                  <div className="contact-form-btns">
                    <button type="submit" className="modal-primary save-contact-btn" disabled={addingContact}>
                      {addingContact ? <span className="spinner" /> : 'Save Contact'}
                    </button>
                    <button
                      type="button"
                      className="modal-secondary cancel-contact-btn"
                      onClick={() => setShowAddContact(false)}
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              )}

              {/* Edit Contact Form */}
              {editingContact && (
                <form className="add-contact-form edit-contact-form" onSubmit={handleUpdateContact}>
                  <h4>Edit Trusted Contact</h4>
                  <div className="contact-form-inputs">
                    <div>
                      <label htmlFor="edit-name-input">Full Name *</label>
                      <input
                        id="edit-name-input"
                        type="text"
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        required
                        minLength={2}
                      />
                    </div>
                    <div>
                      <label htmlFor="edit-rel-input">Relationship *</label>
                      <input
                        id="edit-rel-input"
                        type="text"
                        value={editRel}
                        onChange={(e) => setEditRel(e.target.value)}
                        required
                        minLength={2}
                      />
                    </div>
                    <div>
                      <label htmlFor="edit-phone-input">Phone Number *</label>
                      <input
                        id="edit-phone-input"
                        type="tel"
                        value={editPhone}
                        onChange={(e) => setEditPhone(e.target.value)}
                        required
                        minLength={5}
                      />
                    </div>
                    <label className="primary-toggle-label">
                      <input
                        type="checkbox"
                        checked={editIsPrimary}
                        onChange={(e) => setEditIsPrimary(e.target.checked)}
                      />
                      <span>Set as primary emergency contact</span>
                    </label>
                  </div>
                  <div className="contact-form-btns">
                    <button type="submit" className="modal-primary save-contact-btn" disabled={updatingContact}>
                      {updatingContact ? <span className="spinner" /> : 'Update Contact'}
                    </button>
                    <button
                      type="button"
                      className="modal-secondary cancel-contact-btn"
                      onClick={() => setEditingContact(null)}
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              )}

              {/* Contacts List */}
              {contacts.length > 0 ? (
                <div className="trusted-contacts-list">
                  {contacts.map((contact) => {
                    const cName = contact.contact_name || contact.name || 'Trusted Contact'
                    return (
                      <div key={contact.contact_id} className="trusted-contact-card">
                        <div className="contact-avatar">
                          <User size={16} />
                        </div>
                        <div className="contact-info">
                          <div className="contact-name-row">
                            <strong>{cName}</strong>
                            {contact.is_primary && <span className="primary-badge">Primary</span>}
                          </div>
                          <span>
                            {contact.relationship} · {contact.phone_number}
                          </span>
                        </div>
                        <div className="contact-actions">
                          <a
                            href={`tel:${contact.phone_number}`}
                            className="contact-call-btn"
                            title={`Call ${cName}`}
                          >
                            <Phone size={14} /> Call
                          </a>
                          {tripContext && (
                            <button
                              type="button"
                              className="contact-share-btn"
                              title="Share trip details with this contact"
                              onClick={() => setShareTargetContact(contact)}
                            >
                              <Share2 size={14} /> Share Trip
                            </button>
                          )}
                          <button
                            type="button"
                            className="contact-icon-btn"
                            title="Edit contact"
                            onClick={() => openEditModal(contact)}
                            aria-label={`Edit ${cName}`}
                          >
                            <Edit2 size={14} />
                          </button>
                          <button
                            type="button"
                            className="contact-icon-btn danger"
                            title="Delete contact"
                            onClick={() => setDeletingContact(contact)}
                            aria-label={`Delete ${cName}`}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <div className="no-contacts-card">
                  <p className="no-contacts-note">
                    No trusted contacts configured. Add a family member or friend to quickly share trip details or live
                    coordinates during emergencies.
                  </p>
                </div>
              )}
            </section>

            {/* Section 5: Explicit SOS Activation Button */}
            <section className="emergency-section sos-action-section">
              <div className="sos-box">
                <div>
                  <h4>Emergency Assistance Audit & SOS Log</h4>
                  <p>
                    Log an explicit emergency event for your trip records, register crisis assistance steps, and prepare
                    location coordinates.
                  </p>
                </div>
                <button
                  type="button"
                  className="sos-activate-btn"
                  onClick={() => setSosFlowState('confirming')}
                  disabled={sosFlowState === 'activating'}
                >
                  <AlertTriangle size={18} /> Activate SOS Assistance
                </button>
              </div>
            </section>
          </div>
        )}

        {/* Share Trip Details Confirmation Subdialog */}
        {shareTargetContact && tripContext && (
          <div className="modal-backdrop inner-confirm-backdrop" role="presentation">
            <div className="confirm-modal inner-confirm-card" role="dialog" aria-modal="true">
              <div className="inner-confirm-header">
                <Share2 size={20} className="info-icon" />
                <h3>Share Trip Details Confirmation</h3>
              </div>
              <p className="inner-confirm-subtitle">
                You are about to share the following verified trip summary with{' '}
                <strong>{shareTargetContact.contact_name || shareTargetContact.name}</strong> (
                {shareTargetContact.relationship}):
              </p>
              <div className="share-summary-preview">
                <div>
                  <span>Destination:</span>{' '}
                  <strong>{tripContext.destination || tripContext.destination_city}</strong>
                </div>
                {tripContext.hotel_name && (
                  <div>
                    <span>Accommodation:</span> <strong>{tripContext.hotel_name}</strong>
                  </div>
                )}
                {tripContext.booking_reference && (
                  <div>
                    <span>Booking Reference:</span> <code>{tripContext.booking_reference}</code>
                  </div>
                )}
                {tripContext.start_date && (
                  <div>
                    <span>Dates:</span>{' '}
                    <strong>
                      {tripContext.start_date} → {tripContext.end_date}
                    </strong>
                  </div>
                )}
                {confirmedLocation?.source === 'gps' && confirmedLocation.coordinates && (
                  <div>
                    <span>GPS Coordinates:</span>{' '}
                    <strong>
                      {confirmedLocation.coordinates.latitude}, {confirmedLocation.coordinates.longitude} (±
                      {confirmedLocation.coordinates.accuracy_meters}m) [Device Hardware]
                    </strong>
                  </div>
                )}
                {confirmedLocation?.source === 'geocoded' && confirmedLocation.coordinates && (
                  <div>
                    <span>Geocoded Location:</span>{' '}
                    <strong>
                      {confirmedLocation.displayLabel} ({confirmedLocation.coordinates.latitude},{' '}
                      {confirmedLocation.coordinates.longitude}) [Map Geocoded]
                    </strong>
                  </div>
                )}
                {confirmedLocation?.source === 'manual_unverified' && (
                  <div>
                    <span>Location Note:</span>{' '}
                    <strong>{confirmedLocation.displayLabel} [Unverified Manual Note]</strong>
                  </div>
                )}
                {!confirmedLocation && manualLocationText.trim() && (
                  <div>
                    <span>Location Note:</span> <strong>{manualLocationText.trim()} [Unverified]</strong>
                  </div>
                )}
              </div>
              <div className="inner-confirm-actions">
                <button
                  type="button"
                  className="modal-primary"
                  onClick={() => void handleConfirmShare()}
                  disabled={sharing}
                >
                  {sharing ? <span className="spinner" /> : <><Check size={16} /> Confirm Share</>}
                </button>
                <button type="button" className="modal-secondary" onClick={() => setShareTargetContact(null)}>
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Delete Contact Confirmation Subdialog */}
        {deletingContact && (
          <div className="modal-backdrop inner-confirm-backdrop" role="presentation">
            <div className="confirm-modal inner-confirm-card" role="dialog" aria-modal="true">
              <div className="inner-confirm-header danger">
                <Trash2 size={20} className="danger-icon" />
                <h3>Remove Trusted Contact</h3>
              </div>
              <p className="inner-confirm-subtitle">
                Are you sure you want to remove{' '}
                <strong>{deletingContact.contact_name || deletingContact.name}</strong> ({deletingContact.relationship})
                from your trusted emergency contacts?
              </p>
              <div className="inner-confirm-actions">
                <button
                  type="button"
                  className="modal-primary danger-btn"
                  onClick={() => void handleDeleteContact()}
                  disabled={isDeleting}
                >
                  {isDeleting ? <span className="spinner" /> : 'Yes, Remove Contact'}
                </button>
                <button type="button" className="modal-secondary" onClick={() => setDeletingContact(null)}>
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Explicit SOS Activation Confirmation Subdialog */}
        {sosFlowState === 'confirming' && (
          <div className="modal-backdrop inner-confirm-backdrop" role="presentation">
            <div className="confirm-modal inner-confirm-card" role="dialog" aria-modal="true">
              <div className="inner-confirm-header danger">
                <AlertOctagon size={24} className="danger-icon" />
                <h3>Confirm SOS Assistance Activation</h3>
              </div>
              <p className="inner-confirm-subtitle">
                Are you sure you want to activate Emergency Assistance? This will create an authoritative audit event,
                attach your captured location, and present crisis assistance steps.
              </p>

              {confirmedLocation?.source === 'gps' && confirmedLocation.coordinates && (
                <div className="sos-confirm-loc-preview gps-confirmed">
                  <Navigation size={14} />
                  <span>
                    <strong>GPS Location Attached:</strong> {confirmedLocation.coordinates.latitude},{' '}
                    {confirmedLocation.coordinates.longitude} (±{confirmedLocation.coordinates.accuracy_meters}m) —
                    Verified via device hardware
                  </span>
                </div>
              )}
              {confirmedLocation?.source === 'geocoded' && confirmedLocation.coordinates && (
                <div className="sos-confirm-loc-preview geocoded-confirmed">
                  <MapPin size={14} />
                  <span>
                    <strong>Geocoded Location Attached:</strong> {confirmedLocation.displayLabel} (
                    {confirmedLocation.coordinates.latitude}, {confirmedLocation.coordinates.longitude}) — Resolved via
                    Map Search
                  </span>
                </div>
              )}
              {confirmedLocation?.source === 'manual_unverified' && (
                <div className="sos-confirm-loc-preview manual-unverified">
                  <FileText size={14} />
                  <span>
                    <strong>Manual Landmark Note Attached:</strong> &quot;{confirmedLocation.displayLabel}&quot; —{' '}
                    <em>Unverified manual text note. No GPS coordinates attached.</em>
                  </span>
                </div>
              )}
              {!confirmedLocation && (
                <div className="sos-confirm-loc-preview warning">
                  <AlertTriangle size={14} />
                  <span>
                    No verified location attached. You can detect coordinates, search for a place, or attach an unverified landmark note.
                  </span>
                </div>
              )}

              <div className="sos-reason-input">
                <label htmlFor="sos-reason">Brief note on the emergency situation (optional):</label>
                <input
                  id="sos-reason"
                  type="text"
                  placeholder="e.g. Medical issue, lost transport, safety concern"
                  value={sosReasonNote}
                  onChange={(e) => setSosReasonNote(e.target.value)}
                />
              </div>

              <div className="inner-confirm-actions">
                <button
                  type="button"
                  className="modal-primary sos-danger-btn"
                  onClick={() => void handleConfirmSOS()}
                >
                  Yes, Activate SOS
                </button>
                <button type="button" className="modal-secondary" onClick={() => setSosFlowState('idle')}>
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
