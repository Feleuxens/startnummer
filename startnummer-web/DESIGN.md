# Workspace design

Use neutral dark surfaces so the photos carry most of the color. Inter is served
locally. Lime marks approved captions and completed work; errors use red.

The review screen keeps the contact sheet, selected photo, and caption evidence
together. Previous/next controls sit centered below the image and follow the
current filter. At narrow widths, selecting a thumbnail opens its detail view;
**Back to photos** returns to the contact sheet.

Action labels state their scope. **Approve this photo** and its evidence checkbox
affect the open photo. **Approve all eligible** requires confirmation and lists
the affected photos, including those hidden by a filter. Applying descriptions
is a separate preview and confirmation step.

Discipline assignment uses a separate checkbox selection in the contact sheet.
Support Shift-click and From/Through controls for touch and keyboard use.
Ranges follow the current filter in album order; changing filters clears selection.
Preview caption changes before confirming, identify replaced manual disciplines,
and keep manually edited captions. Roster suggestions never restrict the full
discipline list. Undetermined discipline and explicit No event remain distinct.

Face-name propagation has its own preview with highlighted matching faces, per-photo
selection, and the resulting captions. Keep the confirmation controls visible while
the list scrolls. Expiry or session closure removes this preview and its geometry.
Show already-named matches as a status. Only eligible matches have checkboxes;
tentative name replacements require confirmation. Protected matches link to review.

Saving a caption keeps face selection available during review. Finishing review
discards the face session. Reopened albums retain saved captions and names.

Roster selection supports searches by name, bib, and club, including combined
terms. Results show all three fields. Search alone does not change review state;
a pending athlete selection remains visible if the search changes.

Counts come from saved batches, jobs, and approvals. Empty accounts show zeros.
Photos are fetched through authenticated endpoints; test-gallery images are not
frontend assets. Browser tests use synthetic images.

Administration uses the same surfaces and typography, with service-status
rows, configured integrations, and labeled numeric settings. Its navigation link
sits above Sign out at the bottom of the sidebar. Saving is explicit. Polling status preserves
unsaved inputs; concurrent settings edits require reloading the saved values.
The configured account is the administrator. Chevereto connections managed by the
environment show read-only fields and a connection test. Otherwise, an explicit
form saves the encrypted connection. Never prefill an existing password. Status
polling preserves connection drafts; stale saves require a reload. Dirty connection
and runtime-settings forms both guard navigation. Startnummer's own database,
application secrets, and storage paths remain server configuration.

Each integration uses a collapsed disclosure under Configured integrations. Its
header shows the name, configuration source, and state. Expanding reveals the
settings and actions. Collapsing keeps drafts and navigation guards intact;
unsaved changes and connection errors remain visible in the header.
