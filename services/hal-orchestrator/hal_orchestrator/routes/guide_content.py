# ruff: noqa: E501 -- guide bodies stay readable as authored markup.
"""Content for /guides — the SEO content pages (see routes/guides.py).

Each guide is one dict; `body` is trusted first-party HTML rendered inside the
article shell. Editorial rules for anything added here:

- YMYL care: sleep numbers are presented as approximate ranges with an "every
  baby is different" hedge, never as prescriptions. Every page ends with the
  same not-medical-advice disclaimer the landing FAQ uses, and cites at least
  two reputable sources (AAP/HealthyChildren, AASM, NHS, Sleep Foundation).
- `code` is the landing `?c=` attribution code the page's CTA carries (see
  MARKETING.md registry; `g-` prefix = guides). Keep codes short.
- `updated` feeds <lastmod> in the sitemap and the visible byline — bump it
  when you materially edit a page.
"""

from __future__ import annotations

DISCLAIMER = (
    "HAL is a household coordination and logging assistant, not a medical "
    "service. Sleep needs vary from baby to baby; the ranges here are common "
    "patterns, not prescriptions. Wake-window and nap-count ranges in "
    "particular are sleep-practitioner conventions rather than formal medical "
    "guidance — medical bodies publish only total-sleep recommendations. For "
    "health concerns, contact your pediatrician or another qualified "
    "professional."
)

_SRC_AAP_HOURS = (
    "AAP / HealthyChildren.org — Healthy Sleep Habits: How Many Hours Does Your Child Need?",
    "https://www.healthychildren.org/English/healthy-living/sleep/Pages/healthy-sleep-habits-how-many-hours-does-your-child-need.aspx",
)
_SRC_AASM = (
    "American Academy of Sleep Medicine — Recommended Amount of Sleep for Pediatric Populations (consensus statement)",
    "https://aasm.org/resources/pdf/pediatricsleepdurationconsensus.pdf",
)
_SRC_SAFE_SLEEP = (
    "AAP / HealthyChildren.org — A Parent's Guide to Safe Sleep",
    "https://www.healthychildren.org/English/ages-stages/baby/sleep/Pages/a-parents-guide-to-safe-sleep.aspx",
)
_SRC_NHS_NEWBORN = (
    "NHS — Helping your baby to sleep",
    "https://www.nhs.uk/conditions/baby/caring-for-a-newborn/helping-your-baby-to-sleep/",
)
_SRC_SF_REGRESSION = (
    "Sleep Foundation — The 4-Month Sleep Regression",
    "https://www.sleepfoundation.org/baby-sleep/4-month-sleep-regression",
)
_SRC_ENOUGH_MILK = (
    "AAP / HealthyChildren.org — How to Tell if Baby is Getting Enough Milk",
    "https://www.healthychildren.org/English/ages-stages/baby/breastfeeding/Pages/How-to-Tell-if-Baby-is-Getting-Enough-Milk.aspx",
)
_SRC_WELL_CHILD = (
    "AAP / HealthyChildren.org — Well-Child Care: A Check-Up for Success",
    "https://www.healthychildren.org/English/family-life/health-management/Pages/Well-Child-Care-A-Check-Up-for-Success.aspx",
)
_SRC_CLEVELAND_WW = (
    "Cleveland Clinic — Wake Windows by Age (pediatrician-reviewed)",
    "https://health.clevelandclinic.org/wake-windows-by-age",
)
_SRC_CANAPARI = (
    "Dr. Craig Canapari, Yale Pediatric Sleep Center — Do Wake Windows Help Kids Nap Better?",
    "https://drcraigcanapari.com/do-wake-windows-help-kids-nap-better/",
)
_SRC_AAP_FEEDING = (
    "AAP / HealthyChildren.org — How Often and How Much Should Your Baby Eat?",
    "https://www.healthychildren.org/English/ages-stages/baby/feeding-nutrition/Pages/how-often-and-how-much-should-your-baby-eat.aspx",
)
_SRC_SF_NEWBORN_WW = (
    "Sleep Foundation — Newborn Wake Windows: What's Normal?",
    "https://www.sleepfoundation.org/baby-sleep/newborn-wake-window",
)
_SRC_CC_REGRESSION = (
    "Cleveland Clinic — Infant Sleep Regression: What Parents Need To Know",
    "https://health.clevelandclinic.org/the-4-month-sleep-regression-what-parents-need-to-know",
)
_SRC_AAP_SEP_ANXIETY = (
    "AAP / HealthyChildren.org — Separation Anxiety & Sleeping Trouble in Young Children",
    "https://www.healthychildren.org/English/healthy-living/sleep/Pages/separation-anxiety-and-sleeping.aspx",
)
_SRC_SF_12MO = (
    "Sleep Foundation — The 12-Month Sleep Regression",
    "https://www.sleepfoundation.org/baby-sleep/12-month-sleep-regression",
)
_SRC_HB_2TO1 = (
    "Huckleberry — How to manage the transition from two naps to one nap",
    "https://huckleberrycare.com/blog/2-to-1-nap-transition",
)
_SRC_TCB_2TO1 = (
    "Taking Cara Babies — Transitioning from 2 Naps to 1",
    "https://www.takingcarababies.com/blogs/naps/transitioning-from-2-naps-to-1",
)
_SRC_HB_3TO2 = (
    "Huckleberry — How to manage the transition from three naps to two naps",
    "https://huckleberrycare.com/blog/3-to-2-nap-transition",
)
_SRC_IPR_BABYAPPS = (
    "Pybus, Matheson & Lachmansingh — Extraction-by-design: Auditing infrastructures of datafication in baby-tracking apps (Internet Policy Review, 2026)",
    "https://policyreview.info/articles/analysis/datafication-baby-tracking-apps",
)
_SRC_FTC_PREMOM = (
    "FTC — Ovulation Tracking App Premom Barred from Sharing Health Data for Advertising (2023)",
    "https://www.ftc.gov/news-events/news/press-releases/2023/05/ovulation-tracking-app-premom-will-be-barred-sharing-health-data-advertising-under-proposed-ftc",
)
_SRC_MOZILLA_PNI = (
    "Mozilla *Privacy Not Included — 18 of 25 Period and Pregnancy Tracking Apps Labeled with Privacy Warnings",
    "https://www.mozillafoundation.org/en/privacynotincluded/articles/in-post-roe-v-wade-era-mozilla-labels-18-of-25-popular-period-and-pregnancy-tracking-tech-with-privacy-not-included-warning/",
)
_SRC_BMJ_APPS = (
    "Grundy et al. — Data sharing practices of medicines related apps (BMJ 2019; open-access PMC mirror)",
    "https://pmc.ncbi.nlm.nih.gov/articles/PMC6425456/",
)

