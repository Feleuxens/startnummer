# Workspace design

Use this guide when changing the interface. Keep the photographer's photos and
review decisions easy to inspect, with explicit actions for saves and publishing.

## Surfaces and feedback

Use neutral dark surfaces and locally served Inter. Photos provide most of the
color. Lime marks approved captions and completed work; red marks errors.
Counts come from saved data, and empty accounts show zeros. Use semantic native
controls and the existing styles before adding a UI dependency.

Write action labels that identify their scope. Keep loading, empty, success,
and error states visible near the relevant control. Forms preserve drafts during
status refreshes, and navigation asks before discarding unsaved changes.

## Review layout

Keep the contact sheet, selected photo, and caption evidence together.
Previous/next controls are centered below the image and follow the current filter.
Filename order is the default. Sort changes retain the open photo and its drafts;
navigation and range selection use the same order. Clear checked photos and range
endpoints when changing either the filter or sort.
On narrow screens, a thumbnail opens its detail view; **Back to photos** returns
to the contact sheet.

**Approve this photo** also acknowledges uncertain evidence, affecting only the
open photo. **Approve all eligible** skips unacknowledged uncertainty and previews
every affected photo, including filtered-out ones. Publishing requires its own
preview and confirmation.

## Roster and discipline selection

Roster search matches name, bib, and club, including combined terms. Results show
all three fields. Searching does not save a correction. Keep a pending athlete
selection visible even when a new search would exclude it.

Discipline selection uses contact-sheet checkboxes, Shift-click, and From/Through
controls. Ranges follow the selected sort within the filter; changing filters clears
the selection. Preview caption changes, identify replaced manual disciplines,
and retain manually edited captions. Roster suggestions must leave the full
discipline list available. Keep undetermined discipline distinct from **No event**.

Subject drafts belong to each person, so selecting another face or subject never
discards them. One save applies all corrections atomically. Each subject has a
reversible Exclude/Include control for caption inclusion; keep its evidence and
face index intact. Preserve manually edited captions and offer the regenerated
caption explicitly.

## Temporary face review

Face propagation has its own preview, matching-face highlights, photo selection,
and resulting captions. Keep confirmation controls visible while the list scrolls.
Already-named matches show a status. Eligible matches have checkboxes; tentative
name replacements need confirmation. Protected matches link to individual review.

Session closure or expiry removes the preview and geometry. Caption saves keep
the session; finishing review discards it. Reopening an album retains saved names
and captions without restoring face data.

## Administration

Place **Account**, **Administration**, and **Sign out** at the bottom of the
sidebar with matching widths. Show Administration only to administrators. Use
the same surfaces and typography for status rows, integrations, and numeric limits.

Integration panels start collapsed. Their headers show the configuration source,
state, unsaved changes, and connection errors. Collapsing preserves drafts and
navigation guards. Environment-managed connections have read-only fields and a
test action; editable connections use an explicit save. Never prefill a saved
password. Concurrent edits require a reload.

## Account forms

Setup, sign-in, and registration share the compact login layout. Account creation
includes password confirmation and minimum-length guidance; errors stay near the
form. Invitation links are selectable and copyable, with expiry and revocation
beside the list. Registration policy has an explicit save and an unsaved-change
guard.

Ordinary users start imports with uploads and see no Chevereto controls. Private
workspace state is cleared on session rejection. Keep temporary face data out of
browser storage and screen-opening state.
