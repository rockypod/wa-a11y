# WA-A11y — WCAG 2.2 AAA manual checklist (wa-a11y's own pages)

Automated checks (`scripts/selfscan`: axe-core + Alfa, focus/reflow/text-spacing probes) cannot
prove AAA. A person signs this off **for every release**. Mark each row ✔ (verified), ✖ (needs work,
link an issue) or N/A (with reason). Never describe wa-a11y as "AAA conformant" without this.

| SC | Name | What to check on wa-a11y | Status | Notes |
|---|---|---|---|---|
| 1.2.6 | Sign Language (Prerecorded) | No prerecorded audio/video on the site | | |
| 1.2.8 | Media Alternative (Prerecorded) | No prerecorded video | | |
| 1.2.9 | Audio-only (Live) | No live audio | | |
| 1.4.6 | Contrast (Enhanced) | Tools check text; also check focus ring, borders, status boxes by eye in light, dark and extra-contrast themes | | |
| 1.4.8 | Visual Presentation | Colours selectable (settings), ≤ 80 ch lines, no justify, line height ≥ 1.5, paragraph gap ≥ 1.5× line, 200% text with no horizontal scroll | | |
| 1.4.9 | Images of Text (No Exception) | No images of text anywhere | | |
| 2.1.3 | Keyboard (No Exception) | Every task (scan, results, settings, help) works with keyboard only | | |
| 2.2.3 | No Timing | Nothing is timed; status page never refreshes itself | | |
| 2.2.4 | Interruptions | No pop-ups, alerts or auto-updates | | |
| 2.2.6 | Timeouts | Session/form expiry never loses entered data (form is shown again with input) | | |
| 2.3.2 | Three Flashes | Nothing flashes | | |
| 2.3.3 | Animation from Interactions | No animation or transitions at all | | |
| 2.4.9 | Link Purpose (Link Only) | Every link's text alone says where it goes (no "click here", "more") | | |
| 2.4.10 | Section Headings | Every section has a heading; heading levels are in order | | |
| 2.4.12 | Focus Not Obscured (Enhanced) | Focused item never hidden by anything (selfscan checks on-screen; also check by eye) | | |
| 2.4.13 | Focus Appearance | Focus ring ≥ 2px, contrast ≥ 3:1 against both sides, in every theme | | |
| 2.5.5 | Target Size (Enhanced) | All non-inline targets ≥ 44×44 px (Alfa checks; confirm at 320 px and 200% zoom) | | |
| 3.1.3 | Unusual Words | Jargon explained (WCAG, axe-core, Alfa, "success criterion") on Help | | |
| 3.1.4 | Abbreviations | Abbreviations expanded on first use (`<abbr>`) | | |
| 3.1.5 | Reading Level | Plain language: content readable at lower-secondary level | | |
| 3.1.6 | Pronunciation | No words whose meaning depends on pronunciation | | |
| 3.2.5 | Change on Request | Nothing changes until the user submits (settings apply on Save) | | |
| 3.3.6 | Error Prevention (All) | Every submission can be reviewed/corrected; nothing irreversible without confirmation | | |

Also test once per release with: NVDA + Firefox, VoiceOver + Safari, keyboard only, 400% zoom,
Windows High Contrast / forced colours, each reading font.

## Sign-off

| Release | Date | Checked by | Result |
|---|---|---|---|
| | | | |