GUIDES: list[dict] = [
    # ------------------------------------------------------------------ #
    # Pillar page — the cluster hub; every age/transition page links here
    # and is linked from here (bidirectional, per topic-cluster practice).
    # ------------------------------------------------------------------ #
    {
        "slug": "baby-sleep-schedules-by-age",
        "code": "g-pillar",
        "category": "By age",
        "page_title": "Baby Sleep Schedules by Age: 0–24 Months [Full Chart]",
        "title": "Baby sleep schedules by age: 0–24 months",
        "description": "The full picture of baby sleep from newborn to age two: a master chart of naps, wake windows, and sleep totals by age, what changes at each stage, and every transition — with links to the detailed guide for each age.",
        "teaser": "The master chart and what changes at every age — start here.",
        "updated": "2026-08-27",
        "related": ["wake-windows-by-age", "2-to-1-nap-transition", "share-baby-schedule-with-grandparents"],
        "body": """
<p>Baby sleep follows a surprisingly consistent arc: newborns sleep in fragments around the clock; by 4 months a real schedule emerges; naps consolidate from 4-ish to 3, to 2, to 1 by around 18 months. This page is the whole arc in one chart — with a deeper guide for every age when you need the details.</p>
<h2>The master chart</h2>
<p>Nap counts and wake windows are sleep-practitioner convention (medical bodies publish only the totals — more on that below). Every baby drifts from these ranges sometimes; that's normal.</p>
<table>
<thead><tr><th>Age</th><th>Naps</th><th>Wake windows</th><th>Day sleep</th><th>Night sleep</th><th>Total / 24 h</th></tr></thead>
<tbody>
<tr><td>0–3 months</td><td>4–6+ (irregular)</td><td>30–90 min</td><td>varies widely</td><td>fragmented</td><td>~14–17 h</td></tr>
<tr><td>3–4 months</td><td>3–4</td><td>75 min–2 h</td><td>~3.5–4.5 h</td><td>~10–12 h</td><td>12–16 h</td></tr>
<tr><td>5–6 months</td><td>3</td><td>2–3 h</td><td>~2.5–4 h</td><td>~11–12 h</td><td>12–16 h</td></tr>
<tr><td>7–9 months</td><td>2–3 → 2</td><td>2.5–3.5 h</td><td>~2–3.5 h</td><td>~11–12 h</td><td>12–16 h</td></tr>
<tr><td>10–12 months</td><td>2</td><td>3–4 h</td><td>~2–3 h</td><td>~11–12 h</td><td>12–16 h</td></tr>
<tr><td>13–18 months</td><td>2 → 1</td><td>3–5 h</td><td>~2–3 h</td><td>~11 h</td><td>11–14 h</td></tr>
<tr><td>18–24 months</td><td>1</td><td>4–6 h</td><td>~1.5–2.5 h</td><td>~11 h</td><td>11–14 h</td></tr>
</tbody>
</table>
<h2>How to read this chart honestly</h2>
<p>Two different kinds of numbers live in that table. The <strong>totals</strong> are formal medical guidance: the American Academy of Sleep Medicine (endorsed by the AAP) recommends 12–16 hours per 24 for infants 4–12 months and 11–14 hours for ages 1–2, with no formal recommendation under 4 months. The <strong>nap counts and wake windows</strong> are convention from sleep practitioners — useful, broadly agreed, but not research-derived. Treat them as starting ranges and let your baby's own recent pattern be the tiebreaker. (More on this in the <a href="/guides/wake-windows-by-age">wake windows guide</a>, or skip the math with the <a href="/guides/wake-window-calculator">calculator</a>.)</p>
<h2>0–3 months: rhythm, not schedule</h2>
<p>Newborns run on feed-sleep cycles of roughly 2–3 hours with wake windows so short (30–60 minutes at first) that a feed and a diaper change nearly fill them. Day/night confusion is standard-issue until the body clock consolidates around 6–12 weeks. Don't chase a schedule yet — build a repeatable cycle, keep days bright and nights boring, and follow safe-sleep rules for every sleep.</p>
<p><a href="/guides/newborn-sleep-schedule">Full guide: newborn sleep, 0–3 months →</a></p>
<h2>3–4 months: the schedule arrives (so does the regression)</h2>
<p>Sleep reorganizes into adult-style cycles around 3–5 months — a permanent upgrade that temporarily wrecks nights (the famous 4-month regression). On the other side of it, most babies land on 3–4 naps with wake windows of 75 minutes to 2 hours, and the first genuinely predictable days appear.</p>
<p><a href="/guides/4-month-old-nap-schedule">Full guide: 4-month-old nap schedule →</a></p>
<h2>5–6 months: the three-nap sweet spot</h2>
<p>Two proper naps plus a late-afternoon catnap, wake windows around 2–3 hours, and solids joining the day. For many families this is the first stretch where tomorrow reliably looks like today.</p>
<p><a href="/guides/6-month-old-nap-schedule">Full guide: 6-month-old nap schedule →</a></p>
<h2>7–9 months: the catnap goes</h2>
<p>Somewhere around 7–9 months the third nap stops earning its keep. The two-nap day that replaces it — morning nap, afternoon nap, windows of 2.5–3.5 hours — is the most stable architecture of the first year. Expect a wobble around 8–10 months from separation anxiety and crawling practice.</p>
<p><a href="/guides/9-month-old-nap-schedule">Full guide: 9-month-old nap schedule →</a></p>
<h2>10–12 months: two naps, and the fake-out</h2>
<p>Still two naps for almost everyone — but around the first birthday many babies stage a convincing nap strike that looks like readiness for one nap and usually isn't. Hold the two-nap line through it.</p>
<p><a href="/guides/12-month-old-nap-schedule">Full guide: 12-month-old nap schedule →</a></p>
<h2>13–18 months: the 2-to-1 transition</h2>
<p>The real transition to one midday nap comes between 13 and 18 months, most commonly around 15. Done gradually — shifting the morning nap later in steps, bridging with early bedtimes — it takes two to four weeks.</p>
<p><a href="/guides/2-to-1-nap-transition">Full guide: the 2-to-1 nap transition →</a></p>
<h2>18–24 months: the one-nap era</h2>
<p>One midday nap of 1.5–2.5 hours, wake windows of 4–6 hours, bedtime around 7–8. This architecture holds until the nap fades out entirely, typically sometime after age 3.</p>
<h2>The three transitions at a glance</h2>
<table>
<thead><tr><th>Transition</th><th>Typical age</th><th>Tell-tale sign it's real</th></tr></thead>
<tbody>
<tr><td>4 → 3 naps</td><td>~4–5 months</td><td>the fourth catnap keeps failing and bedtime holds anyway</td></tr>
<tr><td>3 → 2 naps</td><td>~7–9 months</td><td>the catnap pushes bedtime late or gets refused for weeks</td></tr>
<tr><td>2 → 1 nap</td><td>~13–18 months</td><td>a nap is consistently refused for 2+ weeks and skipped days go fine</td></tr>
</tbody>
</table>
<h2>When do babies drop to one nap?</h2>
<p>Most toddlers move to a single midday nap between 13 and 18 months, commonly around 15. Before ~13 months, nap refusal is far more likely a temporary strike than true readiness — the <a href="/guides/2-to-1-nap-transition">2-to-1 guide</a> covers how to tell the difference.</p>
<h2>Should you wake a sleeping baby?</h2>
<p>Sometimes. Wake a newborn if a feed is due and weight gain is still being established (your pediatrician will tell you). Wake an older baby to cap a nap that's threatening bedtime or running past the family's schedule. Otherwise, let sleep run — babies mostly take what they need.</p>
<h2>Should bedtime move earlier when a nap gets skipped?</h2>
<p>Yes — the early bedtime is the universal repair tool. Pull it forward by roughly 30–60 minutes (rarely before 6:00 PM) whenever the day's sleep came up short. It's much easier to protect a night than to rescue an overtired one.</p>
<h2>The part the chart can't do: keeping everyone on it</h2>
<p>A schedule only protects your baby if every caregiver runs the same one — and knows where today actually stands. That's the job HAL does in the family group chat: anyone texts "woke 2:40," everyone sees the same day, and the next-nap estimate comes from your baby's own recent rhythm rather than this chart. The chart is the map; the log is the GPS.</p>
""",
        "sources": [_SRC_AASM, _SRC_AAP_HOURS, _SRC_CLEVELAND_WW, _SRC_SAFE_SLEEP],
    },
    # ------------------------------------------------------------------ #
    # Wake-windows hub
    # ------------------------------------------------------------------ #
    {
        "slug": "wake-windows-by-age",
        "code": "g-ww",
        "category": "By age",
        "page_title": "Wake Windows by Age: Chart for 0–24 Months",
        "title": "Wake windows by age: 0–24 months",
        "description": "A practical wake-windows chart from newborn to 24 months — how long baby can comfortably stay awake between sleeps, how nap counts change, and how to use the ranges without living by the clock.",
        "teaser": "The full chart, 0–24 months, and how to actually use it.",
        "updated": "2026-08-27",
        "related": ["baby-sleep-schedules-by-age", "newborn-sleep-schedule", "4-month-old-nap-schedule"],
        "body": """
<p>A <strong>wake window</strong> is the stretch of time a baby can comfortably stay awake between one sleep and the next. Keep it too short and the next nap is a fight; stretch it too long and you get an overtired baby who paradoxically sleeps <em>worse</em>. Most of practical baby scheduling comes down to landing inside these windows.</p>
<h2>First, an honest note about where these numbers come from</h2>
<p>No medical body publishes a wake-windows chart. The AAP and the American Academy of Sleep Medicine publish <em>total</em> sleep recommendations; wake windows are a convention developed by sleep consultants, and their charts disagree with each other at the edges. Pediatric sleep physicians point out the specific numbers aren't derived from research. They're still a genuinely useful planning tool — just treat them as a starting range to adjust from, not a prescription, and let your baby's own pattern be the tiebreaker.</p>
<h2>Wake windows chart</h2>
<p>The ranges below reflect the rough consensus across the major charts (including a pediatrician-reviewed one — see sources). Premature babies, growth spurts, and plain individual temperament all shift them.</p>
<table>
<thead><tr><th>Age</th><th>Typical wake window</th><th>Naps per day</th></tr></thead>
<tbody>
<tr><td>0–4 weeks</td><td>about 30–60 min</td><td>4–6+ (irregular)</td></tr>
<tr><td>1–2 months</td><td>about 60–90 min</td><td>4–5</td></tr>
<tr><td>2–3 months</td><td>about 60–90 min</td><td>4–5</td></tr>
<tr><td>3–4 months</td><td>about 75 min–2 h</td><td>3–4</td></tr>
<tr><td>5–6 months</td><td>about 2–3 h</td><td>3</td></tr>
<tr><td>7–9 months</td><td>about 2.5–3.5 h</td><td>2–3 → 2</td></tr>
<tr><td>10–12 months</td><td>about 3–4 h</td><td>2</td></tr>
<tr><td>13–18 months</td><td>about 3–5 h</td><td>2 → 1</td></tr>
<tr><td>18–24 months</td><td>about 4–6 h</td><td>1</td></tr>
</tbody>
</table>
<p>For totals, which <em>are</em> formal medical guidance: the American Academy of Sleep Medicine (endorsed by the AAP) recommends 12–16 hours per 24 hours (including naps) for babies 4–12 months, and 11–14 hours for ages 1–2. There is no formal recommendation for newborns under 4 months — their sleep is too variable to standardize.</p>
<p>Prefer to skip the mental math? The free <a href="/guides/wake-window-calculator">wake window calculator</a> turns age + last wake-up into a next-nap time range.</p>
<h2>How to use wake windows (without living by the clock)</h2>
<ul>
<li><strong>Count from wake-up, not from when you started trying.</strong> The window opens when baby actually wakes.</li>
<li><strong>Use the early end after short naps.</strong> A 30-minute catnap doesn't buy a full window.</li>
<li><strong>Watch the baby, then check the clock.</strong> Rubbing eyes, zoning out, fussing at toys — start wind-down. The chart tells you when to <em>expect</em> those cues.</li>
<li><strong>The last window of the day is usually the longest</strong>, and the first is often the shortest (a consultant convention, but an uncontested one).</li>
</ul>
<h2>Overtired vs. undertired</h2>
<p>Both look like "won't sleep," which is why guessing fails — and short naps happen in <em>both</em> cases, so nap length alone won't tell you which. The distinguishing signal is mood and distress: an <strong>overtired</strong> baby is wired, cries hard at the crib, and wakes from short naps still cranky. An <strong>undertired</strong> baby resists calmly — plays or chats in the crib for a long time, settles late without drama, and wakes from a short nap cheerful. A common rule of thumb among sleep consultants: if you're seeing the first, shorten windows by 10–15 minutes and hold that for a few days; the second, stretch by the same amount.</p>
<h2>Do wake windows include feeding time?</h2>
<p>Yes. The wake window runs from the moment your baby wakes to the moment they're asleep again, and everything inside it counts — feeds, diaper changes, play, the wind-down. For newborns a feed can fill most of the window, which is why they're often ready to sleep right after eating.</p>
<h2>When do wake windows start counting?</h2>
<p>From wake-up, not from when you get baby out of the crib and not from the end of the feed. If she woke at 2:40 and you got her up at 3:00, the window opened at 2:40 — miss that and every estimate for the rest of the day runs 20 minutes late.</p>
<h2>Should the last wake window of the day be the longest?</h2>
<p>Usually, yes. Most babies handle their longest stretch of awake time right before bedtime, and the first window of the morning is typically the shortest. If bedtime is a nightly fight, the pre-bed window is the first one worth adjusting — often it's too short rather than too long.</p>
<h2>The part no chart solves: everyone has to know today's timing</h2>
<p>Wake windows only work if whoever is holding the baby knows when the last sleep ended. That's the actual hard part in a two-parent-plus-caregivers household. HAL solves it in the family group chat: anyone texts "woke 2:40" and everyone — including HAL's next-nap estimate from your baby's own recent rhythm — is looking at the same day.</p>
""",
        "sources": [_SRC_AASM, _SRC_AAP_HOURS, _SRC_CLEVELAND_WW, _SRC_CANAPARI],
    },
    # ------------------------------------------------------------------ #
    # Age-band schedules
    # ------------------------------------------------------------------ #
    {
        "slug": "newborn-sleep-schedule",
        "code": "g-nb",
        "category": "By age",
        "page_title": "Newborn Sleep Schedule (0–3 Months): What's Realistic",
        "title": "Newborn sleep schedule (0–3 months): what's realistic",
        "description": "Newborns don't follow schedules — they follow feed-sleep cycles. What a realistic 0–3 month rhythm looks like, day/night confusion, safe sleep basics, and when patterns start to emerge.",
        "teaser": "There is no schedule yet — here's the rhythm to expect instead.",
        "updated": "2026-08-26",
        "related": ["baby-sleep-schedules-by-age", "wake-windows-by-age", "4-month-old-nap-schedule"],
        "body": """
<p>First, permission to relax: <strong>newborns do not have schedules, and nothing is wrong with your baby or your parenting.</strong> For roughly the first three months, sleep is driven by feeding and a not-yet-developed body clock. What you can build now is a <em>rhythm</em> — and a record — while the schedule arrives on its own later.</p>
<h2>What newborn sleep actually looks like</h2>
<ul>
<li><strong>Total sleep:</strong> commonly 14–17 hours per 24 — but in fragments of 30 minutes to 3–4 hours, around the clock.</li>
<li><strong>Wake windows:</strong> very short — about 30–60 minutes in the first weeks, stretching toward 60–90 minutes by 2–3 months, and that includes the feed. Many newborns are ready to sleep again almost as soon as they've fed and been changed. (Newborns typically feed about every 2–3 hours.)</li>
<li><strong>Day/night confusion is normal.</strong> The circadian rhythm doesn't start consolidating until around 6–12 weeks. Help it along: bright light and normal noise for daytime feeds, dark and boring for night ones.</li>
</ul>
<h2>A realistic cycle (not a schedule)</h2>
<table>
<thead><tr><th>Repeating cycle, roughly every 2–3 hours</th></tr></thead>
<tbody>
<tr><td>Wake + feed (20–40 min)</td></tr>
<tr><td>Diaper, burp, brief awake time — a little light and chat</td></tr>
<tr><td>Wind-down and back to sleep (asleep by ~45–60 min after waking)</td></tr>
</tbody>
</table>
<p>Expect one longer stretch (hopefully!) somewhere at night, and know that "good nights" and rough nights alternate without explanation at this age.</p>
<h2>Safe sleep, every sleep</h2>
<p>The AAP's guidance applies to naps as much as nights: baby on their <strong>back</strong>, on a <strong>firm, flat surface</strong>, in their <strong>own sleep space</strong> (crib or bassinet) with <strong>nothing else in it</strong> — no blankets, pillows, bumpers, or toys. Room-sharing (not bed-sharing) is recommended for at least the first 6 months.</p>
<h2>Why log anything this early?</h2>
<p>Two reasons. Your pediatrician will ask concrete questions — feeds per day, wet diapers, sleep — and 3 AM memory is not a data source. And around 8–12 weeks, patterns quietly emerge; a log is how you notice the nap that's stabilizing. HAL does this by text in your family group chat: "ate 3:10" and "down 4:05" is the whole workflow, and either parent (or grandma) can log or ask what's next.</p>
""",
        "sources": [_SRC_SAFE_SLEEP, _SRC_NHS_NEWBORN, _SRC_AAP_FEEDING, _SRC_SF_NEWBORN_WW],
    },
    {
        "slug": "4-month-old-nap-schedule",
        "code": "g-4mo",
        "category": "By age",
        "page_title": "4-Month-Old Nap Schedule: Wake Windows, Naps & the Regression",
        "title": "4-month-old nap schedule: wake windows, naps, and the regression",
        "description": "A realistic 4-month-old schedule: 3–4 naps, wake windows of about 75 minutes to 2 hours, a sample day, and what the famous 4-month sleep regression actually is.",
        "teaser": "3–4 naps, the first real wake windows — and the famous regression.",
        "updated": "2026-08-27",
        "related": ["baby-sleep-schedules-by-age", "wake-windows-by-age", "newborn-sleep-schedule"],
        "body": """
<p>Four months is when a schedule first becomes worth talking about. Sleep is reorganizing into adult-style cycles, the body clock is coming online, and most babies land on <strong>3–4 naps</strong> with wake windows of roughly <strong>75 minutes to 2 hours</strong>.</p>
<h2>The shape of the day</h2>
<ul>
<li><strong>Wake windows:</strong> about 75 min–2 h, shortest before the first nap, longest before bedtime.</li>
<li><strong>Naps:</strong> 3–4, often one or two decent naps plus catnaps. Total day sleep commonly 3.5–4.5 hours.</li>
<li><strong>Night:</strong> 10–12 hours with feeds; the AASM's 12–16 h per 24 h recommendation starts at this age.</li>
</ul>
<h2>Sample 4-month day</h2>
<p>A shape, not a script — anchor to your baby's actual wake-up and the day flexes from there.</p>
<table>
<thead><tr><th>Time</th><th>What</th></tr></thead>
<tbody>
<tr><td>7:00 am</td><td>Wake + feed</td></tr>
<tr><td>8:30–10:00</td><td>Nap 1</td></tr>
<tr><td>11:45–1:00</td><td>Nap 2</td></tr>
<tr><td>2:45–3:30</td><td>Nap 3 (catnap)</td></tr>
<tr><td>5:15</td><td>Begin wind-down</td></tr>
<tr><td>6:45–7:15 pm</td><td>Bedtime</td></tr>
</tbody>
</table>
<h2>The 4-month sleep regression, briefly</h2>
<p>It isn't really a regression — the underlying change is a permanent upgrade, even though the rough patch it causes is temporary. Around 3–5 months, baby's sleep matures into cycles with more light-sleep stages, which means more chances to fully wake between cycles. A baby who needs help falling asleep at bedtime will often need the same help at every overnight cycle break. It typically shows up as sudden frequent night waking and short naps lasting anywhere from a few days to a few weeks (some babies take up to six). What helps: protecting age-appropriate wake windows, practicing some falling-asleep-in-the-crib at bedtime, and riding it out consistently.</p>
<h2>Questions parents ask at this age</h2>
<p><strong>How much should a 4-month-old sleep?</strong> The formal guidance (AASM, endorsed by the AAP) is 12–16 hours per 24 including naps — commonly ~10–12 hours at night plus 3.5–4.5 hours across naps.</p>
<p><strong>Can a 4-month-old sleep through the night?</strong> Some manage one long stretch of 6–8 hours; many still genuinely need a night feed or two. Both are normal at this age — ask your pediatrician about your baby specifically before dropping night feeds.</p>
<p><strong>What's a good bedtime for a 4-month-old?</strong> Most land between 6:30 and 7:30 PM — roughly 2 hours after the last nap ends. If the last nap ran late, bedtime shifts with it.</p>
<p><strong>Can a 4-month-old nap too long?</strong> A single marathon nap that eats the day's sleep pressure can shortchange the night. Many families cap daytime naps around 2 hours; if nights are going fine, there's no need to wake a napper.</p>
<p><strong>Should I move bedtime earlier if a nap gets skipped?</strong> Yes — an earlier bedtime (commonly 30–60 minutes, rarely before 6:00 PM) is the standard bridge that keeps a lost nap from snowballing into an overtired night.</p>
<h2>Keeping two parents on the same day</h2>
<p>At 3–4 naps a day, timing drifts fast — a 20-minute-late nap moves everything behind it. This is the age where households start needing a shared record. In HAL's case that's your existing group chat: "woke 7:05" from whoever got up, and everyone sees the same schedule and the same next-nap window estimate, sized to your baby's own recent rhythm rather than a generic chart.</p>
""",
        "sources": [_SRC_SF_REGRESSION, _SRC_CC_REGRESSION, _SRC_AASM],
    },
    {
        "slug": "6-month-old-nap-schedule",
        "code": "g-6mo",
        "category": "By age",
        "page_title": "6-Month-Old Nap Schedule: 3 Naps, Wake Windows & a Sample Day",
        "title": "6-month-old nap schedule: 3 naps, wake windows, and a sample day",
        "description": "Most 6-month-olds settle on 3 naps with wake windows around 2–2.5 hours. A sample day, signs the third nap is on its way out, and how to keep every caregiver on the same schedule.",
        "teaser": "The 3-nap sweet spot, and the first hints of dropping to two.",
        "updated": "2026-08-26",
        "related": ["baby-sleep-schedules-by-age", "4-month-old-nap-schedule", "9-month-old-nap-schedule"],
        "body": """
<p>Six months is often the first genuinely predictable stretch: most babies settle on <strong>3 naps</strong> with wake windows around <strong>2–2.5 hours</strong>, and the day starts to look similar from one date to the next.</p>
<h2>The shape of the day</h2>
<ul>
<li><strong>Wake windows:</strong> about 2 h before nap 1, stretching toward 2.5 h by bedtime.</li>
<li><strong>Naps:</strong> two solid naps (often 1–1.5 h) plus a short third catnap late afternoon. Day sleep commonly totals ~2.5–4 hours.</li>
<li><strong>Night:</strong> commonly 11–12 hours, with the 24-hour total inside the recommended 12–16 hours.</li>
</ul>
<h2>Sample 6-month day</h2>
<table>
<thead><tr><th>Time</th><th>What</th></tr></thead>
<tbody>
<tr><td>7:00 am</td><td>Wake + feed</td></tr>
<tr><td>9:00–10:15</td><td>Nap 1</td></tr>
<tr><td>12:30–2:00</td><td>Nap 2</td></tr>
<tr><td>4:15–4:45</td><td>Nap 3 (catnap)</td></tr>
<tr><td>7:15–7:30 pm</td><td>Bedtime</td></tr>
</tbody>
</table>
<h2>Signs the third nap is on its way out</h2>
<p>Somewhere between 6 and 9 months (most commonly around 7–9), the catnap goes. You'll know it's close when the catnap starts routinely failing, when taking it pushes bedtime past 8, or when it happens but bedtime becomes a battle anyway. The move: cap or skip the catnap, pull bedtime as early as 6:30 for a few weeks, and stretch the two remaining windows gradually.</p>
<h2>Solids join the schedule</h2>
<p>Around 6 months, solids enter the day (typically after or between milk feeds, not replacing them yet). It's one more thing to coordinate — who fed what, when — and one more reason a shared log beats texting "did she eat?" back and forth. In HAL's case, "oatmeal 11:30, 5oz at 12" in the family thread keeps the food log and the sleep schedule in one place everyone can see.</p>
""",
        "sources": [_SRC_AASM, _SRC_AAP_HOURS, _SRC_HB_3TO2],
    },
    {
        "slug": "9-month-old-nap-schedule",
        "code": "g-9mo",
        "category": "By age",
        "page_title": "9-Month-Old Nap Schedule: 2 Naps, Wake Windows & a Sample Day",
        "title": "9-month-old nap schedule: 2 naps, wake windows, and a sample day",
        "description": "By 9 months most babies are on 2 naps with wake windows of about 2.5–3.5 hours. A sample day, the 8–10 month sleep bump, and keeping nannies and grandparents on the same schedule.",
        "teaser": "Two proper naps, longer windows, and the 8–10 month bump.",
        "updated": "2026-08-26",
        "related": ["baby-sleep-schedules-by-age", "6-month-old-nap-schedule", "12-month-old-nap-schedule"],
        "body": """
<p>By nine months the catnap is usually gone and the day has a clean two-nap architecture: wake windows of about <strong>2.5–3.5 hours</strong>, a real morning nap, a real afternoon nap.</p>
<h2>The shape of the day</h2>
<ul>
<li><strong>Wake windows:</strong> roughly 2.5–3 h before nap 1, 3–3.5 h before nap 2 and bedtime.</li>
<li><strong>Naps:</strong> two, ideally 1–1.5 h each; day sleep totals ~2–3.5 h.</li>
<li><strong>Night:</strong> commonly 11–12 h; many babies can go all or most of the night without a feed by now (ask your pediatrician about yours).</li>
</ul>
<h2>Sample 9-month day</h2>
<table>
<thead><tr><th>Time</th><th>What</th></tr></thead>
<tbody>
<tr><td>6:45 am</td><td>Wake + milk</td></tr>
<tr><td>9:30–10:45</td><td>Nap 1</td></tr>
<tr><td>2:00–3:30</td><td>Nap 2</td></tr>
<tr><td>7:00–7:15 pm</td><td>Bedtime</td></tr>
</tbody>
</table>
<h2>The 8–10 month bump</h2>
<p>Right when the schedule stabilizes, many babies hit a rough patch: separation anxiety peaks, crawling and pulling-to-stand are irresistible to practice in the crib, and naps or nights wobble for a few weeks. It's developmental, not a broken schedule — hold the routine steady, give lots of daytime practice for the new skills, and it passes. Motor-skill disruption usually settles within a few weeks; separation-anxiety waking can take longer, sometimes a few months. (If your baby fights nap 1 hard for weeks near 12 months, that's a different thing — see the 12-month guide.)</p>
<h2>The handoff problem gets real</h2>
<p>Nine-month-olds are often in part-time childcare or spending days with grandparents — and a 2-nap schedule with 3-hour windows falls apart when the morning handoff loses the wake-up time. A shared record fixes the handoff: with HAL, the nanny texts "down 9:35" in the same thread you use, and whoever does pickup already knows how the day went and when bedtime should land.</p>
""",
        "sources": [_SRC_AASM, _SRC_AAP_HOURS, _SRC_AAP_SEP_ANXIETY],
    },
    {
        "slug": "12-month-old-nap-schedule",
        "code": "g-12mo",
        "category": "By age",
        "page_title": "12-Month-Old Nap Schedule: 2 Naps, Wake Windows & a Sample Day",
        "title": "12-month-old nap schedule: two naps (for now)",
        "description": "A realistic 12-month-old schedule: still 2 naps for most, wake windows around 3–4 hours, a sample day, and why the one-year nap strike usually isn't the 2-to-1 transition yet.",
        "teaser": "Still two naps for most — don't let the nap strike fool you.",
        "updated": "2026-08-26",
        "related": ["baby-sleep-schedules-by-age", "9-month-old-nap-schedule", "2-to-1-nap-transition"],
        "body": """
<p>At twelve months most babies are still solidly on <strong>2 naps</strong>, with wake windows around <strong>3–4 hours</strong>. The headline for this age: many one-year-olds suddenly fight the morning nap, and it usually <em>isn't</em> time to drop it yet.</p>
<h2>The shape of the day</h2>
<ul>
<li><strong>Wake windows:</strong> about 3 h / 3 h / 3.5–4 h across the day.</li>
<li><strong>Naps:</strong> two, totaling ~2–3 h. The morning nap often shortens toward an hour.</li>
<li><strong>Night:</strong> commonly 11–12 h; the 1–2 year recommendation is 11–14 h per 24 including naps.</li>
</ul>
<h2>Sample 12-month day</h2>
<table>
<thead><tr><th>Time</th><th>What</th></tr></thead>
<tbody>
<tr><td>6:45 am</td><td>Wake</td></tr>
<tr><td>9:45–10:45</td><td>Nap 1</td></tr>
<tr><td>2:30–3:45</td><td>Nap 2</td></tr>
<tr><td>7:30 pm</td><td>Bedtime</td></tr>
</tbody>
</table>
<h2>The one-year nap strike</h2>
<p>Around 11–13 months many babies abruptly refuse a nap — usually the morning one — for a week or three, thanks to standing-and-walking practice, teething, or a wave of separation anxiety. The common mistake is reading this as the 2-to-1 transition and dropping the nap permanently; most babies genuinely need two naps until somewhere around 13–18 months, and dropping early buys weeks of overtired evenings. Hold the offer: keep putting baby down at the usual time, treat quiet crib play as rest, and most strikes end on their own. If the refusal persists for 3–4 weeks <em>with</em> the other readiness signs, then read the 2-to-1 guide.</p>
<h2>Knowing the difference takes a record</h2>
<p>"Is this a strike or the transition?" is answerable only from data: how many days, which nap, how long did she actually sleep, what happened to bedtime. That's exactly what a log in the family thread gives you — with HAL, you can just ask "how were naps this week?" and get the recap instead of reconstructing it from memory.</p>
""",
        "sources": [_SRC_AASM, _SRC_AAP_HOURS, _SRC_SF_12MO],
    },
    {
        "slug": "2-to-1-nap-transition",
        "code": "g-2to1",
        "category": "By age",
        "page_title": "The 2-to-1 Nap Transition: When and How to Drop to One Nap",
        "title": "The 2-to-1 nap transition: when and how",
        "description": "Most toddlers drop to one nap between 14 and 18 months. The readiness signs that matter, a gradual week-by-week method, sample days during the transition, and survival tips.",
        "teaser": "The trickiest nap transition — readiness signs and a gradual method.",
        "updated": "2026-08-27",
        "related": ["baby-sleep-schedules-by-age", "12-month-old-nap-schedule", "wake-windows-by-age"],
        "body": """
<p>The move from two naps to one is the trickiest nap transition — it's a big consolidation, and it happens while wake windows are stretching toward <strong>4–5 hours</strong>. Most toddlers make it between <strong>13 and 18 months</strong>, commonly around 15. Done gradually it takes 2–4 weeks; done abruptly it usually means a very cranky month.</p>
<h2>Real readiness signs (need several, for 2+ weeks)</h2>
<ul>
<li>Consistently fighting or skipping one of the naps (usually the second), while coping fine on the days it's missed</li>
<li>Nap 1 going long while nap 2 fails — or naps fine but bedtime pushed past 8:30</li>
<li>Early-morning wake-ups creeping in with no other cause</li>
<li>Age 13–14+ months — before that, a rough patch is far more likely a strike (see the 12-month guide)</li>
</ul>
<h2>A gradual method</h2>
<ol>
<li><strong>Shift, don't drop.</strong> Push nap 1 later by ~15–30 minutes every few days: 9:30 → 10:00 → 10:30 → 11:00, capping it so bedtime survives.</li>
<li><strong>Land at one midday nap</strong>, starting around 11:30–12:30, ideally 2–3 hours long. Keep shifting until it starts ~12:30–1:00.</li>
<li><strong>Protect bedtime with an early-bedtime bridge.</strong> During the transition, bedtime as early as 6:00–6:30 keeps overtiredness from wrecking the night.</li>
<li><strong>Expect hybrid weeks.</strong> Two-nap days after rough nights, one-nap days otherwise, is normal mid-transition.</li>
</ol>
<h2>Sample days</h2>
<table>
<thead><tr><th></th><th>Early transition</th><th>Settled (one nap)</th></tr></thead>
<tbody>
<tr><td>Wake</td><td>6:45 am</td><td>6:45 am</td></tr>
<tr><td>Nap</td><td>11:00–1:00</td><td>12:45–2:45</td></tr>
<tr><td>Bedtime</td><td>6:30–7:00 pm</td><td>7:30 pm</td></tr>
</tbody>
</table>
<h2>Which nap gets dropped?</h2>
<p>The morning nap. It shifts later and later until it <em>becomes</em> the single midday nap — you don't remove it, you slide it. The afternoon nap is the one that quietly disappears as the morning nap moves into its slot.</p>
<h2>What if my baby seems stuck between 2 naps and 1?</h2>
<p>The stuck state — two naps won't fit, one nap isn't enough — is the normal middle of this transition, not a sign it's failing. Run hybrid weeks: one-nap days by default, a two-nap rescue day after any rough night, and an early bedtime whenever the single nap came up short. Most babies un-stick within a few weeks.</p>
<h2>Fighting the second nap at 13 months — transition or strike?</h2>
<p>At 13 months it can be either. Check the other readiness signs: if she copes fine on days the second nap is skipped and bedtime holds, it's probably the real transition starting. If skipped-nap days end in a 5 PM meltdown, treat it as a strike, keep offering both naps, and revisit in two weeks.</p>
<h2>The coordination trap</h2>
<p>Transitions fail most often on inconsistency: daycare runs one schedule, the weekend runs another, grandma still does two naps. A toddler mid-transition needs everyone running the same play. Put the plan where every caregiver already is — with HAL, the current schedule and today's actual timing live in the family thread, so "which schedule are we on today?" has one answer for everyone.</p>
""",
        "sources": [_SRC_AASM, _SRC_HB_2TO1, _SRC_TCB_2TO1],
    },
    # ------------------------------------------------------------------ #
    # Practical / product-adjacent long-tail
    # ------------------------------------------------------------------ #
    {
        "slug": "share-baby-schedule-with-grandparents",
        "code": "g-share",
        "category": "Practical",
        "page_title": "How to Share Your Baby's Schedule with Grandparents & Caregivers",
        "title": "How to share your baby's schedule with grandparents and caregivers",
        "description": "Handoffs are where baby schedules fall apart. What every caregiver actually needs to know, why apps and paper both fail at it, and how to keep everyone on one routine in the group chat.",
        "teaser": "Handoffs are where routines die. Here's how to keep everyone synced.",
        "updated": "2026-08-26",
        "related": ["baby-tracker-without-an-app", "2-to-1-nap-transition", "9-month-old-nap-schedule"],
        "body": """
<p>Babies do best on a consistent routine — and the routine's weakest point is the <strong>handoff</strong>. You leave for the afternoon, grandma takes over, and suddenly nobody knows when the last feed was or when the nap window opens. The baby pays for it at bedtime.</p>
<h2>What a caregiver actually needs to know</h2>
<ul>
<li><strong>Today so far:</strong> last wake-up, last feed (and how much), last diaper.</li>
<li><strong>What's next and when:</strong> the next nap window and next feed, roughly.</li>
<li><strong>The invariants:</strong> wind-down steps, sleep location and safe-sleep rules, any allergies or medicines.</li>
<li><strong>Where to write what happens</strong> — so the <em>next</em> handoff works too.</li>
</ul>
<h2>Why the usual methods fail</h2>
<p><strong>Paper on the fridge</strong> captures the plan but not the day — it can't tell grandma the nap actually ended at 2:40. <strong>Baby-tracking apps</strong> capture the day but lose the caregivers: every grandparent and babysitter must install the app, make an account, be added to your family, and actually use it. In practice the least-technical caregiver — often the one doing the most solo hours — never logs in, and the record splits. <strong>Texting updates</strong> gets everyone participating but the information scrolls away, and nobody's doing the arithmetic on wake windows at 3 pm.</p>
<h2>The group chat, upgraded</h2>
<p>The family group chat is the one tool every caregiver already uses. What it lacks is memory and math — which is exactly what HAL adds. Add HAL to the thread and:</p>
<ul>
<li>Anyone logs by texting normally: "she ate 4oz at 2" — grandma needs zero new skills.</li>
<li>Anyone asks: "when's her next nap?" and gets an answer from <em>this baby's</em> recent rhythm, not a generic chart.</li>
<li>The handoff writes itself: the incoming caregiver scrolls up or asks for a recap of the day.</li>
</ul>
<h2>Make the handoff boring</h2>
<p>Whatever tool you use, the goal is that any adult can walk in mid-day and know the state of the day in under a minute, without calling you. That's what "protecting the routine" means in practice — the schedule survives the people changing.</p>
""",
        "sources": [_SRC_AAP_HOURS, _SRC_SAFE_SLEEP],
    },
    {
        "slug": "baby-tracker-without-an-app",
        "code": "g-noapp",
        "category": "Practical",
        "page_title": "Baby Tracker Without an App: Track Feeds & Naps by Text",
        "title": "A baby tracker without an app: tracking feeds and naps by text",
        "description": "App fatigue is real, and baby-tracking apps lose half the household. Why texting is the best interface for logging feeds and naps, and what a text-based baby tracker looks like.",
        "teaser": "Why the best baby-tracking interface is the one you already have.",
        "updated": "2026-08-27",
        "related": ["share-baby-schedule-with-grandparents", "pediatrician-visit-checklist", "wake-windows-by-age"],
        "body": """
<p>Every exhausted parent has done it: downloaded a highly-rated baby-tracking app, logged diligently for two weeks, and quietly stopped. Not because tracking isn't useful — it is — but because the interface asks too much of people running on four hours of sleep.</p>
<h2>Why tracking apps lose the household</h2>
<ul>
<li><strong>The two-parent problem.</strong> The record only works if <em>everyone</em> logs. If one parent lives in the app and the other doesn't, you have half a log — worse than none, because you trust it.</li>
<li><strong>The caregiver problem.</strong> Grandparents and babysitters won't install, register, and learn an app for Tuesday afternoons.</li>
<li><strong>The 3 AM problem.</strong> Unlock, find app, tap through four screens, select left/right, start timer — one-handed, in the dark. A text is one thumb: "4oz."</li>
<li><strong>The data problem.</strong> Your baby's daily life is intimate data, and app privacy policies vary wildly on what's collected and shared.</li>
</ul>
<h2>Can I track feedings and naps by text message?</h2>
<p>Yes — that's exactly what HAL is. Add it to your family group chat and texting "4oz at 3:15" or "down for nap" <em>is</em> the logging. It reads plain English, keeps the running record, and answers questions like "when did she last eat?" for anyone in the thread. No app, no accounts for caregivers.</p>
<h2>Texting is the interface that survives</h2>
<p>Text messaging is already installed, already understood by every adult in your baby's life, already open in the group chat you use anyway. A tracker built on text means logging is as hard as sending "woke up 6:50" — which is to say, not hard at all, which is why it actually keeps happening in week six.</p>
<h2>What HAL does with those texts</h2>
<ul>
<li><strong>Logs</strong> feeds, naps, wake-ups, and diapers from plain English — "4oz at 3:15" is enough.</li>
<li><strong>Answers</strong> — "when did she last eat?", "how were naps today?" — for anyone in the thread.</li>
<li><strong>Anticipates</strong> — next-nap and next-feed estimates from your baby's own recent rhythm, with honest uncertainty.</li>
<li><strong>Exports and deletes on request</strong> — text "export" for your full log; text "forget me" and everything is permanently deleted. No ads, never sold.</li>
</ul>
<h2>When you do want an app anyway</h2>
<p>Fair cases exist: pumping-session timers, medical-grade charts for a NICU graduate, wearable integrations. If that's you, use the app — and consider keeping the family-facing layer in the group chat regardless, because the app still won't get grandma logging.</p>
""",
        "sources": [_SRC_AAP_HOURS, _SRC_ENOUGH_MILK],
    },
    {
        "slug": "baby-tracker-privacy",
        "code": "g-priv",
        "category": "Practical",
        "page_title": "Baby Tracker Privacy: 5 Questions to Ask — and HAL's Answers",
        "title": "Before you use any baby tracker: five privacy questions",
        "description": "A baby log is intimate data — feeds, sleep, health worries, your family's daily rhythm. Five privacy questions to ask of any baby-tracking app, and HAL's plain answers to each.",
        "teaser": "Your baby's data is intimate. Ask these five questions of any tracker.",
        "updated": "2026-08-27",
        "related": ["baby-tracker-without-an-app", "share-baby-schedule-with-grandparents", "pediatrician-visit-checklist"],
        "body": """
<p>A baby log is one of the most intimate datasets a family produces: when your child eats and sleeps, what worried you at 3 AM, when your home is on its daily rhythm. Most parents vet a stroller harder than they vet the app that will hold all of that. Regulators have already had to step in against health apps that shared user data with third parties, and app privacy policies vary enormously — so before you commit to any tracker (ours included), ask five questions.</p>
<h2>1. What's the business model?</h2>
<p>If the product is free forever, ask what pays for the servers. "Free plus ads" usually means the data you enter is feeding an advertising machine somewhere. A straightforward paid product has a straightforward reason to keep your data private: you're the customer, not the inventory.</p>
<h2>2. What does the policy say about "sharing with partners"?</h2>
<p>Words like "affiliates," "partners," and "for marketing purposes" in a privacy policy are where your baby's data leaves the building. This isn't hypothetical: a 2026 peer-reviewed audit of 14 popular baby-tracking apps found <strong>all 14 shared data with third parties</strong> — including due dates and pregnancy-loss data. Regulators have acted too: the FTC barred the Premom fertility app from sharing health data for advertising after it sent users' reproductive-health details to third parties against its own promises. Read that paragraph before entering a single feed.</p>
<h2>3. Can you delete everything — easily?</h2>
<p>Not "email support and wait." One clear, self-service action that permanently removes your family's data. If deletion is hard to find, that tells you how the company thinks about ownership.</p>
<h2>4. Can you get your data out?</h2>
<p>Your baby's history is yours. There should be a real export — usable, complete, whenever you want it — not screenshots.</p>
<h2>5. Who else has to create an account?</h2>
<p>Every caregiver who must register is another account, another password, another copy of the access. Grandparents shouldn't need to join a platform to tell you the baby napped.</p>
<h2>HAL's answers, on the record</h2>
<ul>
<li><strong>Business model:</strong> HAL is a paid product. No ads, ever. Your family's data is never sold — being the product is the thing we built HAL to avoid.</li>
<li><strong>What we hold:</strong> only what your household chooses to text. HAL's record is the messages you send it — there's no background collection, no location tracking, no contact scraping.</li>
<li><strong>Deletion:</strong> text <em>"forget me"</em> and the household's stored data is permanently deleted. One text, no support ticket.</li>
<li><strong>Export:</strong> text <em>"export"</em> and HAL prepares your full log as a file. Yours to keep, bring to the pediatrician, or take elsewhere.</li>
<li><strong>Accounts:</strong> caregivers need none. No installs, no registrations — the record lives in the group chat your family already uses.</li>
<li><strong>This website:</strong> no third-party trackers, no ad pixels. (Check the network tab — we'll wait.)</li>
</ul>
<h2>Hold us to it</h2>
<p>Privacy promises are only as good as your ability to verify them. Ours are testable from your phone: send "export" and see exactly what we hold; send "forget me" and watch it go. If a promise on this page ever stops being true, that's a betrayal of the one job a family assistant has — keeping your family's trust.</p>
""",
        "sources": [_SRC_IPR_BABYAPPS, _SRC_FTC_PREMOM, _SRC_MOZILLA_PNI, _SRC_BMJ_APPS],
    },
    {
        "slug": "pediatrician-visit-checklist",
        "code": "g-ped",
        "category": "Practical",
        "page_title": "Pediatrician Visit Checklist: What to Track & Bring (0–12 Months)",
        "title": "Pediatrician visit checklist: what to track and bring",
        "description": "What pediatricians actually ask at well-child visits — feeds per day, wet diapers, sleep, milestones — and how to arrive with real numbers instead of 3 AM guesses.",
        "teaser": "The questions they'll ask, and how to arrive with real numbers.",
        "updated": "2026-08-26",
        "related": ["newborn-sleep-schedule", "baby-tracker-without-an-app", "wake-windows-by-age"],
        "body": """
<p>Well-child visits are frequent in year one — the AAP schedule runs roughly newborn, 1, 2, 4, 6, 9, and 12 months — and each one opens with the same thing: <strong>questions with numeric answers</strong>. Parents who track arrive with data; everyone else estimates from memory, and the estimates are famously bad.</p>
<h2>What they'll ask, by age</h2>
<table>
<thead><tr><th>Visit</th><th>Expect questions about</th></tr></thead>
<tbody>
<tr><td>Newborn–2 months</td><td>Feeds per day and amounts; <strong>wet diapers per day</strong> (about 6+ after the first week is the classic adequacy sign); stools; sleep stretches; jaundice, spit-up</td></tr>
<tr><td>4–6 months</td><td>Feeding pattern, starting solids readiness; sleep totals and night wakings; rolling; the 4-month sleep change</td></tr>
<tr><td>9 months</td><td>Solids variety, cup practice; nap schedule; crawling, pulling to stand; separation anxiety; teeth</td></tr>
<tr><td>12 months</td><td>Transition to whole milk; nap transition status; steps and words; sleep through the night</td></tr>
</tbody>
</table>
<h2>Bring three things</h2>
<ol>
<li><strong>A recent-week summary:</strong> typical feeds/day with amounts, wet diapers/day, total sleep and nap pattern, anything that changed.</li>
<li><strong>Your questions, written down.</strong> The visit is short and 3 of your 5 questions evaporate in the room. Keep a running list between visits.</li>
<li><strong>The weird-thing evidence.</strong> Rash, odd breathing, strange stool: a photo or video beats any description.</li>
</ol>
<h2>Make the log a side effect</h2>
<p>Nobody maintains a spreadsheet for the pediatrician. The trick is a log that happens anyway, as a side effect of normal family coordination. That's HAL's model: the feeds and naps your household already texts into the group chat <em>are</em> the record — before a visit, text "export" and bring the full log, or just ask "how many feeds a day this week?" on the drive over.</p>
<h2>Between visits</h2>
<p>For anything urgent or worrying, call — don't wait for the well-child visit, and don't let a normal-looking log talk you out of a gut feeling. The record is for better conversations with your pediatrician, never a substitute for them.</p>
""",
        "sources": [_SRC_WELL_CHILD, _SRC_ENOUGH_MILK, _SRC_AAP_HOURS],
    },
]

GUIDES_BY_SLUG: dict[str, dict] = {g["slug"]: g for g in GUIDES}
