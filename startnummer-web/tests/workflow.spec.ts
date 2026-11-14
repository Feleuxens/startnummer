import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

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
