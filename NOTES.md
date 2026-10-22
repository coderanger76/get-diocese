# get-diocese: Project Notes

Design reference and change history. For usage, see [README.md](README.md).

## Files

```
get-diocese        bash launcher: activates venv, runs main.py
main.py            the terminal app (scraping, SQLite cache, ANSI rendering, key loop)
presentation.py    Pillow compositor for the shareable PNG cards
dioceses.json      seed data: 183 US dioceses/archdioceses/eparchies
diocese.db         SQLite cache (generated, gitignored)
examples/          sample output cards
```


## How the terminal app works (`main.py`)

- **Config/seed**: `dioceses.json` has 183 entries — every Latin-rite diocese/
  archdiocese and Eastern-rite eparchy in the US, one row each with
  `name, type, state, city, wikipedia, url`.
- **DB**: `diocese.db` (SQLite) is created and seeded from the JSON on first
  run. Each visit updates the row in place (`save_result`) — bishop, founded
  date, Catholic population, parishes, priests, deacons, total population,
  area, cathedral, a Wikipedia summary, and a scraped website excerpt.
  `url_verified` and `cached_at` track freshness; nothing ever re-fetches a
  field it already has (`COALESCE(NULLIF(...))` pattern), so data only
  accumulates, never regresses to blank.
- **Random pick**: prefers an unvisited diocese (`visited = 0`); once all 183
  have been visited at least once, it falls back to fully random reroll. The footer's "X/183 visited"
  counter is the count of distinct dioceses explored at least once
  (`count_visited()`), queried fresh from the DB after each visit — it used to
  show the current diocese's own per-row visit count instead, which since
  `pick_random` prefers never-visited rows was almost always `0 + 1 = 1` no
  matter how many dioceses had actually been seen (since fixed).
- **Data sources per visit**:
  1. `validate_url` — HEAD (falling back to streamed GET) to catch redirects
     and dead links, only if not already verified.
  2. `fetch_wikipedia` — hits the REST summary endpoint for a clean lead
     paragraph, then scrapes the infobox table from the full page HTML with
     BeautifulSoup, regex-matching row labels (bishop/founded/cathedral/
     parishes/priests/deacons/population/catholics/area) to fields. Handles
     the common "Population — Total / Catholics" combined infobox row by
     splitting out both numbers plus the percentage.
  3. `fetch_website_excerpt` — best-effort crawl of the diocese's own site:
     looks for an About/History-ish link, falls back to the front page,
     strips nav/header/footer/script/style, and keeps the first 5 sentences
     over 50 chars (capped at 700 chars) from the main content area.
- **Rendering**: hand-rolled ANSI terminal UI (256-color amber/magenta/gray
  palette, `os.system('clear')` between frames, raw-mode single-keypress
  input via `termios`/`tty`). Header bar, stat pairs in a two-column layout,
  About/From-the-Diocese sections, Sources footer, status footer with visit
  counter. No external TUI library — everything is manual ANSI codes + a
  `visible_len` helper that strips escape codes for width math.
- **User-Agent**: identifies itself honestly as
  `get-diocese/1.0 (terminal explorer; https://github.com/coderanger76/currents)`.

## Change history

### Visited counter fix
The footer's "X/183 visited" used to show the current diocese's own visit count, which was almost always 1 because `pick_random` prefers unvisited rows. It now shows the number of distinct dioceses visited, via `count_visited()`, queried after each visit.

### Present feature (`P`) — `presentation.py`
Renders a PNG "card" for the currently displayed diocese, built from data
already scraped for the terminal view (no extra fetches except the images
themselves). Never shown in the terminal — purely a file output. (Originally
landscape-only; expanded to three output shapes later the same day — see the
addendum below.)

