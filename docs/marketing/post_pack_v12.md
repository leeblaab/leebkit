# LEEBKIT v1.2 — Reddit + Facebook post pack (Nov 9, 2026)

Anti-deletion rules baked into every draft below:
- Zero launch-hype words ("game-changer", "revolutionary", emoji-spam, exclamation stacks).
- Feedback-first framing everywhere; the repo link appears ONCE, mid-body, never in the title.
- No "upvote/share please", no link shorteners, no cross-posted identical text on the same day.
- Story + technical specifics (mods check for copy-paste ads; real numbers like "8.3s render" read human).

## Account warm-up BEFORE any post (this is why posts get removed more than the text)
Mods' first check is your profile history. A day-old account with one link post = auto-removed
in most subs regardless of quality. Minimum: 5–10 comments on OTHER people's posts in that sub
over 2–3 days, ~50+ karma, then post. Reply to every comment on your post within the first hours.

---

## POST 1 — r/SideProject (primary; self-promo explicitly welcome)
Flair: "Showcase" or "Feedback Requested" if offered.

**Title:** I got tired of paying $15/month to animate text over images, so I built an offline promo-video maker — v1.2 just shipped, roast it please

**Body:**
> A while back I needed a short promo clip for something small I was selling. Every tool I found wanted the same thing: sign up, pick a plan, $10–20/month, watermark on the "free" tier. Some literally charge per export. For a 15-second video of animated text over photos?!
>
> The other thing that bugged me: everything is cloud-based now. You upload your stuff, their servers render it, and if they change pricing or die tomorrow — poof. I wanted something that works on my machine, airplane mode included.
>
> So I built LEEBKIT — Python + Pillow, runs a local server in your browser, turns images + typed captions into finished 9:16 / 1:1 / 16:9 promo videos with kinetic type, panels, transitions, voiceover and music bed. No GPU, no accounts, no API keys.
>
> v1.2 shipped today: three social formats, a one-click Windows installer, burned-proof path hardening, and — measured on my laptop, not guessed — the full 12s promo in the README (voiceover + music, 360 frames) renders in 8.3 seconds wall-clock. The README's before→after strip shows exactly what goes in and what comes out.
>
> Repo: https://github.com/leeblaab/leebkit (AGPL)
>
> It's honest about being early: single-user local tool, no mobile, rough edges exist. That's why I'm posting — try to break it. Weird captions, huge images, long text. Tell me what feels wrong or made you close the tab. If it's useless to you, say why; that's just as useful as praise.

Attach: docs/leebkit_promo.gif (or scratch/post_thumbs/promo_strip.jpg) + docs/beforeafter/strip.jpg as post images — image posts with context get removed far less than link posts, and the GIF demos the product better than any paragraph.

## POST 2 — r/opensource (conditional: real OSS announcement style, no marketing voice)
Flair: "Project" / "Announcement".

**Title:** LEEBKIT v1.2 — AGPL promo-video engine in pure Python/Pillow; everything renders locally, measured 8s for a 12s video on a laptop CPU

**Body (shorter, license+architecture first):**
> Sharing a project of mine: an offline promo/shorts video generator licensed AGPL. Engine is pure Pillow + numpy + ffmpeg — no cloud, no telemetry, no API keys; the whole app is a local Flask server you open in your browser.
>
> Architecture notes for anyone curious: one human-readable JSON per video ("projects are files"), preset-driven layout math (9:16/1:1/16:9), multiprocessing frame rendering with per-frame verify gates, piper TTS bundled as optional local voiceover. Today's v1.2 pass was mostly hardening: path confinement inside media/, upload magic-byte sniffing + size cap, loud aborts instead of silent black frames, and a scripted pre-tag smoke suite that gates every release.
>
> https://github.com/leeblaab/leebkit
>
> Happy to answer design questions — why JSON-over-database, why no frontend framework, how the layout measurement works. Feature requests welcome; the roadmap is public and community comments have already redirected it twice.

## POST 3 — r/IMadeThis (small, promo-friendly, low moderation)
Reuse POST 1 body trimmed by ~half; title: "I made an offline promo-video maker because I got sick of $15/month subscriptions — v1.2, feedback wanted"

