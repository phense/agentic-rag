-- Add an administrative event type; retain every historical row and ACL.
-- The migration runner applies this together with its marker in one transaction.
ALTER TABLE public.dashboard_changes DROP CONSTRAINT dashboard_changes_kind_check;
ALTER TABLE public.dashboard_changes ADD CONSTRAINT dashboard_changes_kind_check
    CHECK (kind IN ('bootstrap','user','machine','rotate','revoke','reranker'));
