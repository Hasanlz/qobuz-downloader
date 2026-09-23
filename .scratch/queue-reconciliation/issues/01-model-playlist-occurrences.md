# Model Playlist occurrences for Queue reconciliation

Status: ready-for-agent
Type: task
Blocked by: none

## Problem

The Queue currently identifies a wanted item only by source Track id. That
identity cannot distinguish two Spotify Playlist occurrences of the same Track,
and it cannot associate a corrected source Match with the original Spotify
origin. Rematching therefore creates replacement rows, while repeated entries
collapse into one row.

## Acceptance criteria

- A persisted Playlist occurrence has stable Playlist identity, Spotify Track
  identity, occurrence identity, position, and matched source Track identity.
- A complete snapshot can be reconciled without deleting completed Downloads.
- A partial or search-error snapshot cannot remove pending occurrences.
- Playlist insertion, deletion, and reordering do not change occurrence
  identity.
- In-memory and SQLite Queue implementations expose equivalent behavior.
- The Queue contract has deterministic tests for repeated occurrences,
  corrected matches, shared Tracks across Playlists, and completed rows.

## Notes

Do not implement position-only deletion. The current production rows are a
cleanup/recovery concern; this ticket defines the future Queue contract rather
than authorizing a destructive migration.
