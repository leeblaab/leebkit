# LEEBKIT v1.3 — Reddit + Facebook post pack (Nov 10, 2026)

Same anti-deletion rules as the v1.2 pack (still binding):
- Zero launch-hype words; feedback-first framing; repo link ONCE, mid-body, never in title.
- No "upvote please", no shorteners, no identical crosspost within 48h — reword + space days.
- Account warm-up first: 5–10 comments in-sub over 2–3 days before posting (this is why
  posts get removed more than the text itself). Reply to every comment fast.
- Numbers below are MEASURED on my machine, never guessed: 12s promo = ~17s wall-clock
  (render_cli.py --jobs 8, warm run), ffprobe gate h264 1080x1920@30 nb_frames=360 + aac.

## What v1.3 actually is (for honest copy)
A reliability release: the render engine now has a golden-frame regression harness —
1260 frames of every caption kind x 2 styles x 3 formats, hash-checked on every push,
plus an ffprobe frame-count gate. Caption measurement was refactored so the pre-render
checker and the renderer share ONE source of truth (no more false "caption too long"
warnings that disagreed with what actually rendered). Panel caption timing bug fixed
(early-start shift was cancelled by the transition freeze). New: style previews — each
preset renders a live 3-frame animated preview in the app before you commit to a look.

## POST 1 — r/SideProject (primary)
Flair: "Showcase" / "Feedback Requested".

**Title:** Offline promo-video maker, v1.3: this release I mostly made it impossible to break — golden-frame tests on every push, roast it please

**Body:**
> Back in September I posted about LEEBKIT here — an offline promo-video maker (Python + Pillow + ffmpeg) because I got tired of paying $15/month to animate text over photos. It renders 9:16 / 1:1 / 16:9 videos with kinetic type, transitions, voiceover and music — on your machine, airplane mode included.
>
> This week's v1.3 is a reliability release and I'm proud of it: the engine now has a golden-frame harness — 1260 frames covering every caption style, both themes and all three formats, hash-compared on every push, plus an ffprobe frame-count gate after encode. Every refactor since then was proven pixel-identical before merge. Fixed a timing bug where panel captions' early start got cancelled by transition freezing, and unified the pre-render checker with the renderer so "caption too long" warnings finally match what actually renders.
>
> New toy: style previews — every preset renders a live animated preview in the app before you commit to a look.
>
> Still measured, not guessed: full 12s promo (360 frames + VO + music) in ~17 seconds wall-clock on a CPU-only laptop.
>
> Repo: https://github.com/leeblaab/leebkit (AGPL)
>
> Try to break it — weird captions, huge images, long text. Tell me what feels wrong.

Attach: docs/leebkit_promo.gif + before/after strip image.

## POST 2 — r/opensource
Flair: "Project" / "Announcement".

**Title:** LEEBKIT v1.3 — AGPL promo-video engine in pure Python/Pillow; now with a 1260-frame golden regression harness gating every push

**Body (architecture-first):**
> v1.3 of my offline promo-video generator (pure Pillow + numpy + ffmpeg, local server, no cloud/telemetry/API keys). This pass was engineering, not features:
> - Golden-frame harness: all frames of a flagship promo + one synthetic corpus carrying every caption kind, 2 presets x 3 aspect formats = 1260 per-frame SHA-256s checked on every push (sampled on Linux CI, full corpus weekly on Windows — the OS we actually ship). One real ffmpeg encode + ffprobe nb_frames assertion as end-to-end leg. Per-OS baselines because font rasterization legitimately differs across platforms.
> - Checker/renderer single source of truth: pre-render overflow warnings now consume the same measure() the renderer uses (they used to mirror its formulas and drift — found one checker that was 0.45s stricter than the render).
> - Metrics cache keyed per shot, not per frame; verbatim-move refactor proven pixel-identical by the harness before any behavior change.
> - Style previews endpoint: preset rendered through the real layout path at half-res, animated webp (not GIF — 256 colors bands gradients).
>
> https://github.com/leeblaab/leebkit
>
> Happy to answer harness design questions — why hashes over image-diff, why per-OS baselines, what the frame-count gate catches that a duration gate hides.

## POST 3 — r/IMadeThis / r/sideprojects (plural)
Trim POST 1 by half, reword title: "Made an offline promo-video maker because $15/month subscriptions annoyed me — v1.3 is the 'make it unbreakable' release". Space days apart, different sub, never identical text.

## BACKUP TIER (only if engagement alive; space days apart)
- r/alphaandbetausers — "looking for 10 people to break v1.3"
- r/microsaas, r/buildinpublic — journey framing ("the release where I wrote no features")
- Show HN: "Show HN: Offline promo-video maker in pure Python (with golden-frame tests)" — HN loves the no-cloud + testing angle; must answer every comment ~6h.

## AVOID (unchanged)
r/webdev, r/Python, r/selfhosted main feeds (9:1 rule / megathread only), r/productivity,
r/smallbusiness, r/artificial. No identical crossposts within 48h.

## Facebook — Arabic (Egyptian, friendly) [v1.3 facts]

**عملت حاجة صغيرة بحبها، وعايز رأيكم فيها ❤️**

اسمها **LEEBKIT** — برنامج بيعمل فيديوهات قصيرة (ريلز/تيك توك ويوتيوب وكمان مربع) من صورك وكلامك انت، وبيشتغل **على اللابتوب بتاعك خالص**، من غير إنترنت أصلاً.

ليه عملته؟ زهقت. كل أداة أونلاين عايزة 15 دولار في الشهر عشان تكتب نص متحرك على صورة! وأغلبها بيطلب ترفع صورك على سيرفراتهم.

**البرنامج:**
🆓 مجاني ومفتوح المصدر (AGPL) — للأبد، مش "تجربة مجانية"
💻 بيشتغل على اللابتوب العادي من غير كارت شاشة — فيديو 12 ثانية بيتعمل في حوالي ١٧ ثانية
🎬 نصوص متحركة، انتقالات، شاشات CTA، تعليق صوتي وموسيقى — كله محلي
📱 تنصيب بـ دبل كليك على ويندوز

النسخة الجديدة 1.3 دي مختلفة: بدل ميزات جديدة، عملت **اختبارات ضمان** إن الفيديو نفسه يطلع بالظبط بعضه في كل تحديث — ١٢٦٠ فريم بيتقارنوا آلياً مع كل تعديل، عشان أي تحديث جاي ما يخرّبش حاجة شغالة. وكمان ضفت **معاينة للستايلات**: قبل ما تختار شكل الفيديو، بتشوفه بيتحرك قدامك الأول.

لسه جديد — **عايزكم تجربه وتكسروه**. قوللي رأيك بصراحة 🙏

التحميل: https://github.com/leeblaab/leebkit

ولو تعرف حد بيبيع أونلاين وزهقان من الاشتراكات الشهرية، ابعتله البوست ده ❤️

## Facebook — English
Same structure as Arabic, translated; attach promo GIF + before/after strip.

## Attachments
- docs/leebkit_promo.gif — refreshed v1.3 looped preview (auto-plays on Reddit)
- docs/beforeafter/strip.jpg — inputs vs rendered frames
- Full voiced 12s: https://github.com/leeblaab/leebkit/releases/download/v1.3/promo_v13.mp4 (link in text, never as the post itself; resolves once tag v1.3 + release asset are pushed)

## Posting schedule
- Day 0 (Tue/Wed): POST 1 r/SideProject ~6–9 AM ET + FB Arabic same evening Cairo time
- Day +2: POST 2 r/opensource
- Day +3: FB English
- Day +4+: backups only if engagement alive; reply to every comment fast
