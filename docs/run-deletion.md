# Recoverable run deletion

Use **Delete run** in any run's header, including during active work. Confirming stops
the owned worker and cleans up its labeled preview/execution resources before hiding the
run. If cleanup fails, the run stays visible with an error, so deletion can be retried.

Runs are soft-deleted into **Trash · deleted runs**. History, source, reports, operation
records and LangGraph checkpoints are retained on disk. This does not reclaim disk space.
Deleted runs are excluded from ordinary reads, source downloads, reports and workflow
actions. Event streams notify other open tabs of deletion. Late workflow events cannot
modify a deleted run. Retried deletion is idempotent; replaying a deleted run's old create
request cannot resurrect it.

Restoring a paused review retains that review state. Restoring interrupted work does not
restart it automatically; it returns interrupted. Restoring a run whose preview was
stopped returns a stopped preview state. Temporary preview database contents are not
restorable. No permanent-purge feature is provided in this version.

The jobs table receives additive `deleted_at` and `restore_status` columns without
rewriting or resetting the database. The delete/restore endpoints retain existing local
session, host/origin, and CSRF protections. The operations lock serializes deletion with
other dashboard actions. Shared templates, dependencies and Ollama models are unchanged.

The six existing development runs were moved to Trash at the user's request. Browser QA
confirmed the empty main list, restored a paused run, and deleted it again through the
confirmation dialog. The final state was zero visible runs and six recoverable runs.
The full regression run passed 74 tests; an added deleted-request retry case and the
deletion-specific tests subsequently passed (5 tests). React type checking and production
build passed. Tests cover active-worker termination, retained history, restore, cleanup
failure, protected APIs and hiding deleted source.
