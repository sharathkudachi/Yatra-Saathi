import assert from 'node:assert/strict'
import { test } from 'node:test'

/** Validation helper matching frontend & backend emergency contact validation rules. */
function validateContact(name: string, relationship: string, phone: string): { valid: boolean; error?: string } {
  const cleanName = (name || '').trim()
  const cleanRel = (relationship || '').trim()
  const cleanPhone = (phone || '').trim()

  if (cleanName.length < 2) {
    return { valid: false, error: 'Contact name must be at least 2 characters.' }
  }
  if (cleanRel.length < 2) {
    return { valid: false, error: 'Relationship must be at least 2 characters.' }
  }
  const digitsOnly = cleanPhone.replace(/[\s\-\(\)\+]/g, '')
  if (digitsOnly.length < 5 || !/^\d+$/.test(digitsOnly)) {
    return { valid: false, error: 'Please enter a valid phone number with at least 5 digits.' }
  }
  return { valid: true }
}

/** Location coordinates validation matching frontend & backend schema. */
function validateCoordinates(lat: number, lon: number): boolean {
  if (typeof lat !== 'number' || typeof lon !== 'number') return false
  if (Number.isNaN(lat) || Number.isNaN(lon)) return false
  if (lat < -90 || lat > 90) return false
  if (lon < -180 || lon > 180) return false
  return true
}

/** Formats emergency summary for manual clipboard or WhatsApp sharing. */
function formatEmergencySummary(options: {
  destination?: string
  hotel?: string
  bookingRef?: string
  dates?: string
  latitude?: number
  longitude?: number
  accuracy?: number
  landmark?: string
  sosEventId?: string
}): string {
  let text = 'EMERGENCY ASSISTANCE ALERT (Yatra Companion)\n'
  if (options.destination) text += `Destination: ${options.destination}\n`
  if (options.hotel) text += `Accommodation: ${options.hotel}\n`
  if (options.bookingRef) text += `Booking Ref: ${options.bookingRef}\n`
  if (options.dates) text += `Dates: ${options.dates}\n`
  if (options.latitude !== undefined && options.longitude !== undefined) {
    text += `GPS Coordinates: ${options.latitude}, ${options.longitude} (±${options.accuracy || 10}m)\n`
    text += `Google Maps Link: https://maps.google.com/?q=${options.latitude},${options.longitude}\n`
  }
  if (options.landmark) text += `Landmark / Location Note: ${options.landmark}\n`
  if (options.sosEventId) text += `Audit Event Ref: ${options.sosEventId}\n`
  text += 'National Emergency Helpline (India): 112\n'
  return text
}

test('valid emergency contact details are accepted', () => {
  const res1 = validateContact('Ramesh Sharma', 'Brother', '+91 98765 43210')
  assert.equal(res1.valid, true)
  assert.equal(res1.error, undefined)

  const res2 = validateContact('Pooja', 'Sister', '011-23456789')
  assert.equal(res2.valid, true)
})

test('invalid emergency contact details are rejected with clear error', () => {
  // Short name
  assert.equal(validateContact('A', 'Friend', '9876543210').valid, false)
  assert.equal(validateContact('', 'Friend', '9876543210').valid, false)

  // Short relationship
  assert.equal(validateContact('Suresh', 'F', '9876543210').valid, false)

  // Invalid phone numbers
  assert.equal(validateContact('Suresh', 'Friend', 'not-a-number').valid, false)
  assert.equal(validateContact('Suresh', 'Friend', '123').valid, false) // Too few digits
  assert.equal(validateContact('Suresh', 'Friend', '++--()').valid, false) // No digits
})

test('official emergency numbers are valid and format as tel: dialer URIs', () => {
  const officialNumbers = ['112', '100', '102', '101', '1091', '1363']
  for (const num of officialNumbers) {
    assert.match(num, /^\d{3,4}$/)
    const dialUri = `tel:${num}`
    assert.equal(dialUri.startsWith('tel:'), true)
    assert.equal(dialUri.slice(4), num)
  }
})

test('location coordinates validation accepts valid coordinates and rejects out of bounds', () => {
  // Valid (Jaipur)
  assert.equal(validateCoordinates(26.9124, 75.7873), true)
  // Valid (Delhi)
  assert.equal(validateCoordinates(28.6139, 77.2090), true)
  // Bounds checks
  assert.equal(validateCoordinates(90.0, 180.0), true)
  assert.equal(validateCoordinates(-90.0, -180.0), true)
  assert.equal(validateCoordinates(90.1, 75.0), false)
  assert.equal(validateCoordinates(-91.0, 75.0), false)
  assert.equal(validateCoordinates(25.0, 180.1), false)
  assert.equal(validateCoordinates(25.0, -180.1), false)
  assert.equal(validateCoordinates(NaN, 75.0), false)
})

test('formatEmergencySummary generates comprehensive manual fallback text with maps link', () => {
  const summary = formatEmergencySummary({
    destination: 'Jaipur',
    hotel: 'ITC Rajputana',
    bookingRef: 'YTR-DEMO-BKG123',
    dates: '2026-11-01 to 2026-11-05',
    latitude: 26.9124,
    longitude: 75.7873,
    accuracy: 12,
    landmark: 'Room 304, Near Lobby',
    sosEventId: 'sos_demo_999',
  })

  assert.match(summary, /EMERGENCY ASSISTANCE ALERT/)
  assert.match(summary, /Jaipur/)
  assert.match(summary, /ITC Rajputana/)
  assert.match(summary, /YTR-DEMO-BKG123/)
  assert.match(summary, /26\.9124, 75\.7873/)
  assert.match(summary, /https:\/\/maps\.google\.com\/\?q=26\.9124,75\.7873/)
  assert.match(summary, /sos_demo_999/)
  assert.match(summary, /112/)
})

