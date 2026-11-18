import { expect, test } from '@playwright/test';

const password = 'synthetic-browser-password';

test('setup, invitations, registration, and account recovery', async ({ page, browser }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Set up Startnummer' })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: test.info().outputPath('setup-mobile.png'), fullPage: true });
  const code = (await (await page.request.get('/fixture/setup-code')).json()).code;
  await page.getByLabel('Setup code', { exact: true }).fill(code);
  await page.getByLabel('Username', { exact: true }).fill('administrator');
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByLabel('Confirm password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Create administrator', exact: true }).click();
  await page.getByRole('button', { name: 'Administration', exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  const accounts = page.getByRole('region', { name: 'Accounts and invitations', exact: true });
  await expect(accounts.getByLabel('Allow public registration')).not.toBeChecked();
  await accounts.getByLabel('Invitation label', { exact: true }).fill('Guest photographer');
  await accounts.getByRole('button', { name: 'Create invitation link', exact: true }).click();
  await expect(accounts.getByLabel('Invitation link', { exact: true })).toBeVisible();
  const link = await accounts.getByLabel('Invitation link', { exact: true }).inputValue();
  await expect(accounts.getByText('Guest photographer', { exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('accounts-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: test.info().outputPath('accounts-mobile.png'), fullPage: true });

  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const guest = await context.newPage();
  await guest.goto(link);
  await expect(guest.getByRole('heading', { name: 'Create your account' })).toBeVisible();
  await guest.getByLabel('Username', { exact: true }).fill('guest');
  await guest.getByLabel('Password', { exact: true }).fill(password);
  await guest.getByLabel('Confirm password', { exact: true }).fill(password);
  await guest.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(guest.getByRole('heading', { name: 'Saved albums', exact: true })).toBeVisible();
  expect(new URL(guest.url()).hash).toBe('');
  await expect(guest.getByRole('button', { name: 'Administration', exact: true })).toHaveCount(0);
  await guest
    .getByRole('navigation', { name: 'Workspace', exact: true })
    .getByRole('button', { name: /^New batch/ })
    .click();
  await expect(guest.getByLabel('Image files')).toBeVisible();
  await expect(guest.getByText('Chevereto album', { exact: true })).toHaveCount(0);
  await guest.getByRole('button', { name: 'Account', exact: true }).click();
  await guest.getByLabel('Current password', { exact: true }).fill(password);
  await guest.getByLabel('New password', { exact: true }).fill(password + '-changed');
  await guest.getByLabel('Confirm new password', { exact: true }).fill(password + '-changed');
  guest.once('dialog', (dialog) => dialog.accept());
  await guest.getByRole('button', { name: 'Change password', exact: true }).click();
  await expect(guest.getByRole('status')).toContainText('Password changed');
  await guest.screenshot({ path: test.info().outputPath('account-mobile.png'), fullPage: true });

  await accounts.getByRole('button', { name: 'Refresh accounts', exact: true }).click();
  page.once('dialog', (dialog) => dialog.accept());
  await accounts.getByRole('button', { name: 'Revoke sessions for guest', exact: true }).click();
  await expect(accounts.getByRole('status')).toContainText('Sessions revoked');
  await guest.getByRole('button', { name: /^Saved albums/ }).click();
  await expect(guest.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
  await expect(guest.getByRole('alert')).toContainText('Sign in');
  await expect(guest.getByRole('button', { name: 'Create an account', exact: true })).toHaveCount(
    0,
  );

  const signIn = async (value: string) => {
    await guest.getByLabel('Username', { exact: true }).fill('guest');
    await guest.getByLabel('Password', { exact: true }).fill(value);
    await guest.getByRole('button', { name: 'Sign in', exact: true }).click();
  };
  await signIn(password + '-changed');
  await expect(guest.getByRole('heading', { name: 'Saved albums', exact: true })).toBeVisible();
  page.once('dialog', (dialog) => dialog.accept());
  await accounts.getByRole('button', { name: 'Disable guest', exact: true }).click();
  await expect(accounts.getByRole('status')).toContainText('guest disabled');
  await expect(accounts.getByRole('button', { name: 'Enable guest', exact: true })).toBeVisible();
  expect((await guest.request.get('/api/session')).status()).toBe(401);
  await guest.reload();

  await accounts.getByRole('button', { name: 'Reset password for guest', exact: true }).click();
  const reset = page.getByRole('dialog', { name: 'Reset password for guest' });
  await expect(reset).toBeVisible();
  await reset.screenshot({ path: test.info().outputPath('password-reset-mobile.png') });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await reset.screenshot({ path: test.info().outputPath('password-reset-desktop.png') });
  await reset.getByLabel('Your administrator password', { exact: true }).fill(password);
  await reset
    .getByLabel('New password (at least 12 characters)', { exact: true })
    .fill(password + '-reset');
  await reset.getByLabel('Confirm new password', { exact: true }).fill(password + '-mismatch');
  await reset.getByRole('button', { name: 'Reset password', exact: true }).click();
  await expect(reset.getByRole('alert')).toContainText('do not match');
  await reset.getByLabel('Confirm new password', { exact: true }).fill(password + '-reset');
  await reset.getByRole('button', { name: 'Reset password', exact: true }).click();
  await expect(reset).toBeHidden();
  await expect(accounts.getByRole('status')).toContainText('Password reset for guest');
  await signIn(password + '-reset');
  await expect(guest.getByRole('alert')).toContainText('Invalid username or password');
  await accounts.getByRole('button', { name: 'Enable guest', exact: true }).click();
  await expect(accounts.getByRole('status')).toContainText('guest enabled');
  await signIn(password + '-changed');
  await expect(guest.getByRole('alert')).toContainText('Invalid username or password');
  await signIn(password + '-reset');
  await expect(guest.getByRole('heading', { name: 'Saved albums', exact: true })).toBeVisible();
  await guest.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(guest.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();

  await guest.goto(link);
  await guest.getByLabel('Username', { exact: true }).fill('reused');
  await guest.getByLabel('Password', { exact: true }).fill(password);
  await guest.getByLabel('Confirm password', { exact: true }).fill(password);
  await guest.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(guest.getByRole('alert')).toContainText('already used');

  await accounts.getByLabel('Allow public registration').check();
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: /^Saved albums/ }).click();
  await expect(accounts).toBeVisible();
  await accounts.getByRole('button', { name: 'Save registration', exact: true }).click();
  await expect(accounts.getByRole('status')).toContainText('Registration settings saved');
  await guest.goto('/');
  await guest.getByRole('button', { name: 'Create an account', exact: true }).click();
  await guest.getByLabel('Username', { exact: true }).fill('public-user');
  await guest.getByLabel('Password', { exact: true }).fill(password);
  await guest.getByLabel('Confirm password', { exact: true }).fill(password);
  await guest.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(guest.getByRole('heading', { name: 'Saved albums', exact: true })).toBeVisible();
  expect((await (await guest.request.get('/api/session')).json()).is_admin).toBe(false);
  await guest.getByRole('button', { name: 'Account', exact: true }).click();
  guest.once('dialog', (dialog) => dialog.accept());
  await guest.getByRole('button', { name: 'Sign out all sessions', exact: true }).click();
  await expect(guest.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
  await context.close();
});
