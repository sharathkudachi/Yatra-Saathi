import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  isValidCoordinate,
  validateCoordinates,
  filterValidHotels,
  computeBounds,
  createRouteGeoJson,
} from '../src/utils/geo.ts'
import { findOrigin } from '../src/services/briefFromMessage.ts'
import type { HotelOption } from '../src/types/travel.ts'

test('valid latitude and longitude coordinates are accepted', () => {
  // Common coordinates
  assert.equal(isValidCoordinate(19.075984, 72.877656), true) // Mumbai
  assert.equal(isValidCoordinate(22.572646, 88.363895), true) // Kolkata
  assert.equal(isValidCoordinate(26.912434, 75.787271), true) // Jaipur
  assert.equal(isValidCoordinate(-8.409518, 115.188919), true) // Bali (southern hemisphere)

  // Exact boundary limits
  assert.equal(isValidCoordinate(90, 180), true)
  assert.equal(isValidCoordinate(-90, -180), true)
  assert.equal(isValidCoordinate(0, 0), true)
})

test('invalid latitude outside -90 to +90 is rejected', () => {
  assert.equal(isValidCoordinate(90.0001, 72.87), false)
  assert.equal(isValidCoordinate(-90.0001, 72.87), false)
  assert.equal(isValidCoordinate(120, 72.87), false)
  assert.equal(isValidCoordinate(-150, 72.87), false)
})

test('invalid longitude outside -180 to +180 is rejected', () => {
  assert.equal(isValidCoordinate(19.07, 180.0001), false)
  assert.equal(isValidCoordinate(19.07, -180.0001), false)
  assert.equal(isValidCoordinate(19.07, 240), false)
  assert.equal(isValidCoordinate(19.07, -200), false)
})

test('missing, non-numeric, NaN, and Infinity coordinates are rejected', () => {
  assert.equal(isValidCoordinate(null, 72.87), false)
  assert.equal(isValidCoordinate(19.07, null), false)
  assert.equal(isValidCoordinate(undefined, undefined), false)
  assert.equal(isValidCoordinate(NaN, 72.87), false)
  assert.equal(isValidCoordinate(19.07, NaN), false)
  assert.equal(isValidCoordinate(Infinity, 72.87), false)
  assert.equal(isValidCoordinate(19.07, -Infinity), false)
  assert.equal(isValidCoordinate('19.07', '72.87'), false)
  assert.equal(isValidCoordinate({}, []), false)
})

test('validateCoordinates preserves exact numeric precision without truncation', () => {
  const exactLat = 26.900329
  const exactLng = 75.723832
  const point = validateCoordinates(exactLat, exactLng)
  assert.notEqual(point, null)
  assert.equal(point?.lat, 26.900329)
  assert.equal(point?.lng, 75.723832)

  assert.equal(validateCoordinates(999, 75.72), null)
})

test('filterValidHotels retains hotels with valid coords and drops invalid/missing ones', () => {
  const dummyHotels: Partial<HotelOption>[] = [
    { hotelId: 'h1', name: 'Valid Hotel 1', latitude: 26.91, longitude: 75.78 },
    { hotelId: 'h2', name: 'Valid Hotel 2', latitude: 26.85, longitude: 75.76 },
    { hotelId: 'h3', name: 'Invalid Lat', latitude: 105.0, longitude: 75.76 },
    { hotelId: 'h4', name: 'Missing Coords', latitude: null, longitude: null },
    { hotelId: 'h5', name: 'Undefined Coords' },
  ]

  const filtered = filterValidHotels(dummyHotels as HotelOption[])
  assert.equal(filtered.length, 2)
  assert.equal(filtered[0].hotelId, 'h1')
  assert.equal(filtered[1].hotelId, 'h2')
})

test('computeBounds accurately computes bounding box and center', () => {
  const points = [
    { lat: 19.076, lng: 72.877 }, // Mumbai
    { lat: 22.572, lng: 88.363 }, // Kolkata
  ]
  const bounds = computeBounds(points)
  assert.notEqual(bounds, null)
  assert.equal(bounds?.minLat, 19.076)
  assert.equal(bounds?.maxLat, 22.572)
  assert.equal(bounds?.minLng, 72.877)
  assert.equal(bounds?.maxLng, 88.363)
  assert.equal(bounds?.centerLat, (19.076 + 22.572) / 2)
  assert.equal(bounds?.centerLng, (72.877 + 88.363) / 2)
})

test('empty geographic dataset returns null bounds for empty state', () => {
  assert.equal(computeBounds([]), null)
  assert.equal(computeBounds([null, undefined]), null)
})

test('createRouteGeoJson constructs valid GeoJSON LineString', () => {
  const origin = { lat: 19.076, lng: 72.877 }
  const destination = { lat: 22.572, lng: 88.363 }
  const geojson = createRouteGeoJson(origin, destination)

  assert.equal(geojson.type, 'Feature')
  assert.equal(geojson.geometry.type, 'LineString')
  assert.deepEqual(geojson.geometry.coordinates, [
    [72.877, 19.076], // [longitude, latitude] GeoJSON standard
    [88.363, 22.572],
  ])
  assert.equal(geojson.properties.type, 'travel-connection')
})

test('findOrigin extracts origin city correctly from natural language and suggestion prompts', () => {
  const cities = ['Mumbai', 'Kolkata', 'Lucknow', 'Ahmedabad', 'Bengaluru', 'Jaipur', 'Pune', 'New Delhi']

  assert.equal(findOrigin('Plan a trip from Mumbai to Kolkata for 5 adults', cities), 'Mumbai')
  assert.equal(findOrigin('from Ahmedabad to Bengaluru for 2 adults', cities), 'Ahmedabad')
  assert.equal(findOrigin('Mumbai → Lucknow · 2 adults', cities), 'Mumbai')
  assert.equal(findOrigin('Chennai → Pune', cities), null) // Chennai not in subset list
  assert.equal(findOrigin('trip starting in Bengaluru headed to Jaipur', cities), 'Bengaluru')
  assert.equal(findOrigin('Just looking for hotels in Jaipur', cities), null)
})
