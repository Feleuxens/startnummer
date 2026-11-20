# Review an album

Start with a small album and a competition roster if available. You will import the inputs,
review the generated captions, and approve the descriptions you want to publish.

To publish to Chevereto, sign in as administrator and [connect the gallery](chevereto.md)
first. Other accounts can upload and review photos in their own workspace.

## 1. Import photos

Choose **New batch**. Select a Chevereto album or upload JPEG, PNG, or WebP files.
Multi-frame JPEGs (MPO) are supported; Startnummer uses the primary image and
keeps the original file unchanged.

Use original photos; leave out generated `.annotated.jpg` and `.faces.jpg` previews.
Startnummer does not automatically exclude those preview files.

Choose the roster independently: upload Competitoroverview or Resultoverview HTML,
or enter the page's URL. You can combine either roster source with either photo
source. The supported URL source is `ergebnisse.leichtathletik.de` by default.

If you have no official list, choose **No roster**. Analysis still detects people,
reads visible bibs, and groups matching faces. Give a detected person a **Name**
and optional club during review, save, then use **Find matching faces…** to assign
that identity to other photos. Names must be entered manually, and there are no
roster-based discipline suggestions. You can still choose any supported discipline.

Use **Resultoverview** when the entry list has no bib numbers. Startnummer reads
the bib field, combines repeated appearances, and collects the listed disciplines.
Relay members without individual bibs remain available without invented numbers.
Results cover people listed in the published results; some entered athletes may
be absent. The importer uses only the page you select and does not fetch or merge
the other overview automatically.

### Check roster names before importing

**Name order** defaults to **Auto**, which checks each name separately. Commas
and uppercase surname blocks identify the order. An abbreviated surname stays
abbreviated: `Alex K.` remains `Alex K.`. Uppercase name parts are normalized:
`EXAMPLE` becomes `Example`, and `VAN EXAMPLE` becomes `van Example`. Hyphens,
apostrophes, accents, initials, and existing mixed-case spellings are kept.
The preview retains the original source text; check unusual spellings and correct
them if needed. Your manual name corrections are saved as entered.
Mixed-case names without clear evidence assume surname first and are marked
for review; compound surname particles such as `van` and `de` stay together.

Choose **Surname first**, **Given name first**, or **Keep source order** to override
automatic detection. Choose **Preview roster names** to compare source and parsed
names, search the list, and edit individual names. The preview shows twenty entries
at a time. **Only uncertain automatic names** filters the original uncertain
choices and keeps corrected rows visible while you edit them.

Name corrections are saved when you import. Changing the source or format clears
the preview; changing the format asks before discarding name corrections. If a
URL's roster changes after the preview, import stops: preview it again before
retrying. Existing saved albums keep their names and captions.

Enter an album name and, if you want it in captions, a meet name. Choose **Import
and preview**. Check the saved photo count and roster sample before continuing.
The roster parser leaves the meet name blank, so supply it yourself if needed.

Uploading a photo does not link it to a gallery image. Import from a Chevereto
album when you want to update that album's existing descriptions.

### Edit album settings

Open a saved album and choose **Edit album…** to change the **Album name** or
**Meet name**. The meet name is optional and appears in generated captions.
Editing it refreshes the affected caption suggestions, including when analysis
is already running. Review changed suggestions before approving them again.

## 2. Analyze the batch

Choose **Analyze batch**. Progress appears above the photos, and failed photos
remain available for review. The worker analyzes the saved inputs; changing the
source page does not change this batch.

**Cancel analysis** keeps saved review work and prevents the job from saving more
results. An active model call may finish before processing stops.

## 3. Review a photo

Open a thumbnail and compare its existing description, caption suggestion, and
evidence. Correct names, bibs, clubs, or disciplines, then save your changes.
Switch between faces or subjects to edit several people before saving. Pending
corrections stay with each person; **Save caption and corrections** saves them
together.
Identity fields open directly below the selected person's row. Save and
Approve/Unapprove stay at the bottom of the screen while you scroll.
Previous/next buttons below the image follow the current filter and stop at each
end. Leaving unsaved edits requires confirmation.

Photos start in natural filename order: `IMG_2.jpg` precedes `IMG_10.jpg`.
Use **Sort by** to choose **File modified date**, **Date taken / EXIF**, or **Import order**.
Dates sort oldest first; missing dates go last and filenames break ties.
Navigation and selection ranges follow the chosen order. Changing the sort clears
checked photos and range endpoints while keeping the open photo and its edits.

**File modified date** is recorded from browser uploads or the gallery original's
HTTP `Last-Modified` header. Older imports may lack that date; Startnummer does
not substitute the storage copy's timestamp. **Date taken / EXIF** uses the
camera's `DateTimeOriginal`, including subseconds, without correcting camera
clocks or guessing time zones. Selecting EXIF order in an older album reads its
saved originals once and caches the dates; it does not rerun analysis or discard
a face session.

Use **No event** when the caption should omit a discipline. An undetermined
discipline means it has not yet been identified. Captions use the existing German
and English discipline names; Startnummer does not invent new disciplines.

### Assign a person from the roster

Select a face or subject, then use **Search roster athletes**. Search by name,
bib, club, or a combination of terms. Each result shows all three fields.
Choose an athlete under **Assign roster athlete** and save the correction.
Searching or pressing Enter alone does not save an assignment.
Entries without bib numbers are available too; choose them by name and club.

You can also give a detected face a name that is absent from the roster, or work
without a roster entirely.
A visible bib is not required.

### Add someone who was missed by detection

