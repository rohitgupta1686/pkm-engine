-- Idempotency hash for concept synthesis: stores SHA-256 of the sorted claim-id
-- set contributing to a concept, so we only re-synthesize when new claims arrive.
ALTER TABLE concepts ADD COLUMN synthesis_claim_hash TEXT;
ALTER TABLE concepts ADD COLUMN synthesis_explanation TEXT;
ALTER TABLE concepts ADD COLUMN synthesis_related TEXT;   -- JSON array of concept names
ALTER TABLE concepts ADD COLUMN synthesis_evidence TEXT;  -- JSON array of claim statements
