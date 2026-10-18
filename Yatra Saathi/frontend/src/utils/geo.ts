/**
 * Geographic validation, bounding box, and GeoJSON utilities.
 * Validates latitude (-90 to +90) and longitude (-180 to +180) coordinates,
 * preserving authoritative precision and rejecting invalid, NaN, Infinity, or missing values.
 */

export type CoordinatePoint = {
  lat: number
  lng: number
}

export type GeoBounds = {
  minLat: number
  maxLat: number
  minLng: number
  maxLng: number
  centerLat: number
  centerLng: number
}

/**
 * Validates that latitude and longitude are finite numbers within physical ranges.
 * Rejects null, undefined, NaN, Infinity, strings, and out-of-bounds coordinates.
 */
export function isValidCoordinate(lat: unknown, lng: unknown): boolean {
  if (typeof lat !== 'number' || typeof lng !== 'number') return false
  if (Number.isNaN(lat) || Number.isNaN(lng)) return false
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return false
  if (lat < -90 || lat > 90) return false
  if (lng < -180 || lng > 180) return false
  return true
}

/**
 * Validates coordinates and returns typed { lat, lng } preserving authoritative precision,
 * or null if coordinates are missing or invalid.
 */
export function validateCoordinates(lat: unknown, lng: unknown): CoordinatePoint | null {
  if (!isValidCoordinate(lat, lng)) return null
  return { lat: lat as number, lng: lng as number }
}

/**
 * Filters a list of hotel or stay options, returning only those with valid geographic coordinates.
 */
export function filterValidHotels<T extends { latitude?: unknown; longitude?: unknown }>(items: T[]): T[] {
  return items.filter((item) => isValidCoordinate(item.latitude, item.longitude))
}

/**
 * Computes bounding box and center coordinate for a list of valid geographic points.
 * Returns null if no valid points are supplied.
 */
export function computeBounds(points: Array<CoordinatePoint | null | undefined>): GeoBounds | null {
  const valid = points.filter((p): p is CoordinatePoint => Boolean(p && isValidCoordinate(p.lat, p.lng)))
  if (valid.length === 0) return null

  let minLat = valid[0].lat
  let maxLat = valid[0].lat
  let minLng = valid[0].lng
  let maxLng = valid[0].lng

  for (let i = 1; i < valid.length; i++) {
    const pt = valid[i]
    if (pt.lat < minLat) minLat = pt.lat
    if (pt.lat > maxLat) maxLat = pt.lat
    if (pt.lng < minLng) minLng = pt.lng
    if (pt.lng > maxLng) maxLng = pt.lng
  }

  return {
    minLat,
    maxLat,
    minLng,
    maxLng,
    centerLat: (minLat + maxLat) / 2,
    centerLng: (minLng + maxLng) / 2,
  }
}

/**
 * Creates a GeoJSON LineString feature connecting two points.
 * Note: Mapbox/MapTiler/GeoJSON convention uses [longitude, latitude].
 */
export function createRouteGeoJson(origin: CoordinatePoint, destination: CoordinatePoint) {
  return {
    type: 'Feature' as const,
    properties: {
      type: 'travel-connection',
      label: 'Approximate travel connection',
    },
    geometry: {
      type: 'LineString' as const,
      coordinates: [
        [origin.lng, origin.lat],
        [destination.lng, destination.lat],
      ],
    },
  }
}

/**
 * Generates an array of [lat, lng] points forming a smooth curved flight arc between two coordinates.
 */
export function generateCurvedArc(
  origin: CoordinatePoint,
  destination: CoordinatePoint,
  numPoints = 50,
  curvature = 0.2
): Array<[number, number]> {
  const points: Array<[number, number]> = []
  const midLat = (origin.lat + destination.lat) / 2
  const midLng = (origin.lng + destination.lng) / 2

  const dLat = destination.lat - origin.lat
  const dLng = destination.lng - origin.lng
  const dist = Math.sqrt(dLat * dLat + dLng * dLng)
  if (dist === 0) return [[origin.lat, origin.lng]]

  // Perpendicular vector for offset towards north/apex
  const pLat = -dLng
  const pLng = dLat
  const norm = Math.sqrt(pLat * pLat + pLng * pLng)
  const offset = dist * curvature

  const ctrlLat = midLat + (pLat / norm) * offset
  const ctrlLng = midLng + (pLng / norm) * offset

  for (let i = 0; i <= numPoints; i++) {
    const t = i / numPoints
    const lat = (1 - t) * (1 - t) * origin.lat + 2 * (1 - t) * t * ctrlLat + t * t * destination.lat
    const lng = (1 - t) * (1 - t) * origin.lng + 2 * (1 - t) * t * ctrlLng + t * t * destination.lng
    points.push([lat, lng])
  }
  return points
}
