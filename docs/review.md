# Review an album

Start with a small album and its competition roster. You will import the inputs,
review the generated captions, and approve the descriptions you want to publish.

To publish to Chevereto, sign in as administrator and [connect the gallery](chevereto.md)
first. Other accounts can upload and review photos in their own workspace.

## 1. Import photos and a roster

Choose **New batch**. Select a Chevereto album or upload JPEG, PNG, or WebP files.
Multi-frame JPEGs (MPO) are supported; Startnummer uses the primary image and
keeps the original file unchanged.

Use original photos; leave out generated `.annotated.jpg` and `.faces.jpg` previews.
Startnummer does not automatically exclude those preview files.

Choose the roster independently: upload Competitoroverview or Resultoverview HTML,
or enter the page's URL. You can combine either roster source with either photo
source. The supported URL source is `ergebnisse.leichtathletik.de` by default.

Use **Resultoverview** when the entry list has no bib numbers. Startnummer reads
the bib field, combines repeated appearances, and collects the listed disciplines.
Relay members without individual bibs remain available without invented numbers.
Results cover people listed in the published results; some entered athletes may
be absent. The importer uses only the page you select and does not fetch or merge
the other overview automatically.

Enter an album name and, if you want it in captions, a meet name. Choose **Import
and preview**. Check the saved photo count and roster sample before continuing.
The roster parser leaves the meet name blank, so supply it yourself if needed.

Uploading a photo does not link it to a gallery image. Import from a Chevereto
album when you want to update that album's existing descriptions.

## 2. Analyze the batch

Choose **Analyze batch**. Progress appears above the photos, and failed photos
remain available for review. The worker analyzes the saved inputs; changing the
source page does not change this batch.

**Cancel analysis** keeps saved review work and prevents the job from saving more
results. An active model call may finish before processing stops.

## 3. Review a photo

Open a thumbnail and compare its existing description, caption suggestion, and
evidence. Correct names, bibs, clubs, or disciplines, then save your changes.
Previous/next buttons below the image follow the current filter and stop at each
end. Leaving unsaved edits requires confirmation.

Use **No event** when the caption should omit a discipline. An undetermined
discipline means it has not yet been identified. Captions use the existing German
and English discipline names; Startnummer does not invent new disciplines.

### Assign a person from the roster

Select a face or subject, then use **Search roster athletes**. Search by name,
bib, club, or a combination of terms. Each result shows all three fields.
Choose an athlete under **Assign roster athlete** and save the correction.
Searching or pressing Enter alone does not save an assignment.

You can also give a detected face a name that is absent from the roster.
A visible bib is not required.

If the person was not detected, choose **Add person from roster**, select the
athlete, and choose **Add to this photo**. This generates a caption suggestion
without adding detection evidence and also works before analysis. Use **Remove
added person** to reverse an accidental addition.

### Correct a sequence of disciplines

1. Choose **Select photos**.
2. Check photos individually, Shift-click to extend a selection, or set **From
   photo** and **Through photo**, then choose **Select range**.
3. Choose **Assign discipline…** and select a discipline.
4. Preview the caption changes and confirm.

Ranges follow album order within the current filter. Changing the filter clears
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
