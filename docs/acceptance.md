# Photographer acceptance

Use a disposable Chevereto 4.5.9 instance. The local test gallery is
`http://localhost:8115`. Run migrations and start the API and worker as described
in the README. Finish active face review before restarting an updated worker;
restarting it clears temporary face data.

## Full-album pass

The photographer has tested a complete album. Missing disciplines required the
most manual correction; range assignment now supports those sequences. Results
for the individual checks below have not been recorded. Automated tests use
synthetic inputs and fake models.

- [ ] Import the representative album and `test-pictures/entrytable.html`. Check
      exact album membership, the expected 93 originals, and 262 roster entries.
      Exclude generated `.annotated.jpg` and `.faces.jpg` files if uploading.
- [ ] Supply a meet name, analyze, and inspect failures and uncertain evidence.
      Record any incorrect bibs, identities, or disciplines separately from app bugs.
- [ ] Correct a bib, choose a roster athlete, enter a name absent from the roster,
      choose **No event**, and edit a caption. Check each generated caption.
- [ ] Select a face and search the roster by bib, name, club, and combined terms.
      Choose a result and save. Searching alone leaves the saved identity unchanged;
      changing the search keeps a pending selection visible until it is saved.
- [ ] On a photo without detected subjects, use **Add person from roster** and
      check the generated caption, including a roster entry without a bib.
      Remove an accidental addition and verify that other people remain unchanged.
- [ ] Save a face name and open **Find matching faces…**. Inspect the highlighted
      people, exclude wrong matches, and confirm selected occurrences. Check that
      manual identities, bib corrections, captions, and disciplines are preserved.
      Undo the last assignment, check the restored names/captions, then apply again.
- [ ] A bib read absent from the roster appears as a warning and requires explicit
      confirmation before assigning a name to that matching face. The read remains
      visible, approval is removed, and genuine roster/manual conflicts stay blocked.
- [ ] Already-named matches show a status rather than a disabled checkbox. A
      tentative name guess can be selected and replaced after confirming the
      warning. A different confirmed name stays protected; **Review this photo**
      opens it for an individual correction.
- [ ] An incompatible worker session explains why propagation is unavailable
      while individual face naming remains usable. Restart the updated processes
      and analyze a fresh batch to create a compatible session.
- [ ] Approve one photo and confirm that other photos remain unapproved. Exercise
      bulk approval, unapproval, filters, and previous/next navigation.
- [ ] Filter undetermined disciplines, select a sequence using Shift-click or the
      range controls, and exclude an individual photo. Changing filters clears
      selection. Explicit No event photos stay out of the undetermined filter.
- [ ] Assign a discipline absent from the roster. Preview captions, including a
      manually edited caption and an existing manual discipline, before confirming.
      Edited captions are kept; changed photos lose approval. A stale revision
      rejects the entire selection. Check the range controls on a narrow screen.
- [ ] Finish the face session and reopen the batch. Names and captions must remain;
      face selection and propagation must be unavailable. A worker restart must
      have the same effect on temporary face data without losing saved review work.
- [ ] Preview and apply a small approved selection to the local gallery. Compare
      the rendered image pages, then conditionally restore the original descriptions.
- [ ] Change a local gallery description outside Startnummer. Check that Apply
      reports a conflict. Load the live value, review replacement consent, approve
      again, and retry. Verify that unrelated descriptions remain unchanged.

## Operations checks

- [ ] After finishing face review and stopping manually started services, migrate
      and start the launcher. Check readiness, model loading, and status. Occupied
      ports must leave the existing service alone.
- [ ] Open Administration with the configured account. Save import limits and a
      session lifetime, then reopen the page. Existing face sessions retain their
      expiry; new sessions use the saved lifetime.
- [ ] Create and verify a backup while the app is running. Restore it into an empty
      database and photo directory, then reopen saved review work. Names, captions,
      approvals, gallery mappings, and publishing history must remain. Temporary
      face data must be absent, and unfinished jobs must be cancelled.
- [ ] Stop the launcher after review. It must stop only managed processes and let
      an active job finish. Saved batches must reopen after a fresh launch.

## Automated coverage

| Area        | Checks                                                                                                                                                                                       |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Imports     | Four source pairings, URL/upload roster equivalence, byte limits, distinct photo IDs for duplicate bytes, recoverable cleanup                                                                |
| Jobs        | Lease expiry and bounded retries, cancellation fencing, immediate approval invalidation, saved review preservation                                                                           |
| Sessions    | Owner isolation, expiry, finish, stale worker generations, authenticated worker transport, no durable geometry/groups/embeddings                                                             |
| Propagation | Bibless matches, candidate exclusions, tentative-name confirmation, already-named matches, stale revisions, protected manual decisions, saved captions, renewed approvals, session-only undo |
| Publishing  | Exact conditional SQL, partial outcomes, interrupted-write reconciliation, stale descriptions, renewed replacement consent, conditional restore                                              |
| Scale       | Synthetic 93-photo batch and 262-entry roster, with worker lease recovery and saved review reopening                                                                                         |
| Review      | Discipline ranges, roster suggestions and overrides, manual captions, approval invalidation, atomic rejection of stale selections, roster search by bib/name/club                            |
| Startup     | Managed subprocess start/stop, worker restart without API restart, occupied ports, stale PID refusal, worker credential separation                                                           |
| Backups     | Shared blobs, checksum and path validation, temporary face-data rejection, PostgreSQL consistency with continuing heartbeats, empty destinations, cancelled jobs, uncertain commits          |
| Settings    | Authentication, ownership, revision checks, import limits, new-session lifetime without changing existing expiry                                                                             |
| Browser     | Desktop/mobile review, propagation and administration, individual/bulk approval scope, navigation, publishing-conflict recovery                                                              |

PostgreSQL tests use random schemas. MariaDB tests use a separate
`startnummer_test_*` database. Neither test suite uses the real photo folder or a
production gallery.

## Backlog alignment

| Issues      | Implementation and remaining work                                                                                                                                                                       |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| #1          | Description preview, apply, reconciliation, conflict refresh, and restore are implemented. Rendered-page checks are listed above.                                                                       |
| #3, #12     | Saved batches, versioned analysis, stable photo IDs, shared blobs, and cleanup are implemented.                                                                                                         |
| #5, #6, #15 | Generated client and the four import pairings are implemented. Import displays a busy state; byte-level upload progress and resumable uploads remain separate work.                                     |
| #7, #8, #18 | Review, corrections, approvals, filters, roster search, bulk discipline assignment, and session finish are implemented. Cross-album person erasure is deferred.                                         |
| #9          | Confirmed within-batch face-name propagation is implemented. Match groups exist only for the active session.                                                                                            |
| #10         | Local batch deletion is implemented. Cross-album identity discovery remains deferred.                                                                                                                   |
| #11, #16    | Durable jobs, leases, progress, cancellation, and bounded recovery are implemented for one worker.                                                                                                      |
| #14         | Authentication, ownership, configuration, and OpenAPI are implemented. The API uses synchronous SQLAlchemy sessions in threadpool handlers, rather than the issue's originally proposed async sessions. |
| #2, #17     | A standalone JSON storage backend and external analysis import remain deferred. The app stores JSON documents in PostgreSQL.                                                                            |

Face embeddings are released after analysis. Face boxes, match groups, and undo
records remain in worker memory for the active review session. Finishing review,
cancellation, expiry, sign-out, deletion, or worker shutdown clears them. Saved
names and captions remain available when a batch is reopened. There is no
permanent identity gallery.
