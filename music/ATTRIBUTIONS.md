# CC0 music beds — provenance ledger

All beds in this folder are **CC0 1.0 Universal** (public domain, no attribution
legally required; credited here anyway). Verified on 2026-11-11 by reading the
item metadata directly from Internet Archive (`https://archive.org/metadata/<id>`
→ `licenseurl = http://creativecommons.org/publicdomain/zero/1.0/`).

| File | Track | Artist | Source item (Archive.org) | Raw master |
|---|---|---|---|---|
| bed_cave_drone.mp3 | Ambient Cave Drone (Mar 6 2015) | uploader arinlares@gmail.com (no author name given) | `AmbientCaveDroneMar62015` | mean -11.8 dBFS, peak 1.0 |
| bed_one_cool_minute.mp3 | One Cool Minute | Loyalty Freak Music | `MINIMALAMBIENTBOUNCE` | mean -19.1 dBFS, peak 0.91 |
| bed_old_key.mp3 | Old Key | Loyalty Freak Music | `MINIMALAMBIENTBOUNCE` | mean -28.3 dBFS, peak 0.48 |

Download URLs used (VBR MP3 originals):
- https://archive.org/download/AmbientCaveDroneMar62015/Ambient%20Cave%20Drone%20Mar%206%202015.mp3
- https://archive.org/download/MINIMALAMBIENTBOUNCE/Loyalty%20Freak%20Music%20-%20MINIMAL%20AMBIENT%20BOUNCE%20-%2002%20One%20Cool%20Minute.mp3
- https://archive.org/download/MINIMALAMBIENTBOUNCE/Loyalty%20Freak%20Music%20-%20MINIMAL%20AMBIENT%20BOUNCE%20-%2003%20Old%20Key.mp3

License evidence (verbatim from Archive metadata JSON):
- `"licenseurl": "http://creativecommons.org/publicdomain/zero/1.0/"` on both items
  (`AmbientCaveDroneMar62015`, `MINIMALAMBIENTBOUNCE`).

Engine handling: external beds are loudness-matched to the procedural band
(mean trim to -19.5 dBFS) then peak-normalized to 0.84 in build_audio — same
shape as the procedural beds — so VO always sits on top regardless of how the
original was mastered.

Note: FMA (freemusicarchive.org) hosts CC0 artists (e.g. HoliznaCC0, per-track
"CC0 1.0 Universal License" verified) but downloads require a login account —
not used as a source. Pixabay music sits behind Cloudflare and its Content
License forbids standalone redistribution — not used.
