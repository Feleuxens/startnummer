import { expect, test } from '@playwright/test';

test('configure, test, save, reload, and use an encrypted gallery connection', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Username', { exact: true }).fill('photographer');
  await page.getByLabel('Password', { exact: true }).fill('browser-test-only');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Administration', exact: true }).click();
  const integration = page.getByRole('region', { name: 'Configured integrations', exact: true });
  const disclosure = integration.locator('summary');
  await expect(disclosure).toContainText('Not configured · Managed in Administration');
  await expect(integration.getByLabel('Gallery URL', { exact: true })).toBeHidden();
  await disclosure.focus();
  await page.keyboard.press('Enter');
  await integration.getByLabel('Gallery URL', { exact: true }).fill('http://gallery.test');
  await integration.getByLabel('Database host', { exact: true }).fill('db.test');
  await integration.getByLabel('Database name', { exact: true }).fill('gallery');
  await integration.getByLabel('Database username', { exact: true }).fill('synthetic-user');
  await integration.getByLabel('Database password', { exact: true }).fill('synthetic-secret');
  await disclosure.click();
  await expect(integration.getByLabel('Database host', { exact: true })).toBeHidden();
  await expect(disclosure).toContainText('Unsaved changes');
  await disclosure.focus();
  await page.keyboard.press('Space');
  await expect(integration.getByLabel('Database host', { exact: true })).toHaveValue('db.test');
  await expect(integration.getByLabel('Database password', { exact: true })).toHaveValue(
    'synthetic-secret',
  );
  await integration.getByRole('button', { name: 'Test connection', exact: true }).click();
  await expect(integration.getByRole('status')).toContainText('No descriptions were written');
  expect(
    (await (await page.request.get('/api/admin/integrations/chevereto')).json()).configured,
  ).toBe(false);
  page.once('dialog', (dialog) => dialog.dismiss());
  await page
    .getByRole('navigation', { name: 'Workspace', exact: true })
    .getByRole('button', { name: /^New batch/ })
    .click();
  await expect(page.getByRole('heading', { name: 'Administration', exact: true })).toBeVisible();

  const lifetime = page.getByLabel('Face-session lifetime (minutes)', { exact: true });
  await lifetime.fill('30');
  await integration.getByRole('button', { name: 'Save connection', exact: true }).click();
  await expect(integration.getByRole('status')).toContainText('Connection saved');
  await expect(integration.getByLabel('Database password', { exact: true })).toHaveValue('');
  page.once('dialog', (dialog) => dialog.dismiss());
  await page
    .getByRole('navigation', { name: 'Workspace', exact: true })
    .getByRole('button', { name: /^New batch/ })
    .click();
  await expect(lifetime).toHaveValue('30');
  await page.getByRole('button', { name: 'Save settings', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Settings saved.' })).toBeVisible();

  await page
    .getByRole('navigation', { name: 'Workspace', exact: true })
    .getByRole('button', { name: /^New batch/ })
    .click();
  await expect(page.getByLabel('Album URL', { exact: true })).toBeEnabled();
  await page.getByLabel('Album URL', { exact: true }).fill('http://gallery.test/album/a');
  await page.getByLabel('Competitoroverview HTML').setInputFiles({
    name: 'roster.html',
    mimeType: 'text/html',
    buffer: Buffer.from(
      '<html><div class="entryline"><div></div><div>12</div><div></div><div>Example Alex</div><div>Example Club</div><div></div><div></div><div>2000</div><div><a>100</a></div></div></html>',
    ),
  });
  await page.getByRole('button', { name: 'Import and preview', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Ready to analyze', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Administration', exact: true }).click();
  await expect(disclosure).toContainText('Configured · Managed in Administration');
  await disclosure.click();
  await expect(integration.getByLabel('Database host', { exact: true })).toHaveValue('db.test');
  await expect(integration.getByLabel('Database password', { exact: true })).toHaveValue('');
  const headers = { 'X-Requested-With': 'Startnummer' };
  const status = await (await page.request.get('/api/admin/integrations/chevereto')).json();
  expect(JSON.stringify(status)).not.toContain('synthetic-secret');
  const changed = await page.request.put('/api/admin/integrations/chevereto', {
    headers,
    data: {
      revision: status.revision,
      url: status.url,
      host: status.host,
      port: 3307,
      database: status.database,
      username: status.username,
      password: null,
    },
  });
  expect(changed.ok()).toBe(true);
  await integration.getByLabel('Database port', { exact: true }).fill('3310');
  await integration.getByRole('button', { name: 'Save connection', exact: true }).click();
  await expect(integration.getByRole('alert')).toContainText('changed');
  page.once('dialog', (dialog) => dialog.accept());
  await integration.getByRole('button', { name: 'Reload connection', exact: true }).click();
  await expect(integration.getByLabel('Database port', { exact: true })).toHaveValue('3307');
  await integration.getByLabel('Database host', { exact: true }).fill('unreachable.test');
  await integration.getByRole('button', { name: 'Test connection', exact: true }).click();
  await expect(integration.getByRole('alert')).toContainText('Could not read');
  await disclosure.click();
  await expect(disclosure).toContainText('Needs attention');
  await disclosure.click();
  expect((await (await page.request.get('/api/admin/integrations/chevereto')).json()).host).toBe(
    'db.test',
  );
  page.once('dialog', (dialog) => dialog.accept());
  await integration.getByRole('button', { name: 'Reload connection', exact: true }).click();
  await expect(integration.getByLabel('Database host', { exact: true })).toHaveValue('db.test');
  await integration.screenshot({ path: test.info().outputPath('connection-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await integration.screenshot({ path: test.info().outputPath('connection-mobile.png') });
  await disclosure.click();
  await expect(integration.getByLabel('Database host', { exact: true })).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await integration.screenshot({ path: test.info().outputPath('connection-collapsed-mobile.png') });
});
