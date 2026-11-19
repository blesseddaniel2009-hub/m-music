# CSS v3 — what changed

Only `static/style.css` was edited. Templates, class names and app logic are untouched
(the smoke test still passes).

## Bugs fixed
- **Dark mode:** featured service card had dark text on dark purple (unreadable); buttons had dark text on dark plum. Now white-on-plum / brass-on-dark with proper contrast.
- **Header:** "Register" button text was overridden by the nav link colour.
- **Services grid:** "Music training" was orphaned on its own row; grid now fills cleanly.
- **Tables:** shrank to content width; now full-width rounded cards. Empty tables are hidden.
- **Background:** gradient banded/cut off on long pages and ignored on iOS; now a fixed glow layer.

## Improvements
- Pill-style nav with active state; header collapses sensibly on phones.
- Real 5-line music staff with note stems; scrolls sideways on phones so labels stay whole.
- Table action buttons (Accept / Verify / Delete…) are pills; status text in tables is a badge.
- Stats as cards, key/value lists with dividers, card hover accent, "See all →" and service-card arrows.
- Native controls follow the colour scheme (date pickers, scrollbars).
- Filter bars flex and wrap properly (admin "Add product" included).
- Flash variants, print styles, reduced-motion support, system-font fallbacks.

## Roles update
The Users and Super admin pages reuse the existing design system. Small additions at the end of style.css: role badges and compact selects inside table rows.

## Update 2: self-rating blocked, star ratings, booked-days calendar

### 1. An artist cannot rate themselves
- The review route (`/provider/<pid>/review`) now rejects any review where the
  reviewer is the profile owner, with a clear flash message.
- On the provider profile, the review form is hidden for the owner and replaced
  with "You can't review your own profile."

### 2. Star ratings (1 to 5)
- The rating input on the provider profile is now a row of 5 clickable stars
  (CSS-only, keyboard-accessible radios), not a dropdown.
- Each existing review displays its stars visually (filled/empty via a gradient
  mask), and the average rating shows as stars at the top of the Reviews section.
- Works in both light and dark themes (brass-gold filled stars).

### 3. Booked-days calendar on the artist's account page (dashboard)
- The artist's dashboard now shows a month calendar of their booked days.
- Each day with a booking is highlighted, with a count badge and clickable
  pills linking to each booking (customer name + status).
- Prev/Next month navigation. Cancelled/declined bookings are excluded.
- The calendar reuses the same month-builder used by the availability calendar.

## Files changed (update 2)
- `app.py` — self-rating guard in `review()`; booked-days calendar data in
  `dashboard()`.
- `templates/provider.html` — star input + star display, owner self-review note.
- `templates/dashboard.html` — booked-days calendar section.
- `static/style.css` — `.stars` display, `.star-input` CSS-only widget,
  `.booked-cal` grid + pills.
