-- PostgreSQL-only migration. Execute with psql; this file is intentionally not
-- registered in the SQLite migration runner.
\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE public.users ADD COLUMN IF NOT EXISTS home_city_id VARCHAR(32) REFERENCES public.cities(city_id);
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS budget_band TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS travel_style TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS traveller_type TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS segment TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS date_of_signup TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS loyalty_tier TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS updated_at TEXT;

COMMIT;
