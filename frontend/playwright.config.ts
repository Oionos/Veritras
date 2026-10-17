import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'list',
  timeout: 30000,
  use: {
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : {},
    baseURL: 'http://localhost:3001',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    // In CI: build first so preview serves static files — no HMR WebSocket,
    // no JIT module compilation, no dev-mode noise. Faster and more stable.
    // VITE_API_URL must be set here (not just in .env) because .env is gitignored;
    // the build bakes this value in so vite preview serves the correct origin.
    command: process.env.CI
      ? 'npm run build && npx vite preview --port 3001 --strictPort'
      : 'npm run dev -- --port 3001',
    url: 'http://localhost:3001',
    reuseExistingServer: !process.env.CI,
    // Allow 3 minutes: covers the full vite build + server start in CI.
    // Locally the dev server starts in < 10 s so this is never reached.
    timeout: 180000,
    env: {
      VITE_API_URL: 'https://chainlens-4qvy.onrender.com',
    },
  },
})