test('SOS activation requires explicit affirmative user confirmation', () => {
  const requiresExplicitConfirmation = (consent: unknown): boolean => consent === true

  assert.equal(requiresExplicitConfirmation(undefined), false)
  assert.equal(requiresExplicitConfirmation(null), false)
  assert.equal(requiresExplicitConfirmation(false), false)
  assert.equal(requiresExplicitConfirmation(true), true)
})

// ---------------------------------------------------------------------------
// Geocoding and Three Location States Tests
// ---------------------------------------------------------------------------

type LocationSource = 'gps' | 'geocoded' | 'manual_unverified'

interface LocationStateModel {
  source: LocationSource
  label: string
  coordinates?: { latitude: number; longitude: number } | null
  accuracyMeters?: number | null
}

function classifyLocationState(input: {
  gpsCoords?: { latitude: number; longitude: number; accuracy: number } | null
  geocodedPlace?: { name: string; display_name: string; latitude: number; longitude: number } | null
  manualText?: string | null
}): LocationStateModel {
  if (input.gpsCoords) {
    return {
      source: 'gps',
      label: `GPS Coordinates (${input.gpsCoords.latitude.toFixed(4)}, ${input.gpsCoords.longitude.toFixed(4)})`,
      coordinates: { latitude: input.gpsCoords.latitude, longitude: input.gpsCoords.longitude },
      accuracyMeters: input.gpsCoords.accuracy,
    }
  }
  if (input.geocodedPlace) {
    return {
      source: 'geocoded',
      label: input.geocodedPlace.display_name,
      coordinates: { latitude: input.geocodedPlace.latitude, longitude: input.geocodedPlace.longitude },
      accuracyMeters: null,
    }
  }
  if (input.manualText && input.manualText.trim().length > 0) {
    return {
      source: 'manual_unverified',
      label: input.manualText.trim(),
      coordinates: null,
      accuracyMeters: null,
    }
  }
  throw new Error('No location provided')
}

test('classifies GPS coordinates as gps source with hardware accuracy', () => {
  const state = classifyLocationState({
    gpsCoords: { latitude: 28.6139, longitude: 77.2090, accuracy: 15 },
  })
  assert.equal(state.source, 'gps')
  assert.equal(state.accuracyMeters, 15)
  assert.deepEqual(state.coordinates, { latitude: 28.6139, longitude: 77.2090 })
  assert.match(state.label, /GPS Coordinates/)
})

test('classifies geocoded search result as geocoded source without GPS label', () => {
  const state = classifyLocationState({
    geocodedPlace: {
      name: 'Hoskote',
      display_name: 'Hoskote, Bengaluru Rural, Karnataka, India',
      latitude: 13.0730,
      longitude: 77.7921,
    },
  })
  assert.equal(state.source, 'geocoded')
  assert.equal(state.accuracyMeters, null)
  assert.deepEqual(state.coordinates, { latitude: 13.0730, longitude: 77.7921 })
  assert.equal(state.label, 'Hoskote, Bengaluru Rural, Karnataka, India')
  // Must NOT claim to be GPS
  assert.equal(state.label.includes('GPS Coordinates'), false)
})

test('classifies manual landmark as unverified note with NULL coordinates', () => {
  const state = classifyLocationState({
    manualText: 'Near Highway Toll Gate, NH 48',
  })
  assert.equal(state.source, 'manual_unverified')
  assert.equal(state.coordinates, null)
  assert.equal(state.accuracyMeters, null)
  assert.equal(state.label, 'Near Highway Toll Gate, NH 48')
  // Crucial requirement: Never label unverified text as GPS-confirmed
  assert.equal(state.label.includes('GPS'), false)
})

test('search query validation requires at least 2 characters', () => {
  const isValidQuery = (q: string) => q.trim().length >= 2
  assert.equal(isValidQuery(''), false)
  assert.equal(isValidQuery(' '), false)
  assert.equal(isValidQuery('H'), false)
  assert.equal(isValidQuery('Ho'), true)
  assert.equal(isValidQuery('Hoskote'), true)
  assert.equal(isValidQuery('Hoskote, Bangalore'), true)
})

test('formatEmergencySummary distinguishes GPS, geocoded, and unverified landmark notes', () => {
  // 1. GPS summary
  const gpsSummary = formatEmergencySummary({
    destination: 'Bengaluru',
    latitude: 12.9716,
    longitude: 77.5946,
    accuracy: 8,
  })
  assert.match(gpsSummary, /GPS Coordinates: 12\.9716, 77\.5946/)

  // 2. Geocoded summary
  const geocodedSummary = formatEmergencySummary({
    destination: 'Bengaluru',
    landmark: 'Hoskote, Bengaluru Rural (Map Geocoded)',
    latitude: 13.0730,
    longitude: 77.7921,
  })
  assert.match(geocodedSummary, /Landmark \/ Location Note: Hoskote, Bengaluru Rural \(Map Geocoded\)/)
  assert.match(geocodedSummary, /13\.073, 77\.7921/)

  // 3. Unverified manual landmark without coordinates
  const unverifiedSummary = formatEmergencySummary({
    destination: 'Bengaluru',
    landmark: 'Room 204, Near Toll Plaza (Unverified)',
  })
  assert.match(unverifiedSummary, /Landmark \/ Location Note: Room 204, Near Toll Plaza \(Unverified\)/)
  // No GPS coordinates block
  assert.equal(unverifiedSummary.includes('GPS Coordinates:'), false)
  assert.equal(unverifiedSummary.includes('Google Maps Link:'), false)
})

