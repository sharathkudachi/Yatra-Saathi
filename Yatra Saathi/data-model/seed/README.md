# Demo seed data

[`demo_seed.json`](demo_seed.json) holds the demo fixtures used by the demo path. It is the single
source for these values: `backend/scripts/seed_demo.py` reads it and inserts the rows into the
**working copy** (never the original), through the live schema and its triggers.

* User `usr_demo0001` ("[DEMO] Traveller", `demo.traveller@example.invalid`)
* Trip `trp_demo0001` ("[DEMO] Ahmedabad → Jaipur"), 2026-10-06 → 2026-10-08, 2 adults
* Budget `bud_demo0001`, total ₹20,000 (category caps split 36 / 18 / 18 / 13.5 / 4.5 %)

```bash
cd backend
python -m scripts.seed_demo     # seed an existing working copy (idempotent)
python -m scripts.demo_reset    # or: fresh working copy + migrations 0001–0004 + seed
```

`tests/e2e/test_demo_story.py` runs the full demo story on top of this seed.
