import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import type { components } from '../src/api/schema';

const html = `<html><div class="entryline"><div></div><div>12</div><div></div><div>Example Alex</div><div>Example Club</div><div></div><div></div><div>2000</div><div><a>100</a></div></div></html>`;

async function login(page: Page) {
  await page.goto('/');
  await page.getByLabel('Username', { exact: true }).fill('photographer');
  await page.getByLabel('Password', { exact: true }).fill('browser-test-only');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Saved albums', exact: true })).toBeVisible();
}

test('preview name order, keep surname initials, override formats, and correct an imported name', async ({
  page,
}) => {
  await login(page);
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Album URL').fill('http://gallery.test/album/a');
  const names = [
    'EXAMPLE Alex',
    'Sam OTHER',
    'Jordan K.',
    'Van Example Robin',
    ...Array.from({ length: 20 }, (_, index) => `EXAMPLE${index} Morgan`),
  ];
  const roster = names
    .map((name, index) =>
      html.replace('<div>12</div>', `<div>${index + 12}</div>`).replace('Example Alex', name),
    )
    .join('');
  await page
    .getByLabel('Roster HTML')
    .setInputFiles({ name: 'roster.html', mimeType: 'text/html', buffer: Buffer.from(roster) });
  const order = page.getByRole('combobox', { name: 'Name order', exact: true });
  await expect(order).toHaveValue('auto');
  await page.getByRole('button', { name: 'Preview roster names', exact: true }).click();
  const name = (index: number) =>
    page.getByRole('textbox', { name: `Parsed name for roster person ${index}`, exact: true });
  await expect(name(1)).toHaveValue('Alex Example');
  await expect(
    page.locator('.roster-name-list').getByText('EXAMPLE Alex', { exact: true }),
  ).toBeVisible();
  await expect(name(2)).toHaveValue('Sam Other');
  await expect(name(3)).toHaveValue('Jordan K.');
  await expect(name(4)).toHaveValue('Robin Van Example');
  await page.getByLabel('Only uncertain automatic names', { exact: true }).check();
  await expect(page.locator('.roster-name-list li')).toHaveCount(1);
  await name(4).fill('Robin Preview');
  await expect(name(4)).toHaveValue('Robin Preview');
  await page.getByLabel('Only uncertain automatic names', { exact: true }).uncheck();
  await expect(page.locator('.roster-name-list li')).toHaveCount(20);
  await page.getByRole('button', { name: 'Next names', exact: true }).click();
  await expect(page.locator('.roster-name-list li')).toHaveCount(4);
  await page.getByRole('button', { name: 'Previous names', exact: true }).click();
  await name(4).fill('Robin Corrected');
  page.once('dialog', (dialog) => dialog.dismiss());
  await order.selectOption('surname_first');
  await expect(order).toHaveValue('auto');
  await expect(name(4)).toHaveValue('Robin Corrected');
  page.once('dialog', (dialog) => dialog.accept());
  await order.selectOption('surname_first');
  await expect(name(1)).toHaveCount(0);
  await page.getByRole('button', { name: 'Preview roster names', exact: true }).click();
  await expect(name(2)).toHaveValue('Other Sam');
  await order.selectOption('as_written');
  await page.getByRole('button', { name: 'Preview roster names', exact: true }).click();
  await expect(name(1)).toHaveValue('Example Alex');
  await order.selectOption('auto');
  await page.getByRole('button', { name: 'Preview roster names', exact: true }).click();
  await expect(name(1)).toHaveValue('Alex Example');
  await name(4).fill('Robin Corrected');
  await page.getByLabel('Search roster names', { exact: true }).fill('Robin');
  await page
    .locator('.roster-preview-section')
    .screenshot({ path: test.info().outputPath('roster-names-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page
    .locator('.roster-preview-section')
    .screenshot({ path: test.info().outputPath('roster-names-mobile.png') });
  await page.getByRole('button', { name: 'Import and preview' }).click();
  await expect(page.getByRole('heading', { name: 'Ready to analyze', exact: true })).toBeVisible();
  const batchId = new URL(page.url()).hash.split('/')[1];
  const batch = (await (await page.request.get(`/api/batches/${batchId}`)).json()).batch;
  expect(batch.roster.athletes[3].name).toBe('Robin Corrected');
  expect(batch.roster.name_parsing[3].source_name).toBe('Van Example Robin');
  expect(batch.roster.athletes[2].name).toBe('Jordan K.');
  await page.reload();
  expect((await (await page.request.get(`/api/batches/${batchId}`)).json()).batch.roster).toEqual(
    batch.roster,
  );
});

test('preview URL name formats and discard a preview after changing the source', async ({
  page,
}) => {
  await login(page);
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Supported URL', { exact: true }).check();
  await page.getByLabel('Roster URL').fill('https://roster.test/Competitions/Resultoverview/1');
  await page.getByLabel('Name order', { exact: true }).selectOption('given_first');
  await page.getByRole('button', { name: 'Preview roster names', exact: true }).click();
  await expect(page.getByLabel('Parsed name for roster person 1', { exact: true })).toHaveValue(
    'Example Alex',
  );
  await page.getByLabel('No roster', { exact: true }).check();
  await expect(page.getByLabel('Parsed name for roster person 1', { exact: true })).toHaveCount(0);
  await expect(page.locator('input[name="roster_digest"]')).toHaveCount(0);
});

test('assign a roster athlete without a bib and propagate the saved identity', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Album URL').fill('http://gallery.test/album/a');
  const roster = ['OTHER Sam', 'EXAMPLE Alex']
    .map((name) => html.replace('<div>12</div>', '<div></div>').replace('Example Alex', name))
    .join('');
  await page
    .getByLabel('Roster HTML')
    .setInputFiles({ name: 'roster.html', mimeType: 'text/html', buffer: Buffer.from(roster) });
  await page.getByRole('button', { name: 'Import and preview' }).click();
  await page.getByRole('button', { name: 'Analyze batch', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Name detected face 1' })).toBeEnabled({
    timeout: 15000,
  });
  await page.getByRole('button', { name: 'Name detected face 1' }).click();
  await page.getByLabel('Search roster athletes', { exact: true }).fill('Sam');
  const assign = page.getByRole('combobox', { name: 'Assign roster athlete', exact: true });
  await expect(assign.getByRole('option')).toHaveCount(2);
  await assign.selectOption('0');
  await page.getByLabel('Search roster athletes', { exact: true }).fill('Alex');
  await expect(assign).toHaveValue('0');
  await expect(assign.locator('optgroup')).toContainText('Sam Other');
  await page.getByRole('button', { name: 'Save caption and corrections' }).click();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue(/Sam Other/);
  await page.getByRole('button', { name: 'Find matching faces…' }).click();
  const dialog = page.getByRole('dialog', { name: 'Assign Sam Other to matching faces?' });
  await dialog
    .getByLabel('I checked the selected faces and proposed changes despite the warnings')
    .check();
  await dialog.getByRole('button', { name: 'Assign name to 1 selected photo' }).click();
  await expect(dialog).toHaveCount(0);
  const batchId = new URL(page.url()).hash.split('/')[1];
  const batch = (await (await page.request.get(`/api/batches/${batchId}`)).json()).batch;
  expect(
    batch.photos.every(
      (photo: components['schemas']['Photo']) =>
        photo.analysis?.record.subjects[0]?.athlete?.value.name === 'Sam Other',
    ),
  ).toBe(true);
  expect(batch.roster.athletes[0].bib).toBe('');
});

test('save private caption names, refresh suggestions, and preserve manual text and face review', async ({
  page,
}) => {
  const batchId = await openAnalyzedGallery(page, 'Caption overrides');
  const read = async (): Promise<components['schemas']['BatchView']> =>
    (await page.request.get(`/api/batches/${batchId}`)).json();
  const originalCaption = (await read()).batch.photos[0]!.caption!;
  await page.getByRole('button', { name: 'Approve this photo', exact: true }).click();
  await page.getByRole('button', { name: 'Next photo', exact: true }).click();
  await page.getByLabel('Reviewed caption').fill('Keep my manually edited caption');
  await page.getByRole('button', { name: 'Save caption and corrections', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Save caption and corrections', exact: true }),
  ).toBeDisabled();
  const before = (await read()).batch;
  await page.getByRole('button', { name: 'Account', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Caption name overrides', exact: true });
  await panel.getByRole('button', { name: 'Add name override', exact: true }).click();
  await panel.getByLabel('Full source name 1', { exact: true }).fill('Alex Example');
  await panel.getByLabel('Name in captions 1', { exact: true }).fill('Alex van Example');
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: /^Saved albums/ }).click();
  await expect(page.getByRole('heading', { name: 'Account', exact: true })).toBeVisible();
  await panel.getByRole('button', { name: 'Save name overrides', exact: true }).click();
  await expect(panel.getByRole('status')).toContainText('Existing captions were kept');
  expect((await read()).batch).toEqual(before);
  const preferences = await (await page.request.get('/api/account/caption-names')).json();
  expect(
    (
      await page.request.put('/api/account/caption-names', {
        headers: { 'X-Requested-With': 'Startnummer' },
        data: preferences,
      })
    ).ok(),
  ).toBe(true);
  await panel.getByLabel('Name in captions 1', { exact: true }).fill('Another draft');
  await panel.getByRole('button', { name: 'Save name overrides', exact: true }).click();
  await expect(panel.getByRole('alert')).toContainText('Settings changed');
  await expect(panel.getByLabel('Name in captions 1', { exact: true })).toHaveValue(
    'Another draft',
  );
  page.once('dialog', (dialog) => dialog.accept());
  await panel.getByRole('button', { name: 'Reload name overrides', exact: true }).click();
  await expect(panel.getByLabel('Name in captions 1', { exact: true })).toHaveValue(
    'Alex van Example',
  );
  await panel.screenshot({ path: test.info().outputPath('caption-names-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await panel.screenshot({ path: test.info().outputPath('caption-names-mobile.png') });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: /^Saved albums/ }).click();
  await page
    .getByRole('button')
    .filter({ has: page.getByRole('heading', { name: 'Caption overrides', exact: true }) })
    .click();
  const caption = page.getByLabel('Reviewed caption');
  await expect(caption).toHaveValue(originalCaption);
  const refresh = page.getByRole('button', { name: 'Refresh caption suggestion', exact: true });
  await refresh.click();
  await expect(caption).toHaveValue(originalCaption.replace('Alex Example', 'Alex van Example'));
  await expect(page.getByRole('button', { name: 'Approve this photo', exact: true })).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Name detected face 1', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Next photo', exact: true }).click();
  await expect(caption).toHaveValue('Keep my manually edited caption');
  await refresh.click();
  await expect(caption).toHaveValue('Keep my manually edited caption');
  await expect(
    page.locator('details').filter({ has: page.getByText('Analysis suggestion', { exact: true }) }),
  ).toContainText('Alex van Example');
  await page.getByRole('button', { name: 'Use generated caption', exact: true }).click();
  await page.getByRole('button', { name: 'Save caption and corrections', exact: true }).click();
  await expect(caption).toHaveValue(/Alex van Example/);
  expect((await read()).batch.roster.athletes![0]!.name).toBe('Alex Example');
  expect(
    (await read()).batch.photos.every(
      (photo) => photo.analysis?.record.subjects[0]?.athlete?.value.name === 'Alex Example',
    ),
  ).toBe(true);
  await page
    .getByRole('button', { name: 'Save review and finish face session', exact: true })
    .click();
  await expect(page.getByRole('button', { name: 'Name detected face 1', exact: true })).toHaveCount(
    0,
  );
  const latest = await (await page.request.get('/api/account/caption-names')).json();
  expect(
    (
      await page.request.put('/api/account/caption-names', {
        headers: { 'X-Requested-With': 'Startnummer' },
        data: { revision: latest.revision, overrides: [] },
      })
    ).ok(),
  ).toBe(true);
  await refresh.click();
  await expect(caption).toHaveValue(originalCaption);
});

test('administrator sees service status and saves revision-checked settings', async ({ page }) => {
  await login(page);
  await expect(
    page.locator('.sidebar-footer').getByRole('button', { name: 'Administration', exact: true }),
  ).toBeVisible();
  await expect(page.locator('.topbar')).not.toContainText('Chevereto configured');
  await page.getByRole('button', { name: 'Administration', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Administration', exact: true })).toBeVisible();
  const integrations = page.getByRole('region', { name: 'Configured integrations', exact: true });
  const disclosure = integrations.locator('summary');
  await expect(disclosure).toContainText('Configured · Managed by environment');
  await expect(integrations.getByLabel('Database host', { exact: true })).toBeHidden();
  await disclosure.click();
  await expect(integrations.getByRole('link')).toHaveAttribute('href', 'http://gallery.test');
  await expect(integrations.getByLabel('Database host', { exact: true })).toBeDisabled();
  await expect(
    integrations.getByRole('button', { name: 'Save connection', exact: true }),
  ).toHaveCount(0);
  await integrations.getByRole('button', { name: 'Test connection', exact: true }).click();
  await expect(integrations.getByRole('status')).toContainText('No descriptions were written');
  const file = page.getByRole('spinbutton', { name: 'Maximum photo size (MiB)', exact: true });
  const batch = page.getByRole('spinbutton', { name: 'Maximum batch size (MiB)', exact: true });
  const lifetime = page.getByRole('spinbutton', {
    name: 'Face-session lifetime (minutes)',
    exact: true,
  });
  await expect(file).toHaveValue('50');
  await expect(lifetime).toHaveValue('60');
  const services = page.getByRole('region', { name: 'Services', exact: true });
  await expect(services).toContainText('Writable');
  await expect(services).toContainText('idle');
  const original = (await (await page.request.get('/api/admin')).json()).settings;
  await file.fill('2');
  await batch.fill('8');
  await lifetime.fill('30');
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: /^Saved albums/ }).click();
  await expect(page.getByRole('heading', { name: 'Administration', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Save settings', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Settings saved.' })).toBeVisible();
  const saved = (await (await page.request.get('/api/admin')).json()).settings;
  expect(saved.max_file_bytes).toBe(2 * 1024 * 1024);
  expect(saved.max_batch_bytes).toBe(8 * 1024 * 1024);
  expect(saved.session_ttl).toBe(1800);
  await lifetime.fill('20');
  const concurrent = await page.request.put('/api/admin/settings', {
    headers: { 'X-Requested-With': 'Startnummer' },
    data: { ...saved, session_ttl: 900 },
  });
  expect(concurrent.ok()).toBe(true);
  await page.getByRole('button', { name: 'Save settings', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Settings changed');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Reload settings', exact: true }).click();
  await expect(lifetime).toHaveValue('15');
  await page.screenshot({
    path: test.info().outputPath('administration-desktop.png'),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: test.info().outputPath('administration-mobile.png'),
    fullPage: true,
  });
  const current = (await (await page.request.get('/api/admin')).json()).settings;
  expect(
    (
      await page.request.put('/api/admin/settings', {
        headers: { 'X-Requested-With': 'Startnummer' },
        data: { ...original, revision: current.revision },
      })
    ).ok(),
  ).toBe(true);
});

async function disciplineBatch(page: Page) {
  await login(page);
  const seed = await page.request.post('/api/batches', {
    headers: { 'X-Requested-With': 'Startnummer' },
    multipart: {
      gallery_url: 'http://gallery.test/album/a',
      roster_file: { name: 'roster.html', mimeType: 'text/html', buffer: Buffer.from(html) },
    },
  });
  expect(seed.ok()).toBe(true);
  const imageId = (await seed.json()).photos[0].id;
  const bytes = await (await page.request.get(`/api/photos/${imageId}`)).body();
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Upload images', { exact: true }).check();
  await page.getByLabel('Image files').setInputFiles(
    [1, 2, 3, 4, 5, 6].map((index) => ({
      name: `sequence-${index}.jpg`,
      mimeType: 'image/jpeg',
      buffer: bytes,
    })),
  );
  await page.getByLabel('Roster HTML').setInputFiles({
    name: 'roster.html',
    mimeType: 'text/html',
    buffer: Buffer.from(html),
  });
  await page.getByLabel('Album name', { exact: true }).fill('Discipline sequences');
  await page.getByRole('button', { name: 'Import and preview' }).click();
  await page.getByRole('button', { name: 'Analyze batch', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Approve this photo', exact: true })).toBeEnabled({
    timeout: 15000,
  });
  const batchId = new URL(page.url()).hash.split('/')[1];
  const read = async (): Promise<components['schemas']['BatchView']> =>
    (await page.request.get(`/api/batches/${batchId}`)).json();
  const batch = (await read()).batch;
  for (const [index, photo] of batch.photos.entries()) {
    const response = await page.request.patch(`/api/batches/${batchId}/photos/${photo.id}`, {
      headers: { 'X-Requested-With': 'Startnummer' },
      data: {
        revision: photo.revision,
        discipline: index === 5 ? 'no_event' : null,
        ...(index === 2 ? { caption: 'Keep my caption' } : {}),
      },
    });
    expect(response.ok()).toBe(true);
  }
  const photos = (await read()).batch.photos;
  expect(
    (
      await page.request.post(`/api/batches/${batchId}/approve`, {
        headers: { 'X-Requested-With': 'Startnummer' },
        data: { photos: photos.map((photo) => ({ photo_id: photo.id, revision: photo.revision })) },
      })
    ).ok(),
  ).toBe(true);
  await page.reload();
  await expect(
    page.getByText('6 photos · 1 roster entries · 6 approved', { exact: true }),
  ).toBeVisible();
  return { batchId, read };
}

test('select sequences, preview captions, and assign a discipline outside the roster', async ({
  page,
}) => {
  const { read } = await disciplineBatch(page);
  const before = (await read()).batch.photos;
  const check = (index: number) =>
    page.getByRole('checkbox', { name: `Select sequence-${index}.jpg`, exact: true });
  await page.getByRole('button', { name: 'Select photos', exact: true }).click();
  await check(1).check();
  await check(4).click({ modifiers: ['Shift'] });
  await expect(page.getByRole('status').filter({ hasText: '4 selected' })).toBeVisible();
  await check(2).uncheck();
  await expect(page.getByRole('status').filter({ hasText: '3 selected' })).toBeVisible();
  await page.getByRole('combobox', { name: 'Show', exact: true }).selectOption('undetermined');
  await expect(page.getByRole('status').filter({ hasText: '0 selected' })).toBeVisible();
  await expect(check(6)).toHaveCount(0);
  await expect(page.getByRole('checkbox', { name: /^Select sequence-/ })).toHaveCount(5);
  await page.getByRole('combobox', { name: 'From photo', exact: true }).selectOption(before[1]!.id);
  await page
    .getByRole('combobox', { name: 'Through photo', exact: true })
    .selectOption(before[3]!.id);
  await page.getByRole('button', { name: 'Select range', exact: true }).click();
  await expect(check(2)).toBeChecked();
  await expect(check(3)).toBeChecked();
  await expect(check(4)).toBeChecked();
  await expect(check(1)).not.toBeChecked();
  await page.getByRole('button', { name: 'Assign discipline…', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Assign discipline to 3 photos', exact: true });
  const chooser = dialog.getByRole('combobox', { name: 'Discipline for selected photos' });
  await expect(
    chooser.locator('optgroup[label="Entered by people in these photos"] option'),
  ).toHaveCount(1);
  await expect(
    chooser.locator('optgroup[label="All disciplines"] option[value="high_jump"]'),
  ).toHaveCount(1);
  await chooser.selectOption('high_jump');
  await dialog.getByRole('button', { name: 'Preview caption changes', exact: true }).click();
  await expect(dialog.getByText('Manually edited caption kept', { exact: true })).toBeVisible();
  await expect(dialog).toContainText('Hochsprung / High jump');
  await expect(dialog).toContainText('Keep my caption');
  expect((await read()).batch.photos).toEqual(before);
  await dialog.screenshot({ path: test.info().outputPath('discipline-preview-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await dialog.screenshot({ path: test.info().outputPath('discipline-preview-mobile.png') });
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  expect((await read()).batch.photos).toEqual(before);
  await page.getByRole('button', { name: 'Assign discipline…', exact: true }).click();
  await chooser.selectOption('high_jump');
  await dialog.getByRole('button', { name: 'Preview caption changes', exact: true }).click();
  await chooser.selectOption('long_jump');
  await expect(dialog.getByRole('button', { name: 'Assign to 3 photos', exact: true })).toHaveCount(
    0,
  );
  await chooser.selectOption('high_jump');
  await dialog.getByRole('button', { name: 'Preview caption changes', exact: true }).click();
  await dialog.getByRole('button', { name: 'Assign to 3 photos', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const after = (await read()).batch.photos;
  for (const index of [1, 2, 3]) {
    expect(after[index]!.analysis?.record.event.discipline?.value).toBe('high_jump');
    expect(after[index]!.approved_revision).toBeNull();
    expect(after[index]!.revision).toBe(before[index]!.revision + 1);
  }
  expect(after[2]!.caption).toBe('Keep my caption');
  expect(after[1]!.caption).toContain('Hochsprung');
  for (const index of [0, 4, 5]) expect(after[index]).toEqual(before[index]);
  await expect(page.getByRole('checkbox', { name: /^Select sequence-/ })).toHaveCount(2);
  await page.getByRole('combobox', { name: 'Show', exact: true }).selectOption('all');
  await page.getByRole('combobox', { name: 'From photo', exact: true }).selectOption(after[0]!.id);
  await page
    .getByRole('combobox', { name: 'Through photo', exact: true })
    .selectOption(after[1]!.id);
  await page.getByRole('button', { name: 'Select range', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '2 selected' })).toBeVisible();
  await page
    .locator('[aria-label="Select photos for discipline"]')
    .screenshot({ path: test.info().outputPath('discipline-range-mobile.png') });
});

test('bulk discipline refuses unsaved edits and stale previews', async ({ page }) => {
  const { batchId, read } = await disciplineBatch(page);
  await page
    .getByRole('textbox', { name: 'Reviewed caption', exact: true })
    .fill('Unsaved caption');
  await page.getByRole('button', { name: 'Select photos', exact: true }).click();
  await page.getByRole('button', { name: 'Select range', exact: true }).click();
  await page.getByRole('button', { name: 'Assign discipline…', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Save the current photo');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Save caption and corrections', exact: true }).click();
  await expect(
    page.getByRole('status').filter({ hasText: 'Changes saved for sequence-1.jpg.' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Assign discipline…', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Assign discipline to 6 photos', exact: true });
  await dialog
    .getByRole('combobox', { name: 'Discipline for selected photos' })
    .selectOption('no_event');
  await dialog.getByRole('button', { name: 'Preview caption changes', exact: true }).click();
  await expect(
    dialog.getByRole('button', { name: 'Assign to 5 photos', exact: true }),
  ).toBeVisible();
  const photo = (await read()).batch.photos[4]!;
  const response = await page.request.patch(`/api/batches/${batchId}/photos/${photo.id}`, {
    headers: { 'X-Requested-With': 'Startnummer' },
    data: { revision: photo.revision, caption: 'Newer edit from another tab' },
  });
  expect(response.ok()).toBe(true);
  const before = (await read()).batch.photos;
  await dialog.getByRole('button', { name: 'Assign to 5 photos', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('A selected photo changed');
  expect((await read()).batch.photos).toEqual(before);
  await expect(dialog.getByRole('button', { name: 'Assign to 5 photos', exact: true })).toHaveCount(
    0,
  );
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
});

test('search face assignments by bib, name, and club without changing the saved identity', async ({
  page,
}) => {
  await login(page);
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Album URL', { exact: true }).fill('http://gallery.test/album/a');
  const roster = [
    html,
    ...[
      ['77', 'North Terry', 'Riverside AC'],
      ['78', 'West Morgan', 'Riverside AC'],
      ['79', 'East Rowan', 'Hill Runners'],
    ].map(([bib, name, club]) =>
      html
        .replace('<div>12</div>', `<div>${bib}</div>`)
        .replace('Example Alex', name!)
        .replace('Example Club', club!),
    ),
  ].join('');
  await page.getByLabel('Roster HTML').setInputFiles({
    name: 'roster.html',
    mimeType: 'text/html',
    buffer: Buffer.from(roster),
  });
  await page.getByLabel('Album name', { exact: true }).fill('Search roster athletes');
  await page.getByRole('button', { name: 'Import and preview' }).click();
  await page.getByRole('button', { name: 'Analyze batch', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Approve this photo', exact: true })).toBeEnabled({
    timeout: 15000,
  });
  await page.getByRole('button', { name: 'Approve this photo', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Unapprove this photo', exact: true }),
  ).toBeVisible();
  const batchId = new URL(page.url()).hash.split('/')[1];
  const read = async (): Promise<components['schemas']['BatchView']> =>
    (await page.request.get(`/api/batches/${batchId}`)).json();
  const before = (await read()).batch.photos;
  await page.getByRole('button', { name: 'Name detected face 1', exact: true }).click();
  const search = page.getByRole('searchbox', { name: 'Search roster athletes', exact: true });
  const assign = page.getByRole('combobox', { name: 'Assign roster athlete', exact: true });
  const save = page.getByRole('button', { name: 'Save caption and corrections', exact: true });
  await search.fill('  RIVERSIDE  ');
  await expect(assign.getByRole('option')).toHaveCount(3);
  await expect(
    assign.getByRole('option', { name: '77 · Terry North · Riverside AC', exact: true }),
  ).toHaveCount(1);
  await expect(
    assign.getByRole('option', { name: '78 · Morgan West · Riverside AC', exact: true }),
  ).toHaveCount(1);
  await search.fill('terry');
  await expect(assign.getByRole('option')).toHaveCount(2);
  await search.fill('78');
  await expect(
    assign.getByRole('option', { name: '78 · Morgan West · Riverside AC', exact: true }),
  ).toHaveCount(1);
  await search.fill('missing club');
  await expect(
    page.getByText('No roster athletes match this search.', { exact: true }),
  ).toBeVisible();
  await expect(assign.getByRole('option')).toHaveCount(1);
  await expect(save).toBeDisabled();
  await search.press('Enter');
  expect((await read()).batch.photos).toEqual(before);

  await search.fill('77 riverside');
  await assign.selectOption('1');
  await expect(save).toBeEnabled();
  await search.fill('Hill');
  await expect(assign).toHaveValue('1');
  await expect(assign.locator('optgroup[label="Selected athlete"]')).toContainText('Terry North');
  await search.fill('missing club');
  await expect(assign).toHaveValue('1');
  await expect(
    page.getByText('No roster athletes match this search.', { exact: true }),
  ).toBeVisible();
  expect((await read()).batch.photos).toEqual(before);
  await search.fill('Riverside');
  const editor = page.locator('.subject-editor').filter({ has: search });
  await editor.screenshot({ path: test.info().outputPath('roster-search-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('region', { name: 'Photo queue' }).getByRole('button').first().click();
  await expect(search).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await editor.screenshot({ path: test.info().outputPath('roster-search-mobile.png') });
  await save.click();
  await expect(
    page.getByRole('status').filter({ hasText: 'Changes saved for same.jpg.' }),
  ).toBeVisible();
  const after = (await read()).batch.photos;
  expect(after[0]!.analysis?.record.subjects[0]?.athlete?.value.name).toBe('Terry North');
  expect(after[0]!.analysis?.record.subjects[0]?.athlete?.value.club).toBe('Riverside AC');
  expect(after[0]!.analysis?.record.subjects[0]?.athlete?.value.entered_events).toEqual(['100m']);
  expect(after[0]!.analysis?.record.subjects[0]?.athlete?.source).toBe('manual');
  expect(after[0]!.analysis?.record.subjects).toHaveLength(1);
  expect(after[0]!.approved_revision).toBeNull();
  expect(after[1]).toEqual(before[1]);
  await page.getByRole('button', { name: 'Name detected face 1', exact: true }).click();
  await search.fill('Hill');
  await page.getByRole('button', { name: 'Next photo', exact: true }).click();
  await page.getByRole('button', { name: 'Name detected face 1', exact: true }).click();
  await expect(search).toHaveValue('');
});

test('import, analyze, name an individual face, save, reopen, approve, apply, and restore', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await login(page);
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Album URL', { exact: true }).fill('http://gallery.test/album/a');
  await page
    .getByLabel('Roster HTML')
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
    .getByLabel('Roster HTML')
    .setInputFiles({ name: 'roster.html', mimeType: 'text/html', buffer: Buffer.from(html) });
  await page.getByLabel('Album name', { exact: true }).fill('Four-photo approval scope');
  await page.getByRole('button', { name: 'Import and preview' }).click();
  // A manual subject keeps the first photo in needs_review after analysis.
  await page.getByRole('combobox', { name: 'Person to add', exact: true }).selectOption('0');
  await page.getByRole('button', { name: 'Add to this photo', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Person added.' })).toBeVisible();
  await page.getByRole('button', { name: 'Analyze batch', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Approve this photo', exact: true })).toBeEnabled({
    timeout: 15000,
  });
  const batchId = new URL(page.url()).hash.split('/')[1];
  const readBatch = async () =>
    (await (await page.request.get(`/api/batches/${batchId}`)).json()).batch;
  const bulkCounts: number[] = [];
  const individualIds: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith(`/batches/${batchId}/approve`)) {
      bulkCounts.push(request.postDataJSON().photos.length);
    } else if (request.method() === 'POST' && request.url().endsWith('/approve')) {
      individualIds.push(request.url().split('/').at(-2)!);
    }
  });

  const saved = await readBatch();
  expect(saved.photos[0].analysis.record.status).toBe('needs_review');
  expect(
    saved.photos.map((photo: { conflicts_resolved: boolean }) => photo.conflicts_resolved),
  ).toEqual([false, false, false, false]);
  expect(
    saved.photos.every(
      (photo: { approved_revision: number | null }) => photo.approved_revision === null,
    ),
  ).toBe(true);
  await expect(
    page.getByLabel('I reviewed and resolved uncertain evidence in this photo'),
  ).toHaveCount(0);

  await page.getByRole('button', { name: 'Approve all eligible (3)…', exact: true }).click();
  const initialPreview = page.getByRole('dialog', { name: 'Approve all eligible captions?' });
  await expect(initialPreview.getByRole('heading', { name: 'original-1.jpg' })).toHaveCount(0);
  await initialPreview.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByLabel('Reviewed caption').fill('Unsaved review');
  await expect(
    page.getByRole('button', { name: 'Approve this photo', exact: true }),
  ).toBeDisabled();
  await page.getByLabel('Reviewed caption').fill(saved.photos[0].caption);
  await page.getByRole('button', { name: 'Save caption and corrections' }).click();
  await expect(page.getByRole('button', { name: 'Approve this photo', exact: true })).toBeEnabled();

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
  expect(individuallyApproved.photos[0].conflicts_resolved).toBe(true);
  expect(individuallyApproved.photos[0].analysis.record.status).toBe('needs_review');
  expect(individualIds).toEqual([saved.photos[0].id]);
  expect(bulkCounts).toEqual([]);
  await page.getByRole('combobox', { name: 'Show' }).selectOption('unresolved');
  await expect(page.getByText('No photos match this filter.')).toBeVisible();

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
  expect(bulkCounts).toEqual([]);
  await approveAll.click();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  expect(bulkCounts).toEqual([]);
  await approveAll.click();
  await dialog.getByRole('button', { name: 'Approve 3 captions', exact: true }).click();
  await expect(
    page.getByText('4 photos · 1 roster entries · 4 approved', { exact: true }),
  ).toBeVisible();
  expect(bulkCounts).toEqual([3]);
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
    .getByLabel('Roster HTML')
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
  await page.getByLabel('Roster HTML').setInputFiles({
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

for (const source of ['gallery', 'uploads']) {
  test(`analyze ${source} without a roster, name a face, and propagate it`, async ({ page }) => {
    await login(page);
    let bytes: Buffer | undefined;
    if (source === 'uploads') {
      const seed = await page.request.post('/api/batches', {
        headers: { 'X-Requested-With': 'Startnummer' },
        multipart: { gallery_url: 'http://gallery.test/album/a' },
      });
      expect(seed.ok()).toBe(true);
      const imageId = (await seed.json()).photos[0].id;
      bytes = await (await page.request.get(`/api/photos/${imageId}`)).body();
    }
    await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
    if (source === 'gallery') {
      await page.getByLabel('Album URL').fill('http://gallery.test/album/a');
    } else {
      await page.getByLabel('Upload images', { exact: true }).check();
      await page.getByLabel('Image files').setInputFiles(
        [1, 2].map((index) => ({
          name: `no-roster-${index}.jpg`,
          mimeType: 'image/jpeg',
          buffer: bytes!,
        })),
      );
    }
    await page.getByLabel('Roster HTML').setInputFiles({
      name: 'roster.html',
      mimeType: 'text/html',
      buffer: Buffer.from(html),
    });
    await page.getByLabel('No roster', { exact: true }).check();
    await expect(page.getByLabel('Roster HTML')).toHaveCount(0);
    await expect(page.getByLabel('Roster URL')).toHaveCount(0);
    await page.getByLabel('Album name', { exact: true }).fill(`Without roster: ${source}`);
    await page.getByLabel('Meet name', { exact: true }).fill('Example Meet');
    if (source === 'uploads') {
      await page.setViewportSize({ width: 390, height: 844 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.screenshot({
        path: test.info().outputPath('optional-roster-mobile.png'),
        fullPage: true,
      });
      await page.setViewportSize({ width: 1440, height: 1000 });
    }
    await page.getByRole('button', { name: 'Import and preview' }).click();
    await expect(
      page.getByText('No roster supplied. Name detected people during review.', { exact: true }),
    ).toBeVisible();
    const batchId = new URL(page.url()).hash.split('/')[1];
    const read = async (): Promise<components['schemas']['BatchView']> =>
      (await page.request.get(`/api/batches/${batchId}`)).json();
    expect((await read()).batch.roster.athletes).toEqual([]);
    expect((await read()).batch.album.roster_source).toBeNull();
    await expect(page.getByText('Add person from roster', { exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: 'Analyze batch', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Name detected face 1' })).toBeVisible({
      timeout: 15000,
    });
    await page.getByRole('button', { name: 'Name detected face 1' }).click();
    await expect(page.getByLabel('Search roster athletes', { exact: true })).toHaveCount(0);
    await expect(page.getByLabel('Assign roster athlete', { exact: true })).toHaveCount(0);
    await page.getByLabel('Name', { exact: true }).fill('Taylor Visitor');
    await page.getByLabel('Club (optional)', { exact: true }).fill('Example Club');
    await page.getByRole('button', { name: 'Save caption and corrections' }).click();
    await expect(page.getByLabel('Reviewed caption')).toHaveValue(
      'Taylor Visitor (Example Club) | Example Meet',
    );
    await page.getByRole('button', { name: 'Find matching faces…' }).click();
    const dialog = page.getByRole('dialog', { name: 'Assign Taylor Visitor to matching faces?' });
    await expect(dialog.getByText(/not in the saved roster/)).toHaveCount(0);
    await dialog.getByRole('button', { name: 'Assign name to 1 selected photo' }).click();
    await expect(dialog).toHaveCount(0);
    const named = (await read()).batch;
    expect(
      named.photos.every(
        (photo) => photo.caption === 'Taylor Visitor (Example Club) | Example Meet',
      ),
    ).toBe(true);
    expect(
      named.photos.every((photo) =>
        photo.analysis?.record.subjects[0]?.bibs?.some((bib) => bib.value === '12'),
      ),
    ).toBe(true);
    await page.getByRole('button', { name: 'Approve this photo', exact: true }).click();
    if (source === 'uploads') {
      await page.screenshot({
        path: test.info().outputPath('optional-roster-review-desktop.png'),
        fullPage: true,
      });
    }
    await page
      .getByRole('button', { name: 'Save review and finish face session', exact: true })
      .click();
    await expect(page.getByRole('button', { name: 'Name detected face 1' })).toHaveCount(0);
    await page.reload();
    await expect(page.getByLabel('Reviewed caption')).toHaveValue(
      'Taylor Visitor (Example Club) | Example Meet',
    );
    await expect(
      page.getByRole('button', { name: 'Unapprove this photo', exact: true }),
    ).toBeVisible();
  });
}

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
  await page.getByLabel('Roster HTML').setInputFiles({
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
  await page.getByLabel('Roster HTML').setInputFiles({
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
  await page.getByLabel('Roster HTML').setInputFiles({
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
  await page.getByLabel('Roster HTML').setInputFiles({
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
  await expect(
    page.getByRole('button', { name: 'Approve this photo', exact: true }),
  ).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Add to this photo', exact: true })).toBeDisabled();
  await page.getByLabel('Find roster person', { exact: true }).fill('nobody-in-this-roster');
  await expect(page.getByText('No roster entries match this search.')).toBeVisible();
  await page.getByLabel('Find roster person', { exact: true }).fill('Alex');
  await page.getByRole('combobox', { name: 'Person to add', exact: true }).selectOption('0');
  await page.getByRole('button', { name: 'Add to this photo', exact: true }).click();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue(
    'Alex Example (12, Example Club) über 100m/over 100m | Example Meet',
  );
  await expect(page.getByRole('button', { name: 'Approve this photo', exact: true })).toBeEnabled();
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
  await page.getByRole('button', { name: 'Approve this photo', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Unapprove this photo', exact: true }),
  ).toBeEnabled();
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
  await page.getByLabel('Roster HTML').setInputFiles({
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

async function openAnalyzedGallery(page: Page, name: string) {
  await login(page);
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Album URL', { exact: true }).fill('http://gallery.test/album/a');
  await page.getByLabel('Roster HTML').setInputFiles({
    name: 'roster.html',
    mimeType: 'text/html',
    buffer: Buffer.from(html),
  });
  await page.getByLabel('Album name', { exact: true }).fill(name);
  await page.getByRole('button', { name: 'Import and preview' }).click();
  await page.getByRole('button', { name: 'Analyze batch', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Name detected face 1', exact: true })).toBeEnabled(
    { timeout: 15000 },
  );
  return new URL(page.url()).hash.split('/')[1];
}

test('screen navigation guards drafts and expires hidden face data before reopening', async ({
  page,
}) => {
  await page.clock.install();
  await openAnalyzedGallery(page, 'Feature navigation');
  await page.getByRole('button', { name: 'Name detected face 1', exact: true }).click();
  await page.getByLabel('Or enter a name').fill('Saved Visitor');
  await page.getByRole('button', { name: 'Save caption and corrections' }).click();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue('Saved Visitor');
  await page.getByLabel('Reviewed caption').fill('Unsaved draft');

  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: 'Administration', exact: true }).click();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue('Unsaved draft');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Administration', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Administration', exact: true })).toBeVisible();
  await page.clock.fastForward(3_700_000);
  await expect(page.locator('.face-box')).toHaveCount(0);
  await page.getByRole('button', { name: /^Saved albums/ }).click();
  await page.getByRole('button', { name: /Feature navigation.*2 photos/ }).click();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue('Saved Visitor');
  await expect(page.getByRole('combobox', { name: 'Show', exact: true })).toHaveValue('all');
  await expect(page.getByLabel('Photo 1 of 2 in album')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save caption and corrections' })).toBeDisabled();
  await expect(page.locator('.face-box')).toHaveCount(0);
  expect(
    await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length })),
  ).toEqual({ local: 0, session: 0 });
});

test('an older analysis poll cannot restore a cancelled job or its face selectors', async ({
  page,
}) => {
  const batchId = await openAnalyzedGallery(page, 'Polling lifecycle');
  const stale: components['schemas']['BatchView'] = await (
    await page.request.get(`/api/batches/${batchId}`)
  ).json();
  const job = stale.jobs[0];
  if (!job) throw new Error('The analyzed fixture must contain a job');
  job.state = 'running';
  let cancelled = false;
  let reads = 0;
  let releasePoll!: () => void;
  let pollStarted!: () => void;
  const held = new Promise<void>((resolve) => {
    releasePoll = resolve;
  });
  const started = new Promise<void>((resolve) => {
    pollStarted = resolve;
  });
  await page.route(`**/api/batches/${batchId}/analysis/cancel`, async (route) => {
    cancelled = true;
    await route.continue();
  });
  await page.route(`**/api/batches/${batchId}`, async (route) => {
    if (cancelled) {
      await route.continue();
      return;
    }
    reads += 1;
    if (reads === 3) {
      pollStarted();
      await held;
      await route.fulfill({
        json: {
          ...stale,
          batch: { ...stale.batch, album: { ...stale.batch.album, name: 'Obsolete poll' } },
        },
      });
    } else await route.fulfill({ json: stale });
  });
  await page.reload();
  await started;
  await page.getByRole('button', { name: 'Cancel analysis', exact: true }).click();
  await expect(
    page.getByRole('status').filter({ hasText: 'Analysis cancelled. Saved review work was kept.' }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Cancel analysis', exact: true })).toHaveCount(0);
  await expect(page.locator('.face-box')).toHaveCount(0);
  await page.getByLabel('Reviewed caption').fill('Draft after cancellation');
  const delivered = page.waitForResponse(
    async (response) =>
      response.url().endsWith(`/api/batches/${batchId}`) &&
      (await response.json()).batch.album.name === 'Obsolete poll',
  );
  releasePoll();
  await (await delivered).finished();
  await page.evaluate(
    () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
  );
  await expect(page.getByRole('heading', { name: 'Polling lifecycle', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Cancel analysis', exact: true })).toHaveCount(0);
  await expect(page.locator('.face-box')).toHaveCount(0);
  await expect(page.getByLabel('Reviewed caption')).toHaveValue('Draft after cancellation');
});

async function subjectReviewBatch(page: Page) {
  await login(page);
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Album URL', { exact: true }).fill('http://gallery.test/album/a');
  const roster =
    html +
    html.replace('<div>12</div>', '<div>77</div>').replace('Example Alex', 'Example Sam') +
    html
      .replace('<div>12</div>', '<div>78</div>')
      .replace('Example Alex', 'Example Jordan')
      .replace('<a>100</a>', '<a>Weitsprung</a>');
  await page.getByLabel('Roster HTML').setInputFiles({
    name: 'roster.html',
    mimeType: 'text/html',
    buffer: Buffer.from(roster),
  });
  await page.getByLabel('Album name', { exact: true }).fill('Subject review');
  await page.getByLabel('Meet name', { exact: true }).fill('Example Meet');
  await page.getByRole('button', { name: 'Import and preview' }).click();
  await page.getByRole('button', { name: 'Analyze batch', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Name detected face 1', exact: true })).toBeVisible(
    { timeout: 15000 },
  );
  const batchId = new URL(page.url()).hash.split('/')[1]!;
  const read = async (): Promise<components['schemas']['BatchView']> =>
    (await page.request.get(`/api/batches/${batchId}`)).json();
  return { batchId, read };
}

test('edit beneath the selected person and keep photo actions fixed while scrolling', async ({
  page,
}) => {
  await subjectReviewBatch(page);
  for (const index of ['1', '2']) {
    await page.getByText('Add person from roster', { exact: true }).click();
    await page.getByRole('combobox', { name: 'Person to add', exact: true }).selectOption(index);
    await page.getByRole('button', { name: 'Add to this photo', exact: true }).click();
    await expect(page.locator('.subject-item')).toHaveCount(Number(index) + 1);
  }
  const people = page.locator('.subject-item');
  await page.getByRole('button', { name: 'Name detected face 1', exact: true }).click();
  await expect(people.nth(0).locator(':scope > .subject-editor')).toBeVisible();
  await expect(people.nth(1).locator('.subject-editor')).toHaveCount(0);
  const row = await people.nth(0).locator('.subject-choice').boundingBox();
  const fields = await people.nth(0).locator('.subject-editor').boundingBox();
  expect(
    row && fields && fields.y >= row.y + row.height && fields.y <= row.y + row.height + 16,
  ).toBeTruthy();
  await page.getByLabel('Or enter a name', { exact: true }).fill('Pending first person');
  await people.nth(2).locator('.subject-row').click();
  await expect(people.nth(2).locator(':scope > .subject-editor')).toBeVisible();
  await page.getByLabel('Or enter a name', { exact: true }).fill('Pending third person');
  await people.nth(0).locator('.subject-row').click();
  await expect(page.getByLabel('Or enter a name', { exact: true })).toHaveValue(
    'Pending first person',
  );
  const footer = page.locator('.editor-actions');
  const save = page.getByRole('button', { name: 'Save caption and corrections', exact: true });
  async function checkActions() {
    const dimensions = await footer.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return {
        position: getComputedStyle(element).position,
        bottom: rect.bottom,
        height: innerHeight,
      };
    });
    expect(dimensions.position).toBe('fixed');
    expect(Math.abs(dimensions.bottom - dimensions.height)).toBeLessThan(1);
    for (const button of [
      save,
      page.getByRole('button', { name: /^(?:Unapprove|Approve) this photo$/, exact: true }),
    ]) {
      const box = await button.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.y).toBeGreaterThanOrEqual(0);
      expect(box!.y + box!.height).toBeLessThanOrEqual(dimensions.height);
      expect(box!.height).toBe(44);
      expect(
        await button.evaluate((element) => {
          const rect = element.getBoundingClientRect();
          return element.contains(
            document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2),
          );
        }),
      ).toBe(true);
    }
  }
  await checkActions();
  await page.locator('.editor').evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await checkActions();
  await people.nth(0).locator('.subject-editor').scrollIntoViewIfNeeded();
  await checkActions();
  await page.screenshot({ path: test.info().outputPath('fixed-review-actions-desktop.png') });
  await page.setViewportSize({ width: 390, height: 780 });
  await expect(footer).toBeHidden();
  await page.getByRole('region', { name: 'Photo queue' }).getByRole('button').first().click();
  await checkActions();
  await people.nth(0).locator('.subject-editor').scrollIntoViewIfNeeded();
  await page.screenshot({ path: test.info().outputPath('fixed-review-actions-mobile.png') });
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await checkActions();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await save.click();
  await expect(save).toBeDisabled();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue(
    /Pending first person.*Pending third person/,
  );
  await page.getByRole('button', { name: 'Approve this photo', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Unapprove this photo', exact: true }),
  ).toBeVisible();
  await checkActions();
  await page.getByRole('button', { name: 'Back to photos', exact: false }).click();
  await expect(footer).toBeHidden();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect(footer).toBeVisible();
  await page.getByRole('button', { name: 'Account', exact: true }).click();
  await expect(footer).toBeHidden();
});

test('edit several people and exclude a background person in one atomic save', async ({ page }) => {
  const { batchId, read } = await subjectReviewBatch(page);
  await page.getByText('Add person from roster', { exact: true }).click();
  await page.getByRole('combobox', { name: 'Person to add', exact: true }).selectOption('1');
  await page.getByRole('button', { name: 'Add to this photo', exact: true }).click();
  await expect(page.locator('.subject-choice')).toHaveCount(2);
  const before = (await read()).batch.photos;
  const save = page.getByRole('button', { name: 'Save caption and corrections', exact: true });
  await page.getByLabel('Or enter a name', { exact: true }).fill('Visitor Example');
  await page.getByLabel('Club (optional)', { exact: true }).fill('Visitor Club');
  await page.getByRole('button', { name: 'Name detected face 1', exact: true }).click();
  await page.getByLabel('Correct bib', { exact: true }).fill('7');
  await page.getByRole('searchbox', { name: 'Search roster athletes', exact: true }).fill('Jordan');
  await page
    .getByRole('combobox', { name: 'Assign roster athlete', exact: true })
    .selectOption('2');
  await expect(page.getByLabel('Correct bib', { exact: true })).toHaveValue('78');
  await page.getByLabel('Club (optional)', { exact: true }).fill('Changed Club');
  await page.locator('.subject-choice').nth(1).locator('.subject-row').click();
  await expect(page.getByLabel('Or enter a name', { exact: true })).toHaveValue('Visitor Example');
  await expect(page.getByLabel('Club (optional)', { exact: true })).toHaveValue('Visitor Club');
  await page.getByRole('button', { name: 'Exclude person 2 from caption', exact: true }).click();
  await expect(page.locator('.subject-choice').nth(1)).toContainText('Excluded from caption');
  expect((await read()).batch.photos).toEqual(before);
  const endpoint = `/api/batches/${batchId}/photos/${before[0]!.id}`;
  await page.route('**' + endpoint, async (route) => {
    await route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: 'This photo changed since it was opened; reload before saving',
      }),
    });
  });
  await save.click();
  await expect(page.getByRole('alert')).toContainText('This photo changed');
  await expect(page.getByLabel('Or enter a name', { exact: true })).toHaveValue('Visitor Example');
  await page.getByRole('button', { name: 'Name detected face 1', exact: true }).click();
  await expect(page.getByLabel('Correct bib', { exact: true })).toHaveValue('78');
  await expect(
    page.getByRole('combobox', { name: 'Assign roster athlete', exact: true }),
  ).toHaveValue('2');
  await expect(page.getByLabel('Club (optional)', { exact: true })).toHaveValue('Changed Club');
  await expect(
    page.getByRole('searchbox', { name: 'Search roster athletes', exact: true }),
  ).toHaveValue('');
  await page.unroute('**' + endpoint);
  await save.click();
  await expect(
    page.getByRole('status').filter({ hasText: 'Changes saved for same.jpg.' }),
  ).toBeVisible();
  const after = (await read()).batch.photos;
  expect(after[0]!.revision).toBe(before[0]!.revision + 1);
  const people = after[0]!.analysis!.record.subjects!;
  expect(people[0]!.bibs?.map((bib) => bib.value)).toEqual(['78']);
  expect(people[0]!.athlete!.value.name).toBe('Jordan Example');
  expect(people[0]!.athlete!.value.club).toBe('Changed Club');
  expect(people[1]!.athlete!.value.name).toBe('Visitor Example');
  expect(people[1]!.athlete!.value.club).toBe('Visitor Club');
  expect(people[1]!.excluded_from_caption).toBe(true);
  expect(after[0]!.caption).toContain('Jordan Example (78, Changed Club)');
  expect(after[0]!.caption).not.toContain('Visitor Example');
  expect(after[1]).toEqual(before[1]);
  await page.reload();
  await expect(
    page.getByRole('button', { name: 'Include person 2 in caption', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Name detected face 1', exact: true }).click();
  await page
    .getByRole('region', { name: 'Selected photo' })
    .screenshot({ path: test.info().outputPath('subject-review-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('region', { name: 'Photo queue' }).getByRole('button').first().click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page
    .getByRole('region', { name: 'Selected photo' })
    .screenshot({ path: test.info().outputPath('subject-review-mobile.png') });
  await page.getByRole('button', { name: 'Include person 2 in caption', exact: true }).click();
  await save.click();
  await expect(page.getByLabel('Reviewed caption')).toHaveValue(/Visitor Example/);
});

test('excluding a person preserves a manual caption until the generated caption is chosen', async ({
  page,
}) => {
  const { read } = await subjectReviewBatch(page);
  const caption = page.getByLabel('Reviewed caption');
  const save = page.getByRole('button', { name: 'Save caption and corrections', exact: true });
  await caption.fill('My manually edited caption');
  await save.click();
  await expect(
    page.getByRole('status').filter({ hasText: 'Changes saved for same.jpg.' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Exclude person 1 from caption', exact: true }).click();
  await save.click();
  await expect(
    page.getByRole('button', { name: 'Include person 1 in caption', exact: true }),
  ).toBeVisible();
  await expect(caption).toHaveValue('My manually edited caption');
  await expect(
    page.getByText('No included person has a matched name.', { exact: true }),
  ).toBeVisible();
  expect((await read()).batch.photos[0]!.caption_edited).toBe(true);
  await page.getByRole('button', { name: 'Use generated caption', exact: true }).click();
  await expect(caption).toHaveValue('');
  await save.click();
  await expect(
    page.getByRole('button', { name: 'Approve this photo', exact: true }),
  ).toBeDisabled();
  await expect.poll(async () => (await read()).batch.photos[0]!.caption).toBeNull();
  const cleared = (await read()).batch.photos[0]!;
  expect(cleared.caption).toBeNull();
  expect(cleared.caption_edited).toBe(false);
  await page.getByRole('button', { name: 'Include person 1 in caption', exact: true }).click();
  await save.click();
  await expect(caption).toHaveValue(/Alex Example/);
});

for (const source of ['file', 'url'] as const) {
  test(`import a Resultoverview roster from ${source}`, async ({ page }) => {
    await login(page);
    await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
    await page.getByLabel('Album URL', { exact: true }).fill('http://gallery.test/album/a');
    if (source === 'url') {
      await page.getByLabel('Supported URL', { exact: true }).check();
      await page
        .getByLabel('Roster URL', { exact: true })
        .fill('https://roster.test/Competitions/Resultoverview/123');
    } else {
      const row = `<div class="entryline">
        <div class="col-1"><div class="firstline">1</div><div class="secondline">345</div></div>
        <div class="col-2"><div class="firstline">Example Alex</div><div class="secondline">Example Club</div></div>
        <div class="col-3"><div class="firstline">U20</div><div class="secondline">2006</div></div>
        <div class="col-4"><div class="firstline">12,34</div></div></div>`;
      const results = `<div class="listheader"><div class="leftheader">100m U20 Zeitläufe</div></div>${row}${row}`;
      await page.getByLabel('Roster HTML', { exact: true }).setInputFiles({
        name: 'results.html',
        mimeType: 'text/html',
        buffer: Buffer.from(results),
      });
    }
    await page.getByLabel('Album name', { exact: true }).fill(`Result roster ${source}`);
    if (source === 'file') {
      await page.screenshot({
        path: test.info().outputPath('result-import-desktop.png'),
        fullPage: true,
      });
      await page.setViewportSize({ width: 390, height: 844 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.screenshot({
        path: test.info().outputPath('result-import-mobile.png'),
        fullPage: true,
      });
      await page.setViewportSize({ width: 1440, height: 1000 });
    }
    await page.getByRole('button', { name: 'Import and preview', exact: true }).click();
    await expect(
      page.getByRole('heading', { name: 'Ready to analyze', exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText('2 photos · 1 roster entries · 0 approved', { exact: true }),
    ).toBeVisible();
    await expect(page.locator('.import-preview')).toContainText('345 · Alex Example');
    const batchId = new URL(page.url()).hash.split('/')[1];
    const view = await (await page.request.get(`/api/batches/${batchId}`)).json();
    expect(view.batch.roster.athletes).toHaveLength(1);
    expect(view.batch.roster.athletes[0]).toMatchObject({
      bib: '345',
      name: 'Alex Example',
      club: 'Example Club',
      year_birth: 2006,
    });
    await page.reload();
    await expect(page.locator('.import-preview')).toContainText('345 · Alex Example');
  });
}

async function orderedBatch(page: Page, legacy = false) {
  await login(page);
  const response = await page.request.post(`/fixture/photo-order?legacy=${legacy}`);
  expect(response.ok()).toBe(true);
  const batch: components['schemas']['Batch'] = await response.json();
  await page.reload();
  await page
    .getByRole('button')
    .filter({ has: page.getByRole('heading', { name: batch.album.name, exact: true }) })
    .click();
  await expect(page.getByRole('heading', { name: batch.album.name, exact: true })).toBeVisible();
  return batch;
}

const orderedNames = (page: Page) =>
  page.getByRole('region', { name: 'Photo queue' }).locator('.photo-tile > span').allTextContents();

test('filename, date, and import sorting share navigation and filtered selection order', async ({
  page,
}) => {
  const batch = await orderedBatch(page);
  const sort = page.getByRole('combobox', { name: 'Sort by', exact: true });
  const detail = page.getByRole('region', { name: 'Selected photo' });
  await expect(sort).toHaveValue('name');
  expect(await orderedNames(page)).toEqual([
    'photo-1.jpg',
    'photo-2.jpg',
    'photo-3.jpg',
    'photo-10.jpg',
  ]);
  await expect(detail.getByRole('heading', { name: 'photo-1.jpg', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next photo', exact: true }).click();
  await expect(detail.getByRole('heading', { name: 'photo-2.jpg', exact: true })).toBeVisible();
  await sort.selectOption('modified');
  expect(await orderedNames(page)).toEqual([
    'photo-3.jpg',
    'photo-10.jpg',
    'photo-2.jpg',
    'photo-1.jpg',
  ]);
  await expect(detail.getByRole('heading', { name: 'photo-2.jpg', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Previous photo', exact: true }).click();
  await expect(detail.getByRole('heading', { name: 'photo-10.jpg', exact: true })).toBeVisible();
  await sort.selectOption('taken');
  expect(await orderedNames(page)).toEqual([
    'photo-3.jpg',
    'photo-2.jpg',
    'photo-10.jpg',
    'photo-1.jpg',
  ]);
  await page.getByRole('button', { name: 'Select photos', exact: true }).click();
  await page.getByRole('checkbox', { name: 'Select photo-3.jpg', exact: true }).check();
  await page
    .getByRole('checkbox', { name: 'Select photo-10.jpg', exact: true })
    .click({ modifiers: ['Shift'] });
  await expect(page.getByRole('status').filter({ hasText: '3 selected' })).toBeVisible();
  await sort.selectOption('name');
  await expect(page.getByRole('status').filter({ hasText: '0 selected' })).toBeVisible();
  const from = page.getByRole('combobox', { name: 'From photo', exact: true });
  const through = page.getByRole('combobox', { name: 'Through photo', exact: true });
  const id = (number: number) =>
    batch.photos.find((photo) => photo.display_name === `photo-${number}.jpg`)!.id;
  await expect(from).toHaveValue(id(1));
  await expect(through).toHaveValue(id(10));
  await page.getByRole('combobox', { name: 'Show', exact: true }).selectOption('undetermined');
  await sort.selectOption('taken');
  expect(await orderedNames(page)).toEqual(['photo-3.jpg', 'photo-10.jpg', 'photo-1.jpg']);
  await from.selectOption(id(3));
  await through.selectOption(id(1));
  await page.getByRole('button', { name: 'Select range', exact: true }).click();
  for (const number of [3, 10, 1])
    await expect(
      page.getByRole('checkbox', { name: `Select photo-${number}.jpg`, exact: true }),
    ).toBeChecked();
  await sort.selectOption('original');
  expect(await orderedNames(page)).toEqual(['photo-10.jpg', 'photo-1.jpg', 'photo-3.jpg']);
  await expect(page.getByRole('status').filter({ hasText: '0 selected' })).toBeVisible();
  await page.getByRole('combobox', { name: 'Show', exact: true }).selectOption('all');
  expect(await orderedNames(page)).toEqual(batch.photos.map((photo) => photo.display_name));
  await page.screenshot({ path: test.info().outputPath('photo-sort-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath('photo-sort-mobile.png'), fullPage: true });
  await page.getByRole('button', { name: /^Saved albums/ }).click();
  await page
    .getByRole('button')
    .filter({ has: page.getByRole('heading', { name: batch.album.name, exact: true }) })
    .click();
  await expect(sort).toHaveValue('name');
  expect(await orderedNames(page)).toEqual([
    'photo-1.jpg',
    'photo-2.jpg',
    'photo-3.jpg',
    'photo-10.jpg',
  ]);
});

test('sorting older albums reads dates once without discarding drafts, approvals, or faces', async ({
  page,
}) => {
  const batch = await orderedBatch(page, true);
  const sort = page.getByRole('combobox', { name: 'Sort by', exact: true });
  const caption = page.getByLabel('Reviewed caption');
  await caption.fill('Keep my pending caption edits');
  let dateReads = 0;
  page.on('request', (request) => {
    if (
      request.method() === 'POST' &&
      request.url().endsWith(`/batches/${batch.album.id}/photo-dates`)
    )
      dateReads++;
  });
  const completed = page.waitForResponse(
    (response) => response.url().endsWith('/photo-dates') && response.status() === 200,
  );
  await sort.selectOption('taken');
  await completed;
  await expect(sort).toBeEnabled();
  expect(await orderedNames(page)).toEqual([
    'photo-3.jpg',
    'photo-2.jpg',
    'photo-10.jpg',
    'photo-1.jpg',
  ]);
  await expect(caption).toHaveValue('Keep my pending caption edits');
  await expect(
    page.getByRole('button', { name: 'Name detected face 1', exact: true }),
  ).toBeVisible();
  const after = (await (await page.request.get(`/api/batches/${batch.album.id}`)).json()).batch;
  for (const photo of after.photos) {
    const original = batch.photos.find((p) => p.id === photo.id)!;
    expect(photo.date_taken_read).toBe(true);
    expect(photo.revision).toBe(original.revision);
    expect(photo.approved_revision).toBe(original.approved_revision);
    expect(photo.caption).toBe(original.caption);
  }
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: 'Previous photo', exact: true }).click();
  await expect(caption).toHaveValue('Keep my pending caption edits');
  await sort.selectOption('name');
  await sort.selectOption('taken');
  expect(dateReads).toBe(1);
});

test('uploads retain the browser file modification times for sorting', async ({ page }) => {
  await login(page);
  const seed = await page.request.post('/fixture/photo-order');
  const sample = await seed.json();
  const bytes = Array.from(
    await (await page.request.get(`/api/photos/${sample.photos[0].id}`)).body(),
  );
  await page.getByRole('button', { name: 'New batch', exact: true }).last().click();
  await page.getByLabel('Upload images', { exact: true }).check();
  await page.getByLabel('Image files').evaluate((input, data) => {
    const transfer = new DataTransfer();
    transfer.items.add(
      new File([new Uint8Array(data)], 'photo-2.jpg', {
        type: 'image/jpeg',
        lastModified: Date.UTC(2020, 0, 1),
      }),
    );
    transfer.items.add(
      new File([new Uint8Array(data)], 'photo-1.jpg', {
        type: 'image/jpeg',
        lastModified: Date.UTC(2021, 0, 1),
      }),
    );
    (input as HTMLInputElement).files = transfer.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }, bytes);
  await page
    .getByLabel('Roster HTML', { exact: true })
    .setInputFiles({ name: 'roster.html', mimeType: 'text/html', buffer: Buffer.from(html) });
  await page.getByLabel('Album name', { exact: true }).fill('File modification times');
  await page.getByRole('button', { name: 'Import and preview', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Ready to analyze', exact: true })).toBeVisible();
  expect(await orderedNames(page)).toEqual(['photo-1.jpg', 'photo-2.jpg']);
  await page.getByRole('combobox', { name: 'Sort by', exact: true }).selectOption('modified');
  expect(await orderedNames(page)).toEqual(['photo-2.jpg', 'photo-1.jpg']);
  const batchId = new URL(page.url()).hash.split('/')[1];
  const batch = (await (await page.request.get(`/api/batches/${batchId}`)).json()).batch;
  expect(batch.photos.map((photo: components['schemas']['Photo']) => photo.date_modified)).toEqual([
    '2020-01-01T00:00:00Z',
    '2021-01-01T00:00:00Z',
  ]);
});
