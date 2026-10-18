import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  OPENSTREETMAP_MAX_ZOOM,
  OPENSTREETMAP_TILE_ATTRIBUTION,
  OPENSTREETMAP_TILE_URL,
} from '../src/utils/mapTiles.ts'

test('default basemap uses public OpenStreetMap raster tiles without provider credentials', () => {
  assert.equal(OPENSTREETMAP_TILE_URL, 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png')
  assert.match(OPENSTREETMAP_TILE_ATTRIBUTION, /openstreetmap\.org\/copyright/)
  assert.match(OPENSTREETMAP_TILE_ATTRIBUTION, /contributors/)
  assert.equal(OPENSTREETMAP_MAX_ZOOM, 19)
  assert.doesNotMatch(OPENSTREETMAP_TILE_URL, /maptiler|carto|api[_-]?key|token/i)
})
