-- The ReAct "reason" step: why this round searched what it searched.
ALTER TABLE research.rounds ADD COLUMN IF NOT EXISTS thought text NOT NULL DEFAULT '';
