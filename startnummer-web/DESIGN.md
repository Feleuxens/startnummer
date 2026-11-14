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

Face-name propagation has its own preview with highlighted matching faces, per-photo
selection, and the resulting captions. Keep the confirmation controls visible while
the list scrolls. Expiry or session closure removes this preview and its geometry.
Show already-named matches as a status. Only eligible matches have checkboxes;
tentative name replacements require confirmation. Protected matches link to review.

Saving a caption keeps face selection available during review. Finishing review
discards the face session. Reopened albums retain saved captions and names.

Counts come from saved batches, jobs, and approvals. Empty accounts show zeros.
Photos are fetched through authenticated endpoints; test-gallery images are not
frontend assets. Browser tests use synthetic images.
