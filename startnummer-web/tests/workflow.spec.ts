import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import type { components } from '../src/api/schema';

const html = `<html><div class="entryline"><div></div><div>12</div><div></div><div>Example Alex</div><div>Example Club</div><div></div><div></div><div>2000</div><div><a>100</a></div></div></html>`;

async function login(page: Page) {
  await page.goto('/');
  await page.getByLabel('Password', { exact: true }).fill('browser-test-only');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Saved albums', exact: true })).toBeVisible();
}

test('import, analyze, name an individual face, save, reopen, approve, apply, and restore', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await login(page);
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Album URL', { exact: true }).fill('http://gallery.test/album/a');
  await page
    .getByLabel('Competitoroverview HTML')
    .setInputFiles({ name: 'roster.html', mimeType: 'text/html', buffer: Buffer.from(html) });
  await page.getByLabel('Album name', { exact: true }).fill('Browser acceptance');
  await page.getByLabel('Meet name', { exact: true }).fill('Synthetic Meet');
  await page.getByRole('button', { name: 'Import and preview' }).click();
  await expect(page.getByRole('heading', { name: 'Ready to analyze' })).toBeVisible();
  await expect(page.getByText('2 photos · 1 roster entries · 0 approved')).toBeVisible();
  await page.getByRole('button', { name: 'Analyze batch', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Name detected face 1' })).toBeVisible({
    timeout: 15000,
  });
  await page.getByRole('button', { name: 'Name detected face 1' }).click();
  await page.getByLabel('Or enter a name').fill('Taylor Visitor');
  await page.getByRole('button', { name: 'Save caption and corrections' }).click();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue('Taylor Visitor | Synthetic Meet');
  await page.getByLabel('I reviewed and resolved uncertain evidence in this photo').check();
  await page.getByRole('button', { name: 'Save caption and corrections' }).click();
  await page.getByRole('button', { name: 'Approve this photo', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Unapprove this photo', exact: true }),
  ).toBeVisible();
  await page
    .getByRole('button', { name: 'Save review and finish face session', exact: true })
    .click();
  await expect(
    page.getByText('Review saved. Extracted face data has been discarded.'),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Name detected face 1' })).toHaveCount(0);
  await page.reload();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue('Taylor Visitor | Synthetic Meet');
  await expect(page.getByRole('button', { name: 'Name detected face 1' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Preview Apply', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Taylor Visitor | Synthetic Meet');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Preview Apply', exact: true }).click();
  await page.getByRole('button', { name: 'Apply to Chevereto', exact: true }).click();
  await expect(
    page.getByText('1 captions applied or unchanged; 0 conflicts or failures.'),
  ).toBeVisible();
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Restore previous description' }).click();
  await expect(page.getByText('Previous description restored.')).toBeVisible();
  expect(errors).toEqual([]);
});

test('mobile import and navigation stay within the viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Supported URL', { exact: true }).check();
  await page.getByLabel('Roster URL', { exact: true }).fill('https://roster.test/overview');
  await page.getByLabel('Album URL', { exact: true }).fill('http://gallery.test/album/a');
  await page.getByLabel('Album name', { exact: true }).fill('Mobile batch');
  await page.getByRole('button', { name: 'Import and preview' }).click();
  await expect(page.getByRole('heading', { name: 'Ready to analyze' })).toBeVisible();
  await page.getByRole('button', { name: 'same.jpg' }).first().click();
  await expect(page.getByRole('button', { name: 'Back to photos' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Previous photo', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Next photo', exact: true }).click();
  await expect(page.getByLabel('Photo 2 of 2 in album')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Next photo', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Previous photo', exact: true }).click();
  await expect(page.getByLabel('Photo 1 of 2 in album')).toBeVisible();
  await page.getByRole('button', { name: 'Back to photos' }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});

test('review and approval affect one photo; approve all requires explicit confirmation', async ({
  page,
}) => {
  await login(page);
  // Reuse synthetic image bytes from the fixture gallery, never real photos.
  const seed = await page.request.post('/api/batches', {
    headers: { 'X-Requested-With': 'Startnummer' },
    multipart: {
      gallery_url: 'http://gallery.test/album/a',
      roster_file: { name: 'roster.html', mimeType: 'text/html', buffer: Buffer.from(html) },
    },
  });
  expect(seed.ok()).toBe(true);
  const imageId = (await seed.json()).photos[0].id;
  const image = await page.request.get(`/api/photos/${imageId}`);
  const bytes = await image.body();
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Upload images', { exact: true }).check();
  await page.getByLabel('Image files').setInputFiles(
    [1, 2, 3, 4].map((index) => ({
      name: `original-${index}.jpg`,
      mimeType: 'image/jpeg',
      buffer: bytes,
    })),
  );
  await page
    .getByLabel('Competitoroverview HTML')
    .setInputFiles({ name: 'roster.html', mimeType: 'text/html', buffer: Buffer.from(html) });
  await page.getByLabel('Album name', { exact: true }).fill('Four-photo approval scope');
  await page.getByRole('button', { name: 'Import and preview' }).click();
  await page.getByRole('button', { name: 'Analyze batch', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Approve this photo', exact: true })).toBeEnabled({
    timeout: 15000,
  });
  const batchId = new URL(page.url()).hash.split('/')[1];
  const readBatch = async () =>
    (await (await page.request.get(`/api/batches/${batchId}`)).json()).batch;
  const sentCounts: number[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith(`/batches/${batchId}/approve`)) {
      sentCounts.push(request.postDataJSON().photos.length);
    }
  });

  await page.getByLabel('I reviewed and resolved uncertain evidence in this photo').check();
  await page.getByRole('button', { name: 'Save caption and corrections' }).click();
  await expect(
    page.getByRole('status').filter({ hasText: 'Changes saved for original-1.jpg.' }),
  ).toBeVisible();
  const saved = await readBatch();
  expect(
    saved.photos.map((photo: { conflicts_resolved: boolean }) => photo.conflicts_resolved),
  ).toEqual([true, false, false, false]);
  expect(
    saved.photos.every(
      (photo: { approved_revision: number | null }) => photo.approved_revision === null,
    ),
  ).toBe(true);

  await page.getByRole('button', { name: 'Approve this photo', exact: true }).click();
  await expect(
    page.getByText('4 photos · 1 roster entries · 1 approved', { exact: true }),
  ).toBeVisible();
  const individuallyApproved = await readBatch();
  expect(
    individuallyApproved.photos.map(
      (photo: { approved_revision: number | null; revision: number }) =>
        photo.approved_revision === photo.revision,
    ),
  ).toEqual([true, false, false, false]);
  expect(sentCounts).toEqual([1]);

  // Bulk approval covers the whole album, even when its eligible photos are
  // hidden by the filter. The confirmation must say so and name the targets.
  await page.getByRole('combobox', { name: 'Show' }).selectOption('approved');
  const approveAll = page.getByRole('button', { name: 'Approve all eligible (3)…', exact: true });
  await approveAll.click();
  const dialog = page.getByRole('dialog', { name: 'Approve all eligible captions?' });
  await expect(dialog).toContainText('3 photos in Four-photo approval scope');
  await expect(dialog).toContainText('including photos hidden by the current filter');
  await expect(dialog.getByRole('heading', { name: 'original-1.jpg', exact: true })).toHaveCount(0);
  for (const index of [2, 3, 4]) {
    await expect(
      dialog.getByRole('heading', { name: `original-${index}.jpg`, exact: true }),
    ).toBeVisible();
  }
  await dialog.screenshot({ path: test.info().outputPath('bulk-approval-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await dialog.screenshot({ path: test.info().outputPath('bulk-approval-mobile.png') });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(sentCounts).toEqual([1]);
  await approveAll.click();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  expect(sentCounts).toEqual([1]);
  await approveAll.click();
  await dialog.getByRole('button', { name: 'Approve 3 captions', exact: true }).click();
  await expect(
    page.getByText('4 photos · 1 roster entries · 4 approved', { exact: true }),
  ).toBeVisible();
  expect(sentCounts).toEqual([1, 3]);
  const allApproved = await readBatch();
  expect(
    allApproved.photos.every(
      (photo: { approved_revision: number | null; revision: number }) =>
        photo.approved_revision === photo.revision,
    ),
  ).toBe(true);
  await expect(
    page.getByRole('button', { name: 'Approve all eligible (0)…', exact: true }),
  ).toBeDisabled();
});

test('unapprove one photo and navigate without losing unsaved edits', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Album URL', { exact: true }).fill('http://gallery.test/album/a');
  await page
    .getByLabel('Competitoroverview HTML')
    .setInputFiles({ name: 'roster.html', mimeType: 'text/html', buffer: Buffer.from(html) });
  await page.getByLabel('Album name', { exact: true }).fill('Photo navigation');
  await page.getByRole('button', { name: 'Import and preview' }).click();
  await page.getByRole('button', { name: 'Analyze batch', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Approve this photo', exact: true })).toBeEnabled({
    timeout: 15000,
  });
  const batchId = new URL(page.url()).hash.split('/')[1];
  const readBatch = async () =>
    (await (await page.request.get(`/api/batches/${batchId}`)).json()).batch;
  const initial = await readBatch();
  const caption = initial.photos[0].caption;
  await expect(page.getByRole('button', { name: 'Previous photo', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Approve this photo', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Unapprove this photo', exact: true }),
  ).toBeEnabled();
  await page.getByRole('button', { name: 'Next photo', exact: true }).click();
  await expect(page.getByLabel('Photo 2 of 2 in album')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Next photo', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Approve this photo', exact: true }).click();
  await expect(
    page.getByText('2 photos · 1 roster entries · 2 approved', { exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Previous photo', exact: true }).click();
  await page.getByLabel('Reviewed caption').fill('Unsaved draft for first photo');
  await page.getByRole('button', { name: 'Unapprove this photo', exact: true }).click();
  await expect(
    page.getByText('2 photos · 1 roster entries · 1 approved', { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue('Unsaved draft for first photo');
  const revoked = await readBatch();
  expect(revoked.photos[0].approved_revision).toBeNull();
  expect(revoked.photos[0].caption).toBe(caption);
  expect(revoked.photos[0].analysis).toEqual(initial.photos[0].analysis);
  expect(revoked.photos[1].approved_revision).toBe(revoked.photos[1].revision);

  // Cancelling a navigation keeps both the selected photo and its draft.
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: 'Next photo', exact: true }).click();
  await expect(page.getByLabel('Photo 1 of 2 in album')).toBeVisible();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue('Unsaved draft for first photo');
  // Confirming discards only the unsaved draft; saved captions are retained.
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Next photo', exact: true }).click();
  await expect(page.getByLabel('Photo 2 of 2 in album')).toBeVisible();
  await page.getByRole('button', { name: 'Previous photo', exact: true }).click();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue(caption);

  // The only approved photo is the second one, so it is the only next target.
  await page.getByRole('combobox', { name: 'Show' }).selectOption('approved');
  await page.getByRole('button', { name: 'Next photo', exact: true }).click();
  await expect(page.getByLabel('Photo 2 of 2 in album')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Previous photo', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Next photo', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Unapprove this photo', exact: true }).click();
  await expect(
    page.getByText('2 photos · 1 roster entries · 0 approved', { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Preview Apply', exact: true })).toBeDisabled();
  expect(
    (await readBatch()).photos.every(
      (photo: { approved_revision: number | null }) => photo.approved_revision === null,
    ),
  ).toBe(true);
});

test('preview matching faces, exclude a photo, preserve captions, and finish the session', async ({
  page,
}) => {
  await login(page);
  const seed = await page.request.post('/api/batches', {
    headers: { 'X-Requested-With': 'Startnummer' },
    multipart: {
      gallery_url: 'http://gallery.test/album/a',
      roster_file: { name: 'roster.html', mimeType: 'text/html', buffer: Buffer.from(html) },
    },
  });
  const imageId = (await seed.json()).photos[0].id;
  const bytes = await (await page.request.get(`/api/photos/${imageId}`)).body();
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Upload images', { exact: true }).check();
  await page.getByLabel('Image files').setInputFiles(
    [1, 2, 3].map((index) => ({
      name: `match-${index}.jpg`,
      mimeType: 'image/jpeg',
      buffer: bytes,
    })),
  );
  await page.getByLabel('Competitoroverview HTML').setInputFiles({
    name: 'roster.html',
    mimeType: 'text/html',
    buffer: Buffer.from(html.replace('<div>12</div>', '<div>99</div>')),
  });
  await page.getByLabel('Album name', { exact: true }).fill('Face propagation');
  await page.getByRole('button', { name: 'Import and preview' }).click();
  await page.getByRole('button', { name: 'Analyze batch', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Name detected face 1' })).toBeVisible({
    timeout: 15000,
  });
  await page.getByRole('button', { name: 'Next photo', exact: true }).click();
  await page.getByLabel('Reviewed caption').fill('Keep my edited caption');
  await page.getByRole('button', { name: 'Save caption and corrections' }).click();
  await expect(
    page.getByRole('status').filter({ hasText: 'Changes saved for match-2.jpg.' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Previous photo', exact: true }).click();
  await page.getByRole('button', { name: 'Name detected face 1' }).click();
  await page.getByLabel('Or enter a name').fill('Taylor Visitor');
  await expect(page.getByRole('button', { name: 'Find matching faces…' })).toBeDisabled();
  await page.getByRole('button', { name: 'Save caption and corrections' }).click();
  await page.getByRole('button', { name: 'Find matching faces…' }).click();
  const dialog = page.getByRole('dialog', { name: 'Assign Taylor Visitor to matching faces?' });
  await expect(dialog).toContainText('Keep my edited caption');
  await expect(
    dialog.getByRole('button', { name: 'Assign name to 2 selected photos' }),
  ).toBeDisabled();
  const acknowledgement = dialog.getByLabel(
    'I checked the selected faces and proposed changes despite the warnings',
  );
  await expect(dialog).toContainText('Bib read 12 is not in the saved roster');
  await acknowledgement.check();
  await expect(
    dialog.getByRole('button', { name: 'Assign name to 2 selected photos' }),
  ).toBeEnabled();
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  const batchId = new URL(page.url()).hash.split('/')[1];
  const readBatch = async () =>
    (await (await page.request.get(`/api/batches/${batchId}`)).json()).batch;
  expect((await readBatch()).photos[1].analysis.record.subjects[0].athlete).toBeNull();
  await page.getByRole('button', { name: 'Find matching faces…' }).click();
  await expect(acknowledgement).not.toBeChecked();
  await acknowledgement.check();
  await dialog.getByRole('checkbox', { name: 'match-3.jpg · person 1' }).uncheck();
  await expect(acknowledgement).not.toBeChecked();
  await expect(
    dialog.getByRole('button', { name: 'Assign name to 1 selected photo' }),
  ).toBeDisabled();
  await dialog.screenshot({ path: test.info().outputPath('face-propagation-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await dialog.screenshot({ path: test.info().outputPath('face-propagation-mobile.png') });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await acknowledgement.check();
  await dialog.getByRole('button', { name: 'Assign name to 1 selected photo' }).click();
  await expect(dialog).toHaveCount(0);
  const saved = await readBatch();
  expect(saved.photos[1].analysis.record.subjects[0].athlete.value.name).toBe('Taylor Visitor');
  expect(saved.photos[1].caption).toBe('Keep my edited caption');
  expect(saved.photos[1].approved_revision).toBeNull();
  expect(saved.photos[1].analysis.record.subjects[0].bibs[0].value).toBe('12');
  expect(saved.photos[1].conflicts_resolved).toBe(false);
  expect(saved.photos[2].analysis.record.subjects[0].athlete).toBeNull();
  await page.setViewportSize({ width: 1440, height: 1000 });
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: 'Undo last name assignment (1)' }).click();
  await expect(page.getByRole('button', { name: 'Undo last name assignment (1)' })).toBeEnabled();
  await expect(
    page.getByText('Last name assignment undone. Review the affected captions before approving.'),
  ).toHaveCount(0);
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Undo last name assignment (1)' }).click();
  await expect(page.getByRole('button', { name: 'Undo last name assignment (1)' })).toHaveCount(0);
  const undone = await readBatch();
  expect(undone.photos[1].analysis.record.subjects[0].athlete).toBeNull();
  expect(undone.photos[1].caption).toBe('Keep my edited caption');
  await page.getByRole('button', { name: 'Find matching faces…' }).click();
  await dialog.getByRole('checkbox', { name: 'match-3.jpg · person 1' }).uncheck();
  await acknowledgement.check();
  await dialog.getByRole('button', { name: 'Assign name to 1 selected photo' }).click();
  await expect(dialog).toHaveCount(0);
  await page
    .getByRole('button', { name: 'Save review and finish face session', exact: true })
    .click();
  await expect(page.getByRole('button', { name: 'Name detected face 1' })).toHaveCount(0);
  await page.reload();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue('Taylor Visitor');
  await page.getByRole('button', { name: 'Next photo', exact: true }).click();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue('Keep my edited caption');
});

test('propagation distinguishes tentative, already named, and protected faces', async ({
  page,
}) => {
  await login(page);
  const seed = await page.request.post('/api/batches', {
    headers: { 'X-Requested-With': 'Startnummer' },
    multipart: {
      gallery_url: 'http://gallery.test/album/a',
      roster_file: { name: 'roster.html', mimeType: 'text/html', buffer: Buffer.from(html) },
    },
  });
  const imageId = (await seed.json()).photos[0].id;
  const bytes = await (await page.request.get(`/api/photos/${imageId}`)).body();
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Upload images', { exact: true }).check();
  await page.getByLabel('Image files').setInputFiles(
    [1, 2, 3, 4].map((index) => ({
      name: `state-${index}.jpg`,
      mimeType: 'image/jpeg',
      buffer: bytes,
    })),
  );
  await page.getByLabel('Competitoroverview HTML').setInputFiles({
    name: 'roster.html',
    mimeType: 'text/html',
    buffer: Buffer.from(html),
  });
  await page.getByLabel('Album name', { exact: true }).fill('Propagation states');
  await page.getByRole('button', { name: 'Import and preview' }).click();
  await page.getByRole('button', { name: 'Analyze batch', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Name detected face 1' })).toBeVisible({
    timeout: 15000,
  });
  await page.getByRole('button', { name: 'Name detected face 1' }).click();
  await page.getByLabel('Or enter a name').fill('Taylor Visitor');
  await page.getByRole('button', { name: 'Save caption and corrections' }).click();
  const batchId = new URL(page.url()).hash.split('/')[1];
  const readBatch = async () =>
    (await (await page.request.get(`/api/batches/${batchId}`)).json()).batch;
  const before = await readBatch();
  let allNamed = false;
  // Render the three preview states, then let the real API reject the stale selection.
  await page.route(`**/api/batches/${batchId}/face-propagation/preview`, async (route) => {
    const response = await route.fetch();
    const preview = (await response.json()) as components['schemas']['PropagationPreview'];
    preview.candidates = preview.candidates.map((candidate, index) => ({
      ...candidate,
      state: allNamed || index === 1 ? 'already_named' : index === 0 ? 'eligible' : 'blocked',
      reason:
        allNamed || index === 1
          ? 'This name is already assigned'
          : index === 0
            ? null
            : candidate.reason,
      current_name: allNamed || index === 1 ? 'Taylor Visitor' : candidate.current_name,
      proposed_caption: !allNamed && index === 0 ? 'Taylor Visitor' : candidate.proposed_caption,
      replaces_tentative_name: !allNamed && index === 0,
      warnings:
        !allNamed && index === 0
          ? ['Tentative name "Alex Example" (50% confidence) will be replaced by "Taylor Visitor".']
          : [],
    }));
    await route.fulfill({ response, json: preview });
  });
  await page.getByRole('button', { name: 'Find matching faces…' }).click();
  const dialog = page.getByRole('dialog', { name: 'Assign Taylor Visitor to matching faces?' });
  await expect(dialog).toContainText('1 selectable · 1 already named · 1 needs individual review');
  await expect(dialog.getByRole('checkbox')).toHaveCount(2);
  await expect(dialog.getByText('Already named', { exact: true })).toBeVisible();
  const choice = dialog.getByRole('checkbox', { name: 'state-2.jpg · person 1' });
  await expect(choice).toBeEnabled();
  await dialog.getByText('state-2.jpg · person 1', { exact: true }).click();
  await expect(choice).not.toBeChecked();
  await choice.check();
  const apply = dialog.getByRole('button', { name: 'Assign name to 1 selected photo' });
  await expect(apply).toBeDisabled();
  await dialog
    .getByLabel('I checked the selected faces and proposed changes despite the warnings')
    .check();
  await expect(apply).toBeEnabled();
  await dialog.screenshot({ path: test.info().outputPath('propagation-states-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await dialog.screenshot({ path: test.info().outputPath('propagation-states-mobile.png') });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const responsePromise = page.waitForResponse((response) =>
    response.url().endsWith(`/api/batches/${batchId}/face-propagation`),
  );
  await apply.click();
  const response = await responsePromise;
  expect(response.status()).toBe(409);
  expect(response.request().postDataJSON()).toMatchObject({
    acknowledge_unsupported_bibs: true,
    acknowledge_tentative_names: true,
    targets: [{ photo_id: before.photos[1].id, revision: before.photos[1].revision, subject: 0 }],
  });
  await expect(dialog.getByRole('alert')).toContainText('changed or needs individual review');
  await dialog.getByRole('button', { name: 'Review this photo' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'state-4.jpg', exact: true })).toBeVisible();
  expect(await readBatch()).toEqual(before);
  allNamed = true;
  await page.getByRole('button', { name: 'Previous photo', exact: true }).click();
  await page.getByRole('button', { name: 'Previous photo', exact: true }).click();
  await page.getByRole('button', { name: 'Previous photo', exact: true }).click();
  await page.getByRole('button', { name: 'Name detected face 1' }).click();
  await page.getByRole('button', { name: 'Find matching faces…' }).click();
  const complete = page.getByRole('dialog', { name: 'Matching faces for Taylor Visitor' });
  await expect(complete).toContainText('No new names to assign');
  await expect(complete.getByRole('checkbox')).toHaveCount(0);
  await expect(complete.getByRole('button', { name: 'Nothing to assign' })).toBeDisabled();
  await page.keyboard.press('Escape');
});

test('gallery conflict can be inspected, refreshed, reviewed, and restored', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Album URL', { exact: true }).fill('http://gallery.test/album/a');
  await page.getByLabel('Competitoroverview HTML').setInputFiles({
    name: 'roster.html',
    mimeType: 'text/html',
    buffer: Buffer.from(html),
  });
  await page.getByLabel('Album name', { exact: true }).fill('Conflict recovery');
  await page.getByRole('button', { name: 'Import and preview' }).click();
  await page.getByRole('button', { name: 'Analyze batch', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Approve this photo', exact: true })).toBeEnabled({
    timeout: 15000,
  });
  await page.getByLabel('Reviewed caption').fill('Replacement after review');
  await page.getByRole('button', { name: 'Save caption and corrections' }).click();
  await page.getByRole('button', { name: 'Approve this photo', exact: true }).click();
  const batchId = new URL(page.url()).hash.split('/')[1];
  const headers = { 'X-Requested-With': 'Startnummer' };
  const concurrentImport = await page.request.post('/api/batches', {
    headers,
    multipart: {
      gallery_url: 'http://gallery.test/album/a',
      roster_file: { name: 'roster.html', mimeType: 'text/html', buffer: Buffer.from(html) },
    },
  });
  const other = await concurrentImport.json();
  await page.request.post(`/api/batches/${other.album.id}/analysis`, { headers });
  let concurrent: { id: string; revision: number };
  await expect
    .poll(async () => {
      const value = await (await page.request.get(`/api/batches/${other.album.id}`)).json();
      concurrent = value.batch.photos[0];
      return value.jobs[0]?.state;
    })
    .toBe('done');
  const edited = await page.request.patch(
    `/api/batches/${other.album.id}/photos/${concurrent!.id}`,
    {
      headers,
      data: { revision: concurrent!.revision, caption: 'Changed in gallery elsewhere' },
    },
  );
  const photo = await edited.json();
  const photos = [{ photo_id: photo.id, revision: photo.revision }];
  await page.request.post(`/api/batches/${other.album.id}/approve`, { headers, data: { photos } });
  const applied = await page.request.post(`/api/batches/${other.album.id}/apply`, {
    headers,
    data: { photos },
  });
  const [priorOperation] = await applied.json();
  await page.getByRole('button', { name: 'Preview Apply', exact: true }).click();
  await page.getByRole('button', { name: 'Apply to Chevereto', exact: true }).click();
  await expect(
    page.getByText('0 captions applied or unchanged; 1 conflicts or failures.'),
  ).toBeVisible();
  await page.getByRole('combobox', { name: 'Show' }).selectOption('publishing-issues');
  await expect(page.getByRole('region', { name: 'Photo queue' }).getByRole('button')).toHaveCount(
    1,
  );
  await page.getByRole('button', { name: 'Check gallery outcome', exact: true }).click();
  await expect(
    page.getByText('Gallery differs from this operation. Load its live description to review.'),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Load live description for review', exact: true }).click();
  await expect(page.getByLabel('Replace the existing gallery description')).not.toBeChecked();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue('Replacement after review');
  await expect(
    page.getByRole('button', { name: 'Approve this photo', exact: true }),
  ).toBeDisabled();
  await page.getByLabel('Replace the existing gallery description').check();
  await page.getByRole('button', { name: 'Save caption and corrections' }).click();
  await page.getByRole('button', { name: 'Approve this photo', exact: true }).click();
  await page.getByRole('button', { name: 'Preview Apply', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Changed in gallery elsewhere');
  await page.getByRole('button', { name: 'Apply to Chevereto', exact: true }).click();
  await expect(
    page.getByText('1 captions applied or unchanged; 0 conflicts or failures.'),
  ).toBeVisible();
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Restore previous description', exact: true }).click();
  await expect(page.getByText('Previous description restored.')).toBeVisible();
  const restored = await page.request.post(
    `/api/batches/${other.album.id}/publications/${priorOperation.id}/restore`,
    { headers },
  );
  expect((await restored.json()).state).toBe('applied');
  expect(batchId).toBeTruthy();
});

test('session expiry removes matching-face previews without losing the saved name', async ({
  page,
}) => {
  await page.clock.install();
  await login(page);
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Album URL', { exact: true }).fill('http://gallery.test/album/a');
  await page.getByLabel('Competitoroverview HTML').setInputFiles({
    name: 'roster.html',
    mimeType: 'text/html',
    buffer: Buffer.from(html),
  });
  await page.getByRole('button', { name: 'Import and preview' }).click();
  await page.getByRole('button', { name: 'Analyze batch', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Name detected face 1' })).toBeVisible({
    timeout: 15000,
  });
  await page.getByRole('button', { name: 'Name detected face 1' }).click();
  await page.getByLabel('Or enter a name').fill('Saved Visitor');
  await page.getByRole('button', { name: 'Save caption and corrections' }).click();
  await page.getByRole('button', { name: 'Find matching faces…' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.clock.fastForward(3_700_000);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Name detected face 1' })).toHaveCount(0);
  await expect(page.getByLabel('Reviewed caption')).toHaveValue('Saved Visitor');
  await expect(page.getByRole('button', { name: 'Find matching faces…' })).toBeDisabled();
  expect(
    await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length })),
  ).toEqual({ local: 0, session: 0 });
});

test('add roster people without detection, generate captions, remove an entry, and reopen', async ({
  page,
}) => {
  await login(page);
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Album URL', { exact: true }).fill('http://gallery.test/album/a');
  const second = html
    .replace('<div>12</div>', '<div></div>')
    .replace('Example Alex', 'Visitor Sam');
  await page.getByLabel('Competitoroverview HTML').setInputFiles({
    name: 'roster.html',
    mimeType: 'text/html',
    buffer: Buffer.from(html + second),
  });
  await page.getByLabel('Album name', { exact: true }).fill('Manual roster people');
  await page.getByLabel('Meet name', { exact: true }).fill('Example Meet');
  await page.getByRole('button', { name: 'Import and preview' }).click();
  await expect(
    page.getByRole('heading', { name: 'Manual roster people', exact: true }),
  ).toBeVisible();
  const batchId = new URL(page.url()).hash.split('/')[1];
  const readBatch = async () =>
    (await (await page.request.get(`/api/batches/${batchId}`)).json()).batch;
  expect((await readBatch()).photos[0].analysis).toBeNull();
  await expect(page.getByRole('button', { name: 'Add to this photo', exact: true })).toBeDisabled();
  await page.getByLabel('Find roster person', { exact: true }).fill('nobody-in-this-roster');
  await expect(page.getByText('No roster entries match this search.')).toBeVisible();
  await page.getByLabel('Find roster person', { exact: true }).fill('Alex');
  await page.getByRole('combobox', { name: 'Person to add', exact: true }).selectOption('0');
  await page.getByRole('button', { name: 'Add to this photo', exact: true }).click();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue(
    'Alex Example (12, Example Club) über 100m/over 100m | Example Meet',
  );
  await expect(
    page.getByRole('button', { name: 'Approve this photo', exact: true }),
  ).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Name detected face 1' })).toHaveCount(0);
  await page.getByLabel('Club (optional)', { exact: true }).fill('Example Club');
  await page.getByRole('button', { name: 'Save caption and corrections' }).click();
  await expect(
    page.getByRole('status').filter({ hasText: 'Changes saved for same.jpg.' }),
  ).toBeVisible();
  await page.getByText('Add person from roster', { exact: true }).click();
  await page.getByLabel('Find roster person', { exact: true }).fill('Sam');
  await page.getByRole('combobox', { name: 'Person to add', exact: true }).selectOption('1');
  await page.getByRole('button', { name: 'Add to this photo', exact: true }).click();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue(
    'Alex Example (12, Example Club) & Sam Visitor (Example Club) über 100m/over 100m | Example Meet',
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('region', { name: 'Photo queue' }).getByRole('button').first().click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page
    .getByRole('region', { name: 'Selected photo' })
    .screenshot({ path: test.info().outputPath('manual-people-mobile.png') });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page
    .getByRole('region', { name: 'Selected photo' })
    .screenshot({ path: test.info().outputPath('manual-people-desktop.png') });
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Remove added person', exact: true }).click();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue(
    'Alex Example (12, Example Club) über 100m/over 100m | Example Meet',
  );
  await page.getByLabel('I reviewed and resolved uncertain evidence in this photo').check();
  await page.getByRole('button', { name: 'Save caption and corrections' }).click();
  await page.getByRole('button', { name: 'Approve this photo', exact: true }).click();
  const before = await readBatch();
  expect(before.photos[0].analysis.record.subjects).toHaveLength(1);
  expect(before.photos[0].analysis.record.subjects[0].added_manually).toBe(true);
  expect(before.photos[0].analysis.record.subjects[0].bibs).toEqual([]);
  await page.reload();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue(before.photos[0].caption);
  await expect(
    page.getByRole('button', { name: 'Unapprove this photo', exact: true }),
  ).toBeEnabled();
});

test('an incompatible worker session explains disabled propagation and keeps individual naming available', async ({
  page,
}) => {
  await login(page);
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Album URL', { exact: true }).fill('http://gallery.test/album/a');
  await page.getByLabel('Competitoroverview HTML').setInputFiles({
    name: 'roster.html',
    mimeType: 'text/html',
    buffer: Buffer.from(html),
  });
  await page.getByRole('button', { name: 'Import and preview' }).click();
  await page.getByRole('button', { name: 'Analyze batch', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Name detected face 1' })).toBeVisible({
    timeout: 15000,
  });
  await page.getByRole('button', { name: 'Name detected face 1' }).click();
  await page.getByLabel('Or enter a name').fill('Saved Visitor');
  await page.getByRole('button', { name: 'Save caption and corrections' }).click();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue('Saved Visitor');
  const pattern = '**/api/batches/*/faces';
  await page.route(pattern, async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    await route.fulfill({
      response,
      json: {
        ...data,
        propagation_available: false,
        propagation_unavailable_reason:
          'This worker session does not support name propagation. Restart the updated worker and analyze a fresh batch. Keep this batch to preserve your review edits.',
      },
    });
  });
  await page.reload();
  await expect(
    page.getByRole('status').filter({ hasText: 'Restart the updated worker' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Name detected face 1' }).click();
  await expect(page.getByRole('button', { name: 'Find matching faces…' })).toBeDisabled();
  await expect(page.getByLabel('Or enter a name')).toBeEnabled();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue('Saved Visitor');
  await page
    .getByRole('status')
    .filter({ hasText: 'Restart the updated worker' })
    .screenshot({
      path: test.info().outputPath('incompatible-worker.png'),
    });
  await page.unroute(pattern);
  await page.reload();
  await page.getByRole('button', { name: 'Name detected face 1' }).click();
  await expect(page.getByRole('button', { name: 'Find matching faces…' })).toBeEnabled();
});