- **Image scraping** (`main.py`, in `fetch_wikipedia`): added
  `extract_infobox_images()`, which pulls three images out of the Wikipedia
  infobox alongside the existing text scrape:
  - **Coat of arms** — reliable, matched by filename (`coat_of_arms` always
    appears in the Commons filename).
  - **Cathedral photo** — heuristic: the *first* infobox image that's neither
    the coat of arms nor a small flag icon (≤48px). This is reliably the
    infobox's lead photo across the dioceses checked.
  - **Diocesan map** — heuristic: the *last* such image, when there are at
    least two candidates (so a diocese with only a cathedral photo doesn't
    mistakenly get it reused as the "map").
  - Resolution gotcha: Wikimedia's thumbnail service only serves a small set
    of pre-generated widths and 400s on anything else ("Use thumbnail sizes
    listed on https://w.wiki/GHai") — rewriting the `/250px-` URL segment to
    an arbitrary width doesn't work. Fixed by reading the `srcset` attribute's
    `2x` entry instead, which is always a Wikipedia-approved higher-res URL
    (`_best_src()`). None of these three URLs are persisted to `diocese.db` —
    they're only ever pulled fresh into the in-memory `data` dict for the
    current session's possible `P` press.
- **Compositing** (`presentation.py`, new file): Pillow-based. Ivory page
  background, deep-gold header band, cardinal-maroon sub band, warm-charcoal
  text — a deliberately "classy/print" palette, distinct from the terminal's
  dark ANSI theme (colors picked by Claude's judgment per the maintainer's ask).
  Layout: coat of arms + cathedral photo side by side top-left, diocesan map
  below them, bishop/cathedral fields and a 3×2 stat-tile grid (Catholics,
  Population, Parishes, Priests, Deacons, Area) to the right, About excerpt,
  footer with `Source: Wikipedia · <domain>` on the left and
  `@_catholicwest · X` / `@catholicwest · Substack` on the right in maroon.
  Any image that can't be found/fetched renders as an empty "not found" box
  rather than breaking the layout. Stat-tile values that are too wide for
  their tile (e.g. long area strings) auto-shrink through a list of font
  sizes (`_fit_font`) rather than overflowing.
  Output overwrites a fixed filename per format (per the maintainer's choice — not
  archived per-diocese; see addendum for the per-format filenames). On macOS,
  `build_presentation` shells out to `open` on save so the PNG pops up in
  Preview immediately ("pop out to screen so I don't have to hunt for it in
  the filesystem" — his words) rather than requiring a manual Finder trip.
- **Terminal wiring** (`main.py`): footer gained a `P PRESENT` key hint next
  to `L LUCKY`. `main()` was refactored to hold the current `(diocese, data)`
  across keypresses (new `load_diocese()` helper factored out of the old
  inline fetch code) so pressing `P` doesn't reroll or re-fetch — it reuses
  what's already on screen, then shows a one-line cyan toast confirming the
  save and loops back to the same card.
- **Manual override workflow**: Wikipedia infoboxes are often incomplete
  (the maintainer's example: Diocese of Monterey was missing priests/deacons/area,
  numbers he could look up himself from the diocesan website). Pressing `P`
  now first asks `Adjust figures before generating? [y/N]`; a `y` drops into
  cooked-mode `input()` prompts (`prompt_overrides()`) for the six stat
  fields, Enter keeps the current value. Anything typed is merged into `data`/
  `diocese` for the render **and** written back through the existing
  `save_result()` cache path — so a manual correction persists in
  `diocese.db` and is still there next time that diocese comes up, not just
  for the one image. (Flagged to the maintainer; persistence of corrections is easy
  to change to session-only if preferred.)
- **Bug fix found along the way**: `stat_pair()` used to drop an entire row
  (e.g. "Parishes / Priests") if only the *left* field was blank, even when
  the right field had a value — which the override flow hits constantly,
  since the user often fills in just one missing field at a time. Fixed to
  print the lone value alone instead of silently dropping it.

Net result confirmed visually on Wheeling-
Charleston, Harrisburg, San Francisco, and Biloxi — crest/cathedral/map all
picked correctly, stat tiles handle both missing and overridden values, footer
handles render correctly.

### three output shapes (landscape/portrait/square)

the maintainer wanted to pick an output aspect ratio after adjusting figures, or
generate all three at once, rather than always getting the one hard-coded
landscape card. `presentation.py` was restructured around a `FORMATS` dict:

| format      | size      | use case                     |
|-------------|-----------|-------------------------------|
| `landscape` | 1600×900  | X/Twitter-style, original two-column layout |
| `portrait`  | 1080×1350 | Instagram feed, stacked single column |
| `square`    | 1080×1080 | Instagram square ("Insta"), stacked + tighter |

- **Landscape** keeps the original two-column layout verbatim (images left,
  text right) — `_render_landscape()`, unchanged visually from the first cut.
- **Portrait/square** share a new stacked single-column layout
  (`_render_stacked()`): crest + cathedral side by side, map full-width below
  them, then bishop/cathedral fields, the 3×2 stat grid, and (space
  permitting) an About excerpt — all in one column since there's no room for
  a side text column at 1080px wide.
- Getting square to fit was the hard part — 1080×1080 minus header/sub-band/
  footer only leaves ~800px of vertical budget for images + text + 6 stat
  tiles, which overflowed badly on the first pass. Iterated by generating the
  actual PNG and visually reading it back (rather than eyeballing pixel math)
  to retune the per-format constants in a `tuning` dict (image/map heights,
  tile heights, gaps, line heights, font sizes) until everything fit cleanly
  with a little breathing room left for a short 2-line About excerpt.
- Header title font is now adaptive (`_title_font`) — tries a list of sizes
  and shrinks until the diocese name fits next to the "FAITH · TYPE" tag,
  since long names (e.g. "Archdiocese of Saint Paul and Minneapolis") would
  otherwise overflow the narrower 1080px-wide formats. Stat-tile value
  shrinking (already in place for landscape) carried over unchanged and
  handles pathological cases fine, e.g. one diocese's Wikipedia infobox listed
  priests as "340 diocesan (208 active, non-retired) 78 religious" — shrinks
  to the smallest size and still fits its tile.
- Output filenames are now per-format and always overwritten:
  `presentation_landscape.png`, `presentation_portrait.png`,
  `presentation_square.png` (the plain `presentation.png` name from the first
  cut is gone). `build_presentation()` takes a new `fmt=` argument
  (`"landscape"` default) instead of always producing one shape.
- **Terminal wiring** (`main.py`): after the existing "Adjust figures?"
  prompt, `P` now also asks `Format?  [L]andscape  [P]ortrait  [S]quare
  (Insta)  [A]ll three` (`FORMAT_KEYS` dict maps the keypress to a list of
  formats to build; unrecognized keys default to `['landscape']`). All
  requested formats are built and opened in one go, and the toast lists every
  filename saved.

Confirmed visually across all three shapes on Wheeling-Charleston (clean
bake) and the Archdiocese of Saint Paul and Minneapolis (stress case — long
name, missing deacons, oversized priests string) — no overflow or clipping in
any format.



Two reports from the maintainer after a couple of days of real use: (1) the About
excerpt on portrait/square was visibly cutting off mid-sentence with no
indication, and (2) he wanted a shape that "fills much of an iPhone screen in
X and Substack apps" so a viewer doesn't have to pinch-zoom to read it.

### About-text truncation — `_wrap()` in `presentation.py`
**Superseded later the same day — see the follow-up addendum below.** First
pass: root cause was `_wrap()` always slicing to `lines[:max_lines]` with no
marker, so a paragraph that ran longer than the space available just stopped
wherever the words happened to wrap to — e.g. Wheeling-Charleston's square
card ended literally on "...Evelio Menjivar-Ayala is the" (bishop's name,
then nothing). First fix was an ellipsis on truncation (skipped when the cut
already landed on a sentence-ending `.`/`!`/`?`, to avoid a stray
"...Baltimore.…"). the maintainer came back and said he'd rather see the whole
paragraph than an ellipsis at all — see below for the real fix.

### New `mobile` format (1080×1920) — fills a phone screen without zooming
Diagnosis: the "have to zoom in" complaint wasn't really about aspect ratio —
X and Substack both scale a shared image to the viewer's screen/device
width, so what actually determines whether text reads comfortably is the
*font-size-to-canvas-width ratio*, not the megapixel count or the shape. The
existing portrait/square cards use body text around 16-19px on a 1080px-wide
canvas — fine on a desktop monitor, but on a phone whose physical width is
often close to that same ~1080px, that's a genuinely small font rendered
close to 1:1, hence the zooming.

Fix was two-part, not just "add a taller format":
- Added a fourth shape, `mobile` (1080×1920, a Stories/Reels-style 9:16) —
  taller than `portrait`/`square` so there's room to spread content out.
- Crucially, gave it its **own much larger font sizes** throughout (title up
  to 52pt, stat values up to 36pt, body text 23pt, vs. 19px/16px on
  portrait/square) rather than just stretching the existing stacked layout
  into a taller box. Taller alone wouldn't have fixed the actual complaint.
- To support this without four near-duplicate layout functions,
  `_render_stacked()` was generalized: every size that used to be a handful
  of hardcoded literals (or a `fmt == "portrait"` ternary) is now pulled from
  a per-format `STACKED_TUNING` dict (`square`/`portrait`/`mobile`) — header/
  sub band height, tag/sub/title font sizes, image row and map heights, gaps,
  caption/label/value/stat font sizes, bishop/cathedral line height, divider
  gaps, and the About section's line height and `footer_zone`. `_header()`
  and `_footer()` were widened to take explicit size arguments instead of
  inferring them from canvas width.
- The About section's remaining-space math (`max_lines = ... (content_bottom
  - y - line_h) // line_h`) already adapted dynamically to whatever's left
  over, so no per-format hand-tuning was needed there beyond picking
  `body_size` — it just works out how many lines fit and lets the new
  ellipsis fix handle the rest cleanly.
- **Terminal wiring** (`main.py`): `FORMAT_KEYS` gained `'m': ['mobile']`,
  the `[A]ll` option now includes all four, and the format prompt text
  updated to `[L]andscape [P]ortrait [S]quare [M]obile [A]ll four`.

Confirmed visually on Wheeling-Charleston across square/portrait/mobile —
ellipsis renders correctly (with and without a pre-existing period at the
cut point), and mobile fills its taller canvas cleanly with noticeably larger
text/images and no overflow.

### full About text, no ellipsis — measure-first + grow-canvas

the maintainer: "I'd kind of prefer it if there were no ellipsis and it just
included the entire about section of text." Pasted a Diocese of Memphis
terminal capture as the target — its full ~270-char About paragraph should
show in full on the presentation card, not a shortened version.

Real fix, not just "allow more lines": `presentation.py`'s About rendering
was rebuilt around a measure-before-you-draw approach, since the whole
problem with the old approach was choosing a line cap *before* knowing how
long the actual paragraph was.

- New `_plan_about()`: given the full text and a list of font sizes
  (largest first), wraps the *entire* paragraph (never slices to N lines)
  at each size and returns the first one whose total wrapped height fits the
  space available — or, if none fit even at the smallest size, returns that
  smallest-size plan anyway. Nothing is ever cut; worst case, the text is
  just smaller (or the canvas grows — next point).
- New geometry-only helpers `_landscape_before_about()` and
  `_stacked_before_about()` compute, via plain arithmetic (no drawing), the
  exact y-coordinate where the About block starts — mirroring
  `_render_landscape`/`_render_stacked`'s real layout math but callable
  *before* a canvas exists. This is what makes planning possible: know where
  About starts and how much room is nominally left, without having drawn
  anything yet.
- `build_presentation()` now runs a **measurement pass** (a throwaway 10×10
  `ImageDraw`, cheap) before creating the real canvas: compute
  `y_before_about`, hand the full summary + a per-format list of candidate
  font sizes to `_plan_about()`, and see how tall the About block actually
  needs to be. If that exceeds the nominal canvas's remaining space, **the
  canvas grows** — `H = max(H_nominal, actual_content_bottom + MARGIN +
  footer_zone)` — rather than the text losing anything. Images/stat-grid
  sizing stays anchored to the nominal layout either way; only the About
  block and footer shift down when growth happens.
- Landscape gained a `LANDSCAPE_TUNING` dict (mirroring `STACKED_TUNING`)
  so its geometry constants live in one place instead of being scattered
  literals — needed so `_landscape_before_about()` can't silently drift out
  of sync with the real drawing code.
- `_render_landscape()`/`_render_stacked()` no longer do their own line-
  wrapping or line-count math for About at all — they just take the
  precomputed `about_plan` (font, lines, line height) and draw it verbatim,
  and take an explicit `footer_top_y` instead of computing their own
  `FOOTER_ZONE`/`content_bottom`.
- The now-unused `_wrap()` (and its ellipsis logic from the morning's first
  fix) was deleted entirely — nothing calls it anymore.
- **Bonus bug found via stress-testing** (Archdiocese of New York, whose
  Wikipedia infobox has an unusually long founding string — original 1808
  founding *and* the 1850 archdiocese redesignation, both dates): the
  maroon sub-band (city/founded line) had no shrink-to-fit at all, unlike
  the header title, and the long string ran straight off the right edge of
  the canvas — an actual clip, same category of bug as the About text issue.
  Fixed the same way the title already was: `_header()` now tries a list of
  shrinking font sizes for the sub-band text via the existing `_fit_font()`
  helper until it fits the canvas width.

Confirmed on the Diocese of Memphis text the maintainer pasted (full paragraph,
no cuts, across all four formats) and stress-tested with the Archdiocese of
New York's much longer ~610-char summary plus its overflowing founded-date
string — square/portrait grew a little taller (1080×1111, 1080×1399) to fit
the full paragraph at a still-readable size, mobile and landscape had enough
nominal room and didn't need to grow, and the sub-band fix kept the long
founded string fully on-canvas in every format.
