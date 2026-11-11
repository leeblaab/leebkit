"""v1.4 C5 — share-format caps (single source of truth).

"GIF is a share teaser, not the master" (plan risk #3). Cap locked by Yasser
2026-11-11: 640px wide, max 6s, ~12fps. WebP gets the same duration cap but a
roomier width (animated webp carries full color + alpha at similar file size,
so it is the "high-quality share" tier). CLI (--gif/--webp), app (/api/share)
and tests all import these numbers — they can never drift apart.
"""

GIF_MAX_W = 640      # px; wider sources are LANCZOS-downscaled before encode
GIF_MAX_S = 6.0      # seconds; longer renders are truncated to the first 6s
GIF_FPS = 12         # sampled frame rate (source frames decimated, never re-timed)

WEBP_MAX_W = 960     # webp teaser keeps more width (full-color, no palette)
WEBP_MAX_S = 8.0     # slightly roomier than GIF; still a teaser, not the master
