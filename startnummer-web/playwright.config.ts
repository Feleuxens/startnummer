import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  workers: 1,
  projects: [
    { name: 'accounts', testMatch: 'accounts.spec.ts', use: { baseURL: 'http://127.0.0.1:8101' } },
    { name: 'workflow', testMatch: 'workflow.spec.ts' },
    {
      name: 'integrations',
      testMatch: 'integrations.spec.ts',
      use: { baseURL: 'http://127.0.0.1:8100' },
    },
  ],
  use: {
    baseURL: 'http://127.0.0.1:8099',
    browserName: 'chromium',
    launchOptions: {
      executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium',
      args: ['--no-sandbox'],
    },
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command:
        'uv run --no-sync uvicorn tests.browser_app:create_fixture --factory --app-dir .. --host 127.0.0.1 --port 8101',
      url: 'http://127.0.0.1:8101',
      reuseExistingServer: false,
      env: { STARTNUMMER_BROWSER_ACCOUNTS: '1' },
    },
    {
      command:
        'uv run --no-sync uvicorn tests.browser_app:create_fixture --factory --app-dir .. --host 127.0.0.1 --port 8099',
      url: 'http://127.0.0.1:8099',
      reuseExistingServer: false,
    },
    {
      command:
        'uv run --no-sync uvicorn tests.browser_app:create_fixture --factory --app-dir .. --host 127.0.0.1 --port 8100',
      url: 'http://127.0.0.1:8100',
      reuseExistingServer: false,
      env: { STARTNUMMER_BROWSER_INTEGRATION_MODE: 'administration' },
    },
  ],
});
