-- PostgreSQL-only, targeted catalogue repair for registration.
-- This inserts the canonical country/language dependencies and city selected
-- by the registration handler's ORDER BY city_id LIMIT 1 query when the
-- production catalogue is empty. It never updates existing reference rows.
\set ON_ERROR_STOP on

BEGIN;

INSERT INTO public.countries (country_id, name, iso2, iso3)
VALUES ('cnt_b8092331', 'Sri Lanka', 'LK', 'LKA')
ON CONFLICT (country_id) DO NOTHING;

INSERT INTO public.languages (
    language_id, bcp47, english_name, native_name, script, rtl, tts_supported, updated_at
) VALUES (
    'lng_5c34a3a2',
    'si',
    'Sinhala',
    U&'\0DC3\0DD2\0D82\0DC4\0DBD',
    'Sinh',
    0,
    0,
    '2026-08-18T10:00:00+05:30'
)
ON CONFLICT (language_id) DO NOTHING;

INSERT INTO public.cities (
    city_id, name, state, country_id, country_code, lat, lng, timezone,
    region, population, season_profile, peak_months, primary_language,
    description, status, updated_at
) VALUES (
    'cty_009c9fd2',
    'Kandy',
    NULL,
    'cnt_b8092331',
    'LK',
    7.290572,
    80.633728,
    'Asia/Colombo',
    'South Asia',
    125000,
    'winter',
    '12,1,2,3',
    'si',
    'Kandy is the kind of place that rewards a second day. The centre is compact enough to walk, the lakefront stays busy well into the evening, and the best of it is off the main road.',
    'active',
    '2026-08-18T10:00:00+05:30'
)
ON CONFLICT (city_id) DO NOTHING;

COMMIT;
