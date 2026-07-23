# RinzUP — "DuoLingo Concept" Homepage

Prototype: open `index.html` in any browser. Fully self-contained (one Google Fonts request; everything else inline). Mobile-first, no build step, no dependencies.

**Brand pass applied (2026-07-22):** placeholder branding swapped for the real RinzUP identity per `rinzUP_Brand_Style_Guide_for_Claude_Design.md` — brand palette (Primary Blue `#185BB4`, Deep Navy `#0F3D70`, Golden Yellow `#FFC53E` for primary CTAs with Amber `#D37E28` depth shadows, per the guide's "gold sparingly, navy/white carry backgrounds" rule), the full logo lockup in the header, the circular Zeke icon as favicon and confirmation moment, Zeke full-body in the hero, tagline "Spotless Results. Wildly Reliable.", real service area (King & Snohomish Counties) and phone (425-645-5999), and the catchphrase "Let's rinzUP this place!" at the booking confirmation. Web-sized copies of the assets live in `assets/`. Layout, functionality, and interactions unchanged.

---

## 1. Design Philosophy & Primary Customer Journey

**Philosophy:** Getting a quote from a contractor usually feels like homework. Duolingo made *actual homework* feel like a game people do voluntarily every day. This concept borrows that psychology — one tiny question at a time, visible progress, instant reward — and applies it to the single moment that matters on a home-services site: finding out what it costs.

The homepage is not a brochure with a form at the end. The estimate quiz **is** the homepage. Everything else (before/after, services, proof, FAQ) exists to feed people back into it.

**Primary journey (mobile-first):**
1. Land → mascot + one sentence: what we do, and "see your price in 60 seconds, no phone/email."
2. Tap the CTA → 4-question quiz: services (multi-select) → home height → grime level → ZIP. A live price ticker updates from the very first answer, so pricing mystery dies at question one.
3. Result: an honest price range + a celebration. **Only now** do we ask for name + phone — the smallest possible commitment, framed as "lock in a free exact quote."
4. Cautious researchers who scroll past instead get: drag-to-rinse before/after → tappable service path (each service answers its own objection in context) → reviews/insurance/guarantee → FAQ → CTA again. Every scroll path dead-ends into the quiz.

## 2. The Five Distinctive Interactions

1. **The Estimate Quiz as hero content** — Duolingo-style stepper with progress bar, chunky "3D press" buttons, auto-advance on single-choice steps, and a back button. Price ranges appear *before* any personal info is requested (only ZIP, justified as service-area check).
2. **Live price ticker** — the running `$lo–$hi` range updates with every answer, including a visible bundle discount. Pricing transparency becomes the reward loop.
3. **"Drag to rinse" before/after slider** — the visitor physically wipes the grime off a house. The product's core promise as a toy.
4. **Service path with objection-in-context** — services rendered as a winding Duolingo-style skill path. Each node opens a bottom sheet: outcome-first description, starting price, and the #1 fear for that service ("won't pressure ruin my roof?") answered right there — then "Add to my estimate" pipes the selection straight into the quiz.
5. **Micro-celebration & badges** — confetti of droplets and a tongue-in-cheek "You earned: Transparent Pricing" badge at the result, plus light social proof ("12 neighbors got estimates this week"). Memorability without adding steps.

## 3. Assumptions

- Services & starting prices are placeholders: House Wash $199, Roof $349, Driveway $149, Windows $99, Gutters $129, Deck/Fence $179; multipliers for stories (×1–1.7) and grime (×1–1.3); 5% bundle discount per extra service. All trivially editable in the `SERVICES/SIZES/GRIME` arrays at the top of the script.
- The business can honor an online range with a free on-site exact quote, and follows up by text within the hour.
- Reviews, stats ($2M insurance, 2,400 homes, 4.9★) are placeholder proof to be replaced with real data.
- Branding is deliberately placeholder (name + a water-drop mascot "Rinzy"); final brand pass comes later per the project plan.
- Form submission is front-end only (no backend yet); it shows the confirmation state.

## 4. The Three Biggest Risks / Tradeoffs

1. **Range accuracy vs. trust.** Showing prices early only builds trust if the on-site quote usually lands inside the range. If real jobs frequently exceed it, the transparency play backfires. Mitigation: wide-ish ranges, explicit "confirmed free on-site" copy, and a policy of flagging changes before work starts.
2. **Playfulness vs. credibility.** Emoji, mascot, and confetti make it memorable, but some homeowners (especially for a $500+ roof job) may want a more "serious" contractor. The trust section (insurance, guarantee, reviews) is the counterweight; the final brand pass can dial tone up or down.
3. **Quiz-first vs. skimmers.** Visitors who refuse any interaction get less information above the fold than a conventional layout would give them. The scroll path covers them, but the concept genuinely bets on interaction — if analytics show low quiz starts, the hero needs a static price anchor ("house washes from $199") as a fallback.

## 5. Notes for teammates (shared-brief compliance)

- Every Experience Objective is mapped: tiny step one (tap one card), pricing before personal info, objections answered in context (bottom sheets + FAQ), proof before commitment, one dominant CTA, mobile-first, no dead ends.
- Duolingo was used as *inspiration for interaction psychology and visual energy* (progress, chunkiness, celebration), not copied: layout, illustration, palette usage, and all copy are original.
