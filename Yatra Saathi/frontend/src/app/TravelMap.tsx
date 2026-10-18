import { useEffect, useRef, useState, useMemo, useCallback } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import {
  Compass, MapPin, ZoomIn, ZoomOut,
  RotateCcw, Sparkles, Navigation,
} from 'lucide-react'
import type { HotelOption, ItineraryActivity } from '../types/travel'
import {
  OPENSTREETMAP_MAX_ZOOM,
  OPENSTREETMAP_TILE_ATTRIBUTION,
  OPENSTREETMAP_TILE_URL,
} from '../utils/mapTiles'
import {
  isValidCoordinate, validateCoordinates, filterValidHotels,
  computeBounds, generateCurvedArc, type CoordinatePoint,
} from '../utils/geo'
import { formatMoney } from '../utils/format'

// Authoritative Indian airport coordinates catalog for direct airport routing
export const KNOWN_AIRPORTS: Record<string, { name: string; iata: string; lat: number; lng: number }> = {
  mumbai: { name: 'Chhatrapati Shivaji Maharaj Intl Airport', iata: 'BOM', lat: 19.0896, lng: 72.8656 },
  lucknow: { name: 'Chaudhary Charan Singh Intl Airport', iata: 'LKO', lat: 26.7606, lng: 80.8893 },
  bengaluru: { name: 'Kempegowda Intl Airport', iata: 'BLR', lat: 13.1986, lng: 77.7066 },
  bangalore: { name: 'Kempegowda Intl Airport', iata: 'BLR', lat: 13.1986, lng: 77.7066 },
  ahmedabad: { name: 'Sardar Vallabhbhai Patel Intl Airport', iata: 'AMD', lat: 23.0772, lng: 72.6347 },
  hyderabad: { name: 'Rajiv Gandhi Intl Airport', iata: 'HYD', lat: 17.2403, lng: 78.4294 },
  chennai: { name: 'Chennai Intl Airport', iata: 'MAA', lat: 12.9941, lng: 80.1709 },
  pune: { name: 'Pune Intl Airport', iata: 'PNQ', lat: 18.5822, lng: 73.9197 },
  kolkata: { name: 'Netaji Subhash Chandra Bose Intl Airport', iata: 'CCU', lat: 22.6547, lng: 88.4467 },
  jaipur: { name: 'Jaipur Intl Airport', iata: 'JAI', lat: 26.8242, lng: 75.8122 },
  delhi: { name: 'Indira Gandhi Intl Airport', iata: 'DEL', lat: 28.5562, lng: 77.1000 },
  'new delhi': { name: 'Indira Gandhi Intl Airport', iata: 'DEL', lat: 28.5562, lng: 77.1000 },
  udaipur: { name: 'Maharana Pratap Airport', iata: 'UDR', lat: 24.6177, lng: 73.8961 },
  varanasi: { name: 'Lal Bahadur Shastri Intl Airport', iata: 'VNS', lat: 25.4524, lng: 82.8593 },
  goa: { name: 'Dabolim / Mopa Intl Airport', iata: 'GOI', lat: 15.3808, lng: 73.8314 },
  panaji: { name: 'Dabolim / Mopa Intl Airport', iata: 'GOI', lat: 15.3808, lng: 73.8314 },
}

export type TravelMapProps = {
  originCity?: string | null
  destinationCity?: string | null
  originCoords?: CoordinatePoint | null
  destinationCoords?: CoordinatePoint | null
  hotels?: HotelOption[]
  selectedHotel?: HotelOption | null
  onSelectHotel?: (hotel: HotelOption) => void
  activities?: ItineraryActivity[]
  selectedActivity?: ItineraryActivity | null
  onSelectActivity?: (activity: ItineraryActivity) => void
  activeDayFilter?: number | null
  onDayFilterChange?: (day: number | null) => void
  totalDays?: number
  title?: string
  className?: string
}

