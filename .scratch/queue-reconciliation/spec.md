# Queue playlist reconciliation

Status: ready-for-agent

## Problem Statement

A Spotify Playlist is represented in the Queue only by matched source Track
ids and display metadata. A rematch can therefore add a corrected source Track
at the same playlist position without removing the stale row. The Queue also
uses the source Track id as its global identity, so repeated occurrences of
one Track in a Playlist collapse into one row and leave later positions
unrepresented. Position-only cleanup is unsafe because Playlist edits and
insertions move positions, and a partial or failed Match must not be treated
as a complete snapshot.

## Solution

Keep the current Queue mutation behavior unchanged until a complete Playlist
snapshot can be reconciled through an explicit Queue operation. Add a
read-only inventory command that reports position coverage, duplicate rows, and
match-generation counts without creating or modifying the database. For a
future reconciliation operation, persist enough Playlist identity to
distinguish source Tracks, Spotify origins, and repeated occurrences. The
operation must preserve completed Downloads, replace or retire stale pending
rows only for a trustworthy snapshot, and make partial/search-error snapshots
non-destructive.

## User Stories

1. As a downloader user, I want a read-only inventory of current Spotify
   positions and Queue coverage, so that I can tell missing Tracks from stale
   replacement rows without downloading or changing the Queue.
2. As a downloader user, I want the inventory to report row counts separately
   from distinct positions, so that duplicate rows cannot make a broken Queue
   look complete.
3. As a downloader user, I want the inventory to identify the match generation
   represented by each row, so that old and rematched data are not silently
   mixed during diagnosis.
4. As a downloader user, I want every repeated Spotify occurrence to remain
   visible as a separate wanted occurrence, so that a Track appearing twice in
   a Playlist is not silently downloaded only once.
5. As a downloader user, I want a corrected Match to replace its stale pending
   occurrence, so that old and corrected source ids do not both consume Queue
   capacity.
6. As a downloader user, I want completed Downloads preserved during
   reconciliation, so that rebuilding current metadata never requeues or
   deletes a successfully downloaded file.
7. As a downloader user, I want a failed or partial Match to leave existing
   pending rows untouched, so that a transient Source outage cannot erase
   wanted Tracks.
8. As a downloader user, I want playlist insertions and reorderings to update
   occurrence identity rather than relying on a numeric position, so that
   current playlist order can be represented safely.
9. As a downloader user, I want the same source Track used by two Playlists to
   retain its download status, so that one completed Download is not treated as
   two unrelated files.
10. As a downloader user, I want a report that distinguishes a clean catalog
    miss, a below-threshold candidate, and a retryable search error, so that a
    later retry decision is based on evidence.

## Implementation Decisions

- The current diagnostic is a standalone read-only script. It opens SQLite
  through a read-only URI and never constructs the application Queue, because
  Queue construction can create or migrate the database.
- The diagnostic compares positions, not total rows, and exposes every row
  occupying a position. This is intentionally not an exact Spotify-id join:
  current Queue rows do not persist Spotify ids.
- The current Queue schema is not changed by this diagnostic. Source Track id
  remains the global identity until a playlist-occurrence model is designed.
- A future authoritative snapshot must include the Spotify Playlist id,
  Spotify Track id, occurrence identity, matched source id, position, and
  Match state. A source id alone cannot identify a Playlist occurrence.
- A reconciliation operation must run only after a complete, trustworthy
  snapshot. Unmatched entries caused by search errors are not evidence that a
  desired row should be removed.
- Completed rows are never deleted or reset to pending. Current Tracks are
  requeued according to the existing failed-row policy, while stale pending
  occurrences are removed only within the correctly identified Playlist scope.
- Position numbers are ordering metadata, not identity. Playlist insertions,
  deletions, and reorderings must be handled by stable origin and occurrence
  identity.
- A source Track shared by multiple Playlists needs an explicit policy for
  whether one completed Download satisfies every occurrence or whether each
  occurrence is independently represented.
- Pending ordering must not rely on SQLite rowid once reconciliation exists;
  the Queue needs a deliberate ordering field or membership relationship.

## Testing Decisions

- Test the inventory seam with a captured Spotify metadata fixture and a
  temporary SQLite database. The test must be deterministic and must not use
  credentials or a network request.
- Test the read-only guarantee by opening a missing database path and
  asserting that the path is not created.
- Test the Queue contract at the highest common seam for in-memory and SQLite
  implementations when reconciliation is implemented. The same scenarios must
  pass for both implementations.
- Cover completed-row preservation, stale pending replacement, failed-row
  requeue, repeated occurrences, playlist insertion/reordering, shared Tracks
  across Playlists, and a partial/search-error snapshot.
- Use external behavior assertions: inspect status, membership, and ordering
  through Queue operations rather than asserting private SQL implementation
  details.
- Retain the live replay as a manual diagnostic loop; it should report current
  Spotify positions, Queue positions, and match errors without downloading.

## Out of Scope

- Automatically deleting or rewriting the existing production Queue as part
  of the diagnostic.
- Treating a numeric playlist position as a stable identity.
- Claiming a Track is globally absent when a credentialed Source was not
  searched or when a search failed.
- Adding Tidal credentials or changing Source matching thresholds as part of
  Queue reconciliation.
- Replacing completed files or changing audio download behavior.

## Further Notes

The current live replay matched 1,087 of 1,118 Spotify positions. Thirty gaps
were reported as catalog misses, and one repeated occurrence was skipped by
the existing source-id deduplication. The corrected candidate probe classified
21 of the 30 as having a strong Deezer candidate rejected for lossy-only
audio, nine as below the current lossless matcher threshold, and none as a
search error. The production database was unexpectedly recreated empty by a
separate process during diagnosis; no production rows were deleted or restored
by the diagnostic work.
