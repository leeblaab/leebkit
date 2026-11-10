"""Shared camera-name normalization: project JSONs write either "cam" (UI +
older samples) or "camera" (promo_v12 authoring drift). The engine must accept
both — silently resolving to (0,0) on a typo'd/alternate key was audit bug:
every pan in promo_v12 lost its vector while zoom survived, so it looked fine."""

def cam_name(shot):
    # explicit key priority: a shot may carry BOTH keys after edits; "cam" is the
    # canonical UI-written key, so it wins over a stale "camera" sibling. (A bare
    # `or` chain made validate read one key while render reads another.)
    v = shot.get("cam")
    if v is None:
        v = shot.get("camera")
    return v