export default function TravelMap({
  originCity,
  destinationCity,
  originCoords,
  destinationCoords,
  hotels = [],
  selectedHotel,
  onSelectHotel,
  activities = [],
  selectedActivity,
  onSelectActivity,
  activeDayFilter = null,
  onDayFilterChange,
  totalDays = 0,
  title,
  className = '',
}: TravelMapProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null)
  const mapInstanceRef = useRef<L.Map | null>(null)
  const tileLayerRef = useRef<L.TileLayer | null>(null)
  const layerGroupRef = useRef<L.LayerGroup | null>(null)
  const markerLookupRef = useRef<Map<string, L.Marker>>(new Map())
  const tileErrorCountRef = useRef(0)

  const [activePopupHotel, setActivePopupHotel] = useState<HotelOption | null>(null)
  const [activePopupActivity, setActivePopupActivity] = useState<ItineraryActivity | null>(null)
  const [mapReady, setMapReady] = useState(false)
  const [tileError, setTileError] = useState(false)

  // Strict coordinate validation
  const validOrigin = useMemo(() => {
    if (!originCoords) return null
    return validateCoordinates(originCoords.lat, originCoords.lng)
  }, [originCoords])

  const validDestination = useMemo(() => {
    if (!destinationCoords) return null
    return validateCoordinates(destinationCoords.lat, destinationCoords.lng)
  }, [destinationCoords])

  const validHotels = useMemo(() => {
    return filterValidHotels(hotels)
  }, [hotels])

  // Look up airports for origin and destination
  const originAirport = useMemo(() => {
    if (!originCity) return null
    return KNOWN_AIRPORTS[originCity.trim().toLowerCase()] || null
  }, [originCity])

  const destAirport = useMemo(() => {
    if (!destinationCity) return null
    return KNOWN_AIRPORTS[destinationCity.trim().toLowerCase()] || null
  }, [destinationCity])

  // Filter activities for map display with valid coordinates
  const validActivities = useMemo(() => {
    return activities.filter((act) =>
      typeof act.latitude === 'number' &&
      typeof act.longitude === 'number' &&
      isValidCoordinate(act.latitude, act.longitude)
    )
  }, [activities])

  // Contextual hotel display: when day filter is active, display only the selected/itinerary hotel
  const displayedHotels = useMemo(() => {
    if (activeDayFilter === null) {
      return validHotels
    }
    if (selectedHotel && isValidCoordinate(selectedHotel.latitude, selectedHotel.longitude)) {
      return [selectedHotel]
    }
    return validHotels.slice(0, 1)
  }, [validHotels, selectedHotel, activeDayFilter])

  // Contextual origin display: show inter-city flight and origin on All Days, Day 1 (Arrival), or final day (Departure)
  const showOriginAndFlightArc = useMemo(() => {
    if (activeDayFilter === null) return true
    return activeDayFilter === 1 || (totalDays > 0 && activeDayFilter === totalDays)
  }, [activeDayFilter, totalDays])

  // All valid points for bounds calculation
  const allPoints = useMemo(() => {
    const pts: CoordinatePoint[] = []
    if (showOriginAndFlightArc) {
      if (validOrigin) pts.push(validOrigin)
      if (originAirport) pts.push({ lat: originAirport.lat, lng: originAirport.lng })
    }
    if (destAirport) pts.push({ lat: destAirport.lat, lng: destAirport.lng })
    if (validDestination) pts.push(validDestination)
    for (const h of displayedHotels) {
      if (isValidCoordinate(h.latitude, h.longitude)) {
        pts.push({ lat: h.latitude as number, lng: h.longitude as number })
      }
    }
    for (const a of validActivities) {
      if (isValidCoordinate(a.latitude, a.longitude)) {
        pts.push({ lat: a.latitude as number, lng: a.longitude as number })
      }
    }
    return pts
  }, [showOriginAndFlightArc, validOrigin, originAirport, destAirport, validDestination, displayedHotels, validActivities])

  const hasGeoData = allPoints.length > 0
  const bounds = useMemo(() => computeBounds(allPoints), [allPoints])

  // Reset view to fit all bounds
  const fitMapToBounds = useCallback(() => {
    const map = mapInstanceRef.current
    if (!map || !bounds || allPoints.length === 0) return
    try {
      if (allPoints.length === 1) {
        map.setView([bounds.centerLat, bounds.centerLng], 12)
      } else {
        const lBounds = L.latLngBounds(
          [bounds.minLat, bounds.minLng],
          [bounds.maxLat, bounds.maxLng]
        )
        map.fitBounds(lBounds, { padding: [50, 50], maxZoom: 14, animate: true })
      }
    } catch {
      // ignore
    }
  }, [bounds, allPoints.length])

  // 1. Initialize Real Leaflet Map
  useEffect(() => {
    if (!mapContainerRef.current) return
    if (mapInstanceRef.current) return // Already initialized

    try {
      const map = L.map(mapContainerRef.current, {
        // Fit authoritative route data in the separate bounds effect after mount.
        // Keeping initialization independent of changing trip data avoids tearing
        // down Leaflet during an active zoom/fly animation.
        center: [20.5937, 78.9629],
        zoom: 4,
        zoomControl: false,
        attributionControl: true,
      })

      // Use the public OSM raster service directly; no provider token is needed.
      const tiles = L.tileLayer(OPENSTREETMAP_TILE_URL, {
        maxZoom: OPENSTREETMAP_MAX_ZOOM,
        subdomains: 'abc',
        attribution: OPENSTREETMAP_TILE_ATTRIBUTION,
      }).addTo(map)
      tileLayerRef.current = tiles
      tileErrorCountRef.current = 0
      setTileError(false)
      tiles.on('tileload', () => {
        tileErrorCountRef.current = 0
        setTileError(false)
      })
      tiles.on('tileerror', () => {
        tileErrorCountRef.current += 1
        if (tileErrorCountRef.current >= 3) setTileError(true)
      })

      const layers = L.layerGroup().addTo(map)
      layerGroupRef.current = layers
      mapInstanceRef.current = map
      setMapReady(true)

      // Invalidate size after container layout settles
      const invalidateTimer = window.setTimeout(() => {
        map.invalidateSize()
      }, 250)

      return () => {
        window.clearTimeout(invalidateTimer)
        map.remove()
        mapInstanceRef.current = null
        tileLayerRef.current = null
        layerGroupRef.current = null
        setMapReady(false)
      }
    } catch (e) {
      console.warn('Leaflet map initialization warning:', e)
    }
  }, [hasGeoData])

  const retryTiles = useCallback(() => {
    tileErrorCountRef.current = 0
    setTileError(false)
    tileLayerRef.current?.redraw()
  }, [])

  // 2. Render Real Markers, Polylines & Flight Arcs
  useEffect(() => {
    const map = mapInstanceRef.current
    const layerGroup = layerGroupRef.current
    if (!map || !layerGroup) return

    layerGroup.clearLayers()
    markerLookupRef.current.clear()

    // -------------------------------------------------------------
    // A. FLIGHT ARC (Geodesic curved path between airport coordinates)
    // -------------------------------------------------------------
    const origFlightPt = originAirport
      ? { lat: originAirport.lat, lng: originAirport.lng }
      : validOrigin
    const destFlightPt = destAirport
      ? { lat: destAirport.lat, lng: destAirport.lng }
      : validDestination

    if (showOriginAndFlightArc && origFlightPt && destFlightPt) {
      const flightArcPoints = generateCurvedArc(origFlightPt, destFlightPt, 40, 0.18)
      const flightPolyline = L.polyline(flightArcPoints, {
        color: '#2563eb',
        weight: 3.5,
        opacity: 0.9,
      }).addTo(layerGroup)

      const flightLabel = `✈ Flight Path: ${originAirport?.iata || originCity || 'Origin'} → ${destAirport?.iata || destinationCity || 'Destination'}`
      flightPolyline.bindTooltip(flightLabel, { sticky: true, className: 'flight-arc-tooltip' })
    }

    // -------------------------------------------------------------
    // B. GROUND CONNECTIONS (Dashed line connecting City -> Airport, and Airport -> Hotel -> POIs)
    // -------------------------------------------------------------
    // 1. Origin City to Origin Airport ground connection
    if (showOriginAndFlightArc && validOrigin && originAirport) {
      L.polyline(
        [[validOrigin.lat, validOrigin.lng], [originAirport.lat, originAirport.lng]],
        { color: '#64748b', weight: 2, dashArray: '4, 6', opacity: 0.7 }
      ).bindTooltip('Approximate ground connection to departure airport (not road navigation)', { sticky: true }).addTo(layerGroup)
    }

    // 2. Destination Airport to Hotel ground connection
    const primaryHotel = selectedHotel || displayedHotels[0]
    if (destAirport && primaryHotel && isValidCoordinate(primaryHotel.latitude, primaryHotel.longitude)) {
      L.polyline(
        [[destAirport.lat, destAirport.lng], [primaryHotel.latitude as number, primaryHotel.longitude as number]],
        { color: '#059669', weight: 2.5, dashArray: '5, 7', opacity: 0.8 }
      ).bindTooltip(`Approximate ground connection: ${destAirport.iata} Airport → ${primaryHotel.name} (not road navigation)`, { sticky: true }).addTo(layerGroup)
    }

    // 3. Hotel to Day Activities ground connection
    if (primaryHotel && isValidCoordinate(primaryHotel.latitude, primaryHotel.longitude) && validActivities.length > 0) {
      const groundPoints: [number, number][] = [
        [primaryHotel.latitude as number, primaryHotel.longitude as number],
      ]
      for (const act of validActivities) {
        if (isValidCoordinate(act.latitude, act.longitude)) {
          groundPoints.push([act.latitude as number, act.longitude as number])
        }
      }
      if (groundPoints.length > 1) {
        L.polyline(groundPoints, {
          color: '#10b981',
          weight: 2,
          dashArray: '5, 8',
          opacity: 0.75,
        }).bindTooltip('Approximate connection between hotel and itinerary stops (not road navigation)', { sticky: true }).addTo(layerGroup)
      }
    }

    // -------------------------------------------------------------
    // C. MARKERS
    // -------------------------------------------------------------

    // 1. 🟢 ORIGIN MARKER
    if (showOriginAndFlightArc && validOrigin) {
      const origIcon = L.divIcon({
        className: 'custom-leaflet-marker',
        html: `
          <div class="marker-container origin-marker">
            <div class="marker-pin origin-pin">
              <span class="marker-emoji">🟢</span>
            </div>
            <div class="marker-label origin-label">${originCity || 'Origin'}</div>
          </div>
        `,
        iconSize: [42, 42],
        iconAnchor: [21, 38],
      })
      const m = L.marker([validOrigin.lat, validOrigin.lng], { icon: origIcon })
        .bindPopup(`<strong>Origin: ${originCity || 'Departure'}</strong><br/>Departure point`)
        .addTo(layerGroup)
      markerLookupRef.current.set('origin', m)
    }

    // 2. 🔵 AIRPORT MARKERS (Departure & Arrival)
    if (showOriginAndFlightArc && originAirport) {
      const aptIcon = L.divIcon({
        className: 'custom-leaflet-marker',
        html: `
          <div class="marker-container airport-marker">
            <div class="marker-pin airport-pin">
              <span class="marker-emoji">🔵</span>
            </div>
            <div class="marker-label airport-label">✈ ${originAirport.iata}</div>
          </div>
        `,
        iconSize: [42, 42],
        iconAnchor: [21, 38],
      })
      const m = L.marker([originAirport.lat, originAirport.lng], { icon: aptIcon })
        .bindPopup(`<strong>${originAirport.name} (${originAirport.iata})</strong><br/>Departure Airport`)
        .addTo(layerGroup)
      markerLookupRef.current.set('origin_airport', m)
    }

    if (destAirport) {
      const aptIcon = L.divIcon({
        className: 'custom-leaflet-marker',
        html: `
          <div class="marker-container airport-marker">
            <div class="marker-pin airport-pin">
              <span class="marker-emoji">🔵</span>
            </div>
            <div class="marker-label airport-label">✈ ${destAirport.iata}</div>
          </div>
        `,
        iconSize: [42, 42],
        iconAnchor: [21, 38],
      })
      const m = L.marker([destAirport.lat, destAirport.lng], { icon: aptIcon })
        .bindPopup(`<strong>${destAirport.name} (${destAirport.iata})</strong><br/>Arrival Airport in ${destinationCity || 'Destination'}`)
        .addTo(layerGroup)
      markerLookupRef.current.set('dest_airport', m)
    }

    // 3. 🏨 HOTEL MARKERS (filtered to active day's stay or full search set)
    for (const h of displayedHotels) {
      if (typeof h.latitude !== 'number' || typeof h.longitude !== 'number') continue
      const isSelected = selectedHotel?.hotelId === h.hotelId
      const hIcon = L.divIcon({
        className: 'custom-leaflet-marker',
        html: `
          <div class="marker-container hotel-marker ${isSelected ? 'selected' : ''}">
            <div class="marker-pin hotel-pin">
              <span class="marker-emoji">🏨</span>
            </div>
            <div class="marker-label hotel-label">${h.name}</div>
          </div>
        `,
        iconSize: [44, 44],
        iconAnchor: [22, 40],
      })

      const m = L.marker([h.latitude, h.longitude], { icon: hIcon })
        .bindPopup(`
          <div class="map-popup-card">
            <h4>🏨 ${h.name}</h4>
            <p>${h.roomName || 'Standard Room'} · ${h.city}</p>
            <strong>${formatMoney(h.price, h.currency)} / stay</strong>
          </div>
        `)
        .addTo(layerGroup)

      m.on('click', () => {
        setActivePopupHotel(h)
        setActivePopupActivity(null)
        if (onSelectHotel) onSelectHotel(h)
      })

      markerLookupRef.current.set(`hotel_${h.hotelId}`, m)
    }

    // 4. 📍 / 🍴 NUMBERED ITINERARY ACTIVITY MARKERS (Synchronized with Itinerary sequence: 1, 2, 3...)
    for (let idx = 0; idx < validActivities.length; idx++) {
      const act = validActivities[idx]
      if (typeof act.latitude !== 'number' || typeof act.longitude !== 'number') continue
      const isSelected = selectedActivity?.id === act.id
      const isRestaurant = act.category === 'food' || act.title.toLowerCase().includes('lunch') || act.title.toLowerCase().includes('dinner')
      const markerNumber = idx + 1

      const actIcon = L.divIcon({
        className: 'custom-leaflet-marker',
        html: `
          <div class="marker-container activity-marker ${isSelected ? 'selected' : ''} ${isRestaurant ? 'restaurant-marker' : ''}">
            <div class="marker-pin ${isRestaurant ? 'restaurant-pin' : 'activity-pin'}">
              <span class="activity-pin-number">${isRestaurant ? '🍴' : markerNumber}</span>
            </div>
            <div class="marker-label activity-label">${act.title}</div>
          </div>
        `,
        iconSize: [40, 40],
        iconAnchor: [20, 36],
      })

      const popupHtml = `
        <div class="map-popup-card">
          <div class="popup-badge">${isRestaurant ? '🍴 Dining' : `📍 Stop ${markerNumber}`}</div>
          <h4>${act.title}</h4>
          ${act.startTime ? `<p class="popup-time">🕒 ${act.startTime}${act.endTime ? ` - ${act.endTime}` : ''}</p>` : ''}
          ${act.location ? `<p class="popup-loc">📍 ${act.location}</p>` : ''}
          ${act.description ? `<p class="popup-desc">${act.description}</p>` : ''}
          ${act.authoritativeCost ? `<strong>Cost: ${act.currency} ${act.authoritativeCost}</strong>` : ''}
        </div>
      `

      const m = L.marker([act.latitude, act.longitude], { icon: actIcon })
        .bindPopup(popupHtml)
        .addTo(layerGroup)

      m.on('click', () => {
        setActivePopupActivity(act)
        setActivePopupHotel(null)
        if (onSelectActivity) onSelectActivity(act)
      })

      markerLookupRef.current.set(`act_${act.id}`, m)
    }
  }, [
    validOrigin,
    originAirport,
    destAirport,
    validDestination,
    displayedHotels,
    showOriginAndFlightArc,
    validActivities,
    selectedHotel,
    selectedActivity,
    originCity,
    destinationCity,
    activeDayFilter,
    onSelectHotel,
    onSelectActivity,
  ])

  // 3. Bidirectional Sync: Focus marker when selectedActivity changes
  useEffect(() => {
    if (!selectedActivity || !mapInstanceRef.current) return
    if (
      typeof selectedActivity.latitude === 'number' &&
      typeof selectedActivity.longitude === 'number' &&
      isValidCoordinate(selectedActivity.latitude, selectedActivity.longitude)
    ) {
      try {
        const map = mapInstanceRef.current
        map.flyTo([selectedActivity.latitude, selectedActivity.longitude], 14, { duration: 1.2 })
        const marker = markerLookupRef.current.get(`act_${selectedActivity.id}`)
        if (marker) {
          setTimeout(() => marker.openPopup(), 600)
        }
      } catch {
        // ignore
      }
    }
  }, [selectedActivity])

  // 4. Re-fit bounds when activeDayFilter changes
  useEffect(() => {
    if (mapReady && mapInstanceRef.current && allPoints.length > 0) {
      fitMapToBounds()
    }
  }, [activeDayFilter, mapReady, fitMapToBounds, allPoints.length])

  // Zoom controls
  const handleZoomIn = () => {
    mapInstanceRef.current?.zoomIn()
  }

  const handleZoomOut = () => {
    mapInstanceRef.current?.zoomOut()
  }

  // EMPTY STATE when no coordinates exist
  if (!hasGeoData) {
    return (
      <section className={`yatra-travel-map-card empty-map ${className}`} aria-label="Travel map">
        <div className="map-card-header">
          <div className="map-card-title">
            <Compass size={17} className="map-icon" />
            <span>Interactive Real Travel Map</span>
          </div>
        </div>
        <div className="map-empty-state">
          <MapPin size={28} className="empty-pin-icon" />
          <h4>Map coordinates are loading for this route.</h4>
          <p>
            Choose a destination or select travel dates with available flight and hotel inventory to explore real geographic routes on the map.
          </p>
        </div>
      </section>
    )
  }

  return (
    <section className={`yatra-travel-map-card ${className}`} aria-label="Interactive real travel map">
      {/* Header bar */}
      <div className="map-card-header">
        <div className="map-card-title">
          <Compass size={17} className="map-icon" />
          <span>{title || 'Interactive Travel Map'}</span>
          {validOrigin && validDestination && (
            <span className="route-badge">
              {originCity || 'Origin'} → {destinationCity || 'Destination'}
            </span>
          )}
          {validActivities.length > 0 && (
            <span className="waypoints-badge">
              <Navigation size={11} /> {validActivities.length} Waypoints
            </span>
          )}
        </div>

        {/* Dynamic Day Filtering Tabs */}
        {totalDays > 0 && onDayFilterChange && (
          <div className="map-day-filter-tabs" role="group" aria-label="Filter map by day">
            <button
              type="button"
              className={`day-filter-btn map-day-pill ${activeDayFilter === null ? 'active' : ''}`}
              onClick={() => onDayFilterChange(null)}
            >
              All Days
            </button>
            {Array.from({ length: totalDays }, (_, i) => i + 1).map((d) => (
              <button
                key={d}
                type="button"
                className={`day-filter-btn map-day-pill ${activeDayFilter === d ? 'active' : ''}`}
                onClick={() => onDayFilterChange(d)}
              >
                Day {d}
              </button>
            ))}
          </div>
        )}

        {/* Map View Controls */}
        <div className="map-controls-group">
          <button
            type="button"
            className="map-ctrl-btn"
            onClick={handleZoomIn}
            title="Zoom In"
            aria-label="Zoom in"
          >
            <ZoomIn size={14} />
          </button>
          <button
            type="button"
            className="map-ctrl-btn"
            onClick={handleZoomOut}
            title="Zoom Out"
            aria-label="Zoom out"
          >
            <ZoomOut size={14} />
          </button>
          <button
            type="button"
            className="map-ctrl-btn"
            onClick={fitMapToBounds}
            title="Reset to Fit Bounds"
            aria-label="Reset map view"
          >
            <RotateCcw size={14} />
          </button>
        </div>
      </div>

      {/* Real Geographic Leaflet Map Canvas */}
      <div className="map-viewport-wrapper">
        <div
          ref={mapContainerRef}
          className={`leaflet-container leaflet-map-canvas-container ${mapReady ? 'ready' : ''}`}
          style={{ width: '100%', height: '480px', minHeight: '440px', background: '#f2f4ee' }}
        />
        {tileError && (
          <div className="map-tile-error" role="alert">
            <span>Map tiles could not be loaded. Check your connection and try again.</span>
            <button type="button" onClick={retryTiles}>Retry map tiles</button>
          </div>
        )}

        {/* Floating Hotel Details Popover if selected on map */}
        {activePopupHotel && (
          <div className="map-hotel-popover" role="dialog" aria-label="Hotel details">
            <button
              type="button"
              className="popover-close-btn"
              onClick={() => setActivePopupHotel(null)}
              aria-label="Close"
            >
              ×
            </button>
            <div className="popover-badge">
              <Sparkles size={11} /> Hotel Highlight
            </div>
            <div className="popover-hotel-header">
              <h4>{activePopupHotel.name}</h4>
              <p className="popover-location">
                <MapPin size={11} /> {activePopupHotel.city}
              </p>
            </div>
            <div className="popover-details">
              <div>
                <strong>{activePopupHotel.roomName || 'Selected Room'}</strong>
                <span>{activePopupHotel.nights} night(s)</span>
              </div>
              <div className="popover-price">
                <em>{formatMoney(activePopupHotel.price, activePopupHotel.currency)}</em>
                <small>/ total stay</small>
              </div>
            </div>
            {onSelectHotel && (
              <button
                type="button"
                className="popover-select-btn"
                onClick={() => {
                  onSelectHotel(activePopupHotel)
                  setActivePopupHotel(null)
                }}
              >
                Select this Hotel
              </button>
            )}
          </div>
        )}

        {/* Selected Activity Popover */}
        {activePopupActivity && (
          <div className="hotel-popover-card activity-popover-card" role="region" aria-label="Activity details">
            <button
              type="button"
              className="popover-close-btn"
              onClick={() => setActivePopupActivity(null)}
              aria-label="Close activity popup"
            >
              ✕
            </button>
            <div className="popover-header">
              <span className="hotel-type-badge">{activePopupActivity.category}</span>
              <h5>{activePopupActivity.title}</h5>
              {activePopupActivity.location && (
                <p className="popover-location">
                  <MapPin size={11} /> {activePopupActivity.location}
                </p>
              )}
            </div>
            {activePopupActivity.description && (
              <p className="popover-desc" style={{ fontSize: '11px', color: '#64748b', margin: '4px 0 0' }}>
                {activePopupActivity.description}
              </p>
            )}
          </div>
        )}
      </div>

      {/* Modern Travel Map Legend */}
      <div className="map-legend-bar" aria-label="Map legend">
        <span className="legend-item">
          <span className="legend-dot origin-dot">🟢</span>
          <span>Origin City</span>
        </span>
        <span className="legend-item">
          <span className="legend-dot airport-dot">🔵</span>
          <span>Airport (IATA)</span>
        </span>
        <span className="legend-item">
          <span className="legend-dot hotel-dot">🏨</span>
          <span>Hotel Stay</span>
        </span>
        <span className="legend-item">
          <span className="legend-dot act-dot">📍</span>
          <span>Numbered Stops (1, 2, 3...)</span>
        </span>
        <span className="legend-item">
          <span className="legend-dot dining-dot">🍴</span>
          <span>Dining / Food</span>
        </span>
        <span className="legend-item">
          <span className="legend-line flight-line" />
          <span>Curved Flight Leg</span>
        </span>
        <span className="legend-item">
          <span className="legend-line ground-line" />
          <span>Local Transit (Dashed)</span>
        </span>
      </div>
    </section>
  )
}