Choose **Add person from roster** to select an athlete, or **Add person manually**
to enter a name and an optional bib and club. Choose **Add to this photo**.
This works before analysis and in albums without a roster.

The entry generates a caption suggestion and belongs to this photo. It has no
detected face to use for propagation. Select its row to make corrections or
choose **Remove added person** to undo the addition.

### Override a name in captions

For one album, choose **Edit album…** and add a rule under **Caption name
overrides**. When you spot a name during review, open that person's row and
choose **Override name for this album…** to fill in its source name. Enter the
replacement under **Name in captions**, then choose **Save album settings**.

Album rules take priority over account rules for the same source name. Saving
refreshes affected suggestions across the album without rerunning analysis.
For a manually edited caption, choose **Use generated caption** to adopt the
new suggestion. Approve changed suggestions again before applying them.

For a name you want to use across albums, use an account rule.
Open **Account → Caption name overrides**, choose **Add name override**, and enter
the **Full source name** shown in the roster or subject evidence. Enter the
replacement under **Name in captions**, then choose **Save name overrides**.

Rules are private to your account and reusable across albums. They match the full
name, ignoring capitalization and extra spaces. They do not match parts of a name
or chain replacements. Your replacement is used as entered, including its casing.
Roster names, bibs, matching, and face propagation identities stay unchanged.

New caption suggestions use these rules. Saving a rule leaves existing captions
and approvals alone. To update an existing photo, save its current edits and choose
**Refresh caption suggestion**. Generated captions update directly; manually edited
captions are kept, with the new **Analysis suggestion** available for comparison.
Choose **Use generated caption** and save when you want to replace manual text.
Changed suggestions remove approval and need review again. No analysis rerun is
needed, and the active face session remains available.

Removing a rule affects future generation. Refresh a photo's suggestion to return
to its matched name. Name overrides are included in your account's backups.

### Leave background people out of the caption

Choose **Exclude** beside a person, then save the corrections. **Include** reverses
the choice. The person and their evidence stay available for review; only their
caption inclusion changes. The choice is specific to this photo and survives
reopening and analysis reruns.

Generated captions use the included people. A manually edited caption is kept;
after saving, **Analysis suggestion** shows the updated generated text. Choose
**Use generated caption** and save to replace your text and resume automatic
caption generation. Excluding every named person leaves the generated caption
empty, so it cannot be approved.

### Correct a sequence of disciplines

1. Choose **Select photos**.
2. Check photos individually, Shift-click to extend a selection, or set **From
   photo** and **Through photo**, then choose **Select range**.
3. Choose **Assign discipline…** and select a discipline.
4. Preview the caption changes and confirm.

Ranges follow the current sort order within the filter. Changing either clears
the selection. **Undetermined discipline** excludes photos marked **No event**.
Roster events are suggestions; you can choose any supported discipline.

The preview identifies manual disciplines that will be replaced. Manually edited
captions are kept, and changed photos need approval again. If any selected photo
changed after the preview, reload and preview the whole selection again.

### Find the same person in other photos

After saving an identity, select the subject and choose **Find matching faces…**.
Review the candidate photos and resulting captions, exclude wrong matches, and
confirm the selection.

| Candidate                      | What you can do                                       |
| ------------------------------ | ----------------------------------------------------- |
| Eligible match                 | Check it to assign the saved identity.                |
| Already named                  | The selected name is already assigned.                |
| Tentative name                 | Confirm the replacement warning before assigning.     |
| Protected identity or conflict | Use **Review this photo** to inspect it individually. |

Manual identities, bib corrections, and genuine roster conflicts are protected.
Warnings about unsupported machine-read bibs require acknowledgement; that does
not override protected corrections. Edited captions and manual disciplines are
kept, and changed photos lose approval.

**Undo last name assignment** reverses the latest propagation during this face
session. It cannot overwrite later edits, restore approval, or undo gallery writes.

## 4. Approve reviewed captions

Save edits first, then choose **Approve this photo**. Approval also confirms that
you have reviewed any uncertain evidence in that photo. Warnings remain visible.
**Unapprove this photo** removes approval while keeping the caption and evidence.

For several captions, use **Approve all eligible**. Its confirmation lists the
photos it affects, including any hidden by the current filter. Blank captions
and photos with unacknowledged uncertainty are excluded; approve those individually
after review. Replacing a nonempty gallery description requires explicit consent.
Edits and analysis reruns remove approval.

## 5. Apply descriptions to Chevereto

Choose **Preview Apply**, inspect the before/after descriptions, then choose
**Apply to Chevereto**. Only approved, mapped photos can be published. Publication
history records an outcome for each photo.

If someone changed a gallery description since import, Startnummer reports a
conflict. Choose **Load live description for review**, review the refreshed value,
choose replacement if intended, and approve again.

After an interrupted or uncertain write, use **Check gallery outcome** before
retrying. This reads the live value without writing. **Restore previous
description** succeeds only while the gallery still contains what Startnummer
wrote. The publishing filters show the latest operation for each photo.

## 6. Finish face review

Save the current photo's edits, then choose **Save review and finish face session**.
Your photos, assigned names, reviewed captions, and publishing history remain
available under **Saved albums**. Extracted face data and propagation undo are
removed.

Face sessions also end on expiry, cancellation, batch deletion, sign-out, password
change, session revocation, or worker shutdown. Ordinary caption saves keep the
session available until then. The default lifetime is one hour.

If you analyze again, manual captions, identities, and disciplines are retained. Those
retained subject layouts do not receive new face selectors. Use a fresh batch
when you need new face matching without those retained layouts.
