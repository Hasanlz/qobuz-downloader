# 03 — Player

Status: ready-for-human

`tui/src/quaver/player.py` (ffplay backend via SIGSTOP/SIGCONT, mpv when
available) and `tui/src/quaver/spectrum.py` (real RMS levels from an ffmpeg
astats side-decode). Play downloaded files or stream without downloading; seek
bar; Enter on found Track plays, `d` downloads.

## Comments

- Verified against real audio: ffplay loads/pauses; spectrum bars track a sine
  source at expected levels.
