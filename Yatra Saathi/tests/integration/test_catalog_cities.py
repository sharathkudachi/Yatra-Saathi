"""The agent resolves city names against the full `/catalog/cities` list, so an
unfiltered listing must return every city, not a truncated page."""
from __future__ import annotations

import sqlite3
import unittest

from src.db.repositories import catalog as catalog_repo
from tests import support


class CatalogCitiesTestCase(unittest.TestCase):
    def setUp(self):
        support.assert_original_untouched()
        self.wc = support.WorkingCopy()
        self.conn = self.wc.raw()
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()
        self.wc.cleanup()
        support.assert_original_untouched()

    def test_unfiltered_listing_returns_every_city(self):
        total = self.conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0]
        rows = catalog_repo.list_cities(self.conn)
        self.assertEqual(len(rows), total)
        self.assertIn("Abu Dhabi", {r["name"] for r in rows})