## POST 4 — r/sideprojects (plural — different sub, allows advertising projects)
Same as POST 3 with a small reword so it isn't detectably identical text. Flair required there.

## BACKUP TIER (post only if 1–2 go well; space them days apart)
- r/alphaandbetausers — tester-recruitment framing ("looking for 10 people to break v1.2")
- r/roastmystartup — brutal-feedback framing, works great with humble copy
- r/microsaas, r/buildinpublic — progress-journey framing ("week 3: what the crowd asked for changed my roadmap")
- r/InternetIsBeautiful ONLY if framed as a web tool demo — risky here (local server ≠ web), skip unless you do a hosted demo page later
- Show HN on Hacker News (not Reddit but same effort): "Show HN: Offline promo-video maker in pure Python" — HN loves the no-cloud angle; needs a live demo link or it flops

## AVOID (why mods keep deleting)
- r/webdev, r/Python, r/selfhosted main feed — 9:1 rule / megathread-only; post only inside "Showoff Saturday" / monthly showcase / weekly self-hosted megathread
- r/productivity, r/smallbusiness main feed, r/artificial — self-promo banned or link-restricted outright
- Any sub where you post the identical text within 48h — crossposts must be reworded + spaced

## Facebook — Arabic (Egyptian, very friendly) [unchanged heart, v1.2 facts]

**عملت حاجة صغيرة بحبها، وعايز رأيكم فيها ❤️**

اسمها **LEEBKIT** — برنامج بيعمل فيديوهات قصيرة (ريلز/تيك توك ويوتيوب وكمان مربع) من صورك وكلامك انت، وبيشتغل **على اللابتوب بتاعك خالص**، من غير إنترنت أصلاً.

ليه عملته؟ بصراحة زهقت. كل أداة أونلاين عايزة 15 دولار في الشهر عشان تكتب نص متحرك على صورة! وأغلبها بيطلب ترفع صورك على سيرفراتهم، ولو الخدمة قفلت بكرة… يلا مع السلامة شغلك.

**البرنامج:**
🆓 مجاني ومفتوح المصدر (AGPL) — للأبد، مش "تجربة مجانية 7 أيام"
💻 بيشتغل على اللابتوب العادي من غير كارت شاشة قوي — وفيديو 12 ثانية بيتعمل في ثواني قليلة
🎬 نصوص متحركة، انتقالات، شاشات CTA، تعليق صوتي وموسيقى — كله محلي
📱 تنصيب بـ دبل كليك على ويندوز — مفيش سطر أوامر ولا تعقيد

النسخة الجديدة 1.2 النهارده: ثلاث مقاسات (تيك توك/انستجرام/يوتيوب)، تنصيب بضغطة، وتحسينات ثبات كتير.

لسه جديد وفيه حاجات هتتحسن، وده بالظبط سبب بوستي: **عايزكم تجربه وتكسروه**. جربه وقوللي رأيك بصراحة — حتى لو "مش شغال حاجة" ده مفيد جداً 🙏

التحميل: https://github.com/leeblaab/leebkit

ولو تعرف حد بيبيع أونلاين وزهقان من الاشتراكات الشهرية، ابعتله البوست ده ❤️

## Facebook — English (same warmth, v1.2 facts)
Same structure as Arabic version translated; attach promo GIF + before/after strip.

---

## Attachments to use
- docs/leebkit_promo.gif — 8s looped preview (auto-plays on Reddit)
- docs/beforeafter/strip.jpg — inputs vs rendered frames
- scratch/post_thumbs/promo_strip.jpg — 4 key promo frames side-by-side (2454x1064)
- Full voiced 12s: https://github.com/leeblaab/leebkit/releases/download/v1.2/promo_v12.mp4 (link in text, never as the post itself)

## Posting schedule
- Day 0 (Tue/Wed): POST 1 r/SideProject ~6–9 AM ET + FB Arabic same evening Cairo time
- Day +2: POST 2 r/opensource (reworded, different day-of-week rhythm)
- Day +3: FB English
- Day +4+: POST 3/4 backups only if engagement is alive; reply to every comment fast
