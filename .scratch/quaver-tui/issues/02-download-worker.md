# 02 — Download worker

Status: ready-for-human

`DownloadWorker` thread in `tui/src/quaver/worker.py`: drains `SqliteQueue`
through `Engine`, byte progress via `ProgressSource`, global pause and
per-track holds (`tui/holds.py`, sidecar table), retry of failed and stuck
rows, 5-consecutive-failure abort, exit-aware stop.

## Comments

- Cross-restart resume covered: pending tracks left by a killed session are
  picked up on the next launch; held tracks are skipped.
