-- Phase 7 (GUARD-03): incrementally-maintained counter rows for the dashboard.
--
-- Cloud doc §9 line 231: "Replace SELECT COUNT(*) FROM big_table dashboards with
-- incrementally-maintained counter rows updated on write." This table holds the
-- counts the nightly dashboard renders so regeneration never scans a full table
-- (keeps Turso cheap).
--
-- Rows are lazy-created by bump_counter(); no seed insert needed.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS dashboard_counters (
    key         TEXT PRIMARY KEY,          -- e.g. sources_total, claims_total, concepts_total, insights_accepted
    value       INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL               -- ISO-8601 UTC of last bump
);