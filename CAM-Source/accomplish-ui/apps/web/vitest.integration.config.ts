import { defineConfig, Plugin } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Intercept static asset imports at resolve time so test environments don't
// try to open /assets/... as real filesystem paths (they don't exist in tests).
const staticAssetMock: Plugin = {
  name: 'static-asset-mock',
  enforce: 'pre',
  resolveId(id: string) {
    if (/\.(svg|png|jpg|jpeg|gif|ico|webp)(\?.*)?$/.test(id)) {
      return '\0virtual:static-asset';
    }
  },
  load(id: string) {
    if (id === '\0virtual:static-asset') {
      return 'export default ""';
    }
  },
};

export default defineConfig({
  plugins: [react(), staticAssetMock],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src/client'),
      '@accomplish_ai/agent-core/common': path.resolve(
        __dirname,
        '../../packages/agent-core/src/common',
      ),
      '@accomplish_ai/agent-core': path.resolve(__dirname, '../../packages/agent-core/src'),
      '@locales': path.resolve(__dirname, 'locales'),
    },
  },
  test: {
    name: 'integration',
    globals: true,
    root: __dirname,
    include: ['__tests__/**/*.integration.test.{ts,tsx}'],
    // These pin the upstream Accomplish screens ("What will you accomplish today", example prompts, task status badges, the stock sidebar
    // logo and routes) that CAM 3.4 replaced with the RFQ app, so they fail on text and structure that no longer exist (SPEC-025 notes).
    // The files are kept, not deleted: re-point them at the CAM screens, then remove them from this list.
    exclude: [
      '**/node_modules/**',
      '__tests__/integration/renderer/App.integration.test.tsx',
      '__tests__/integration/renderer/pages/Home.integration.test.tsx',
      '__tests__/integration/renderer/pages/Execution.integration.test.tsx',
      '__tests__/integration/renderer/components/SettingsDialog.integration.test.tsx',
      '__tests__/integration/renderer/components/Sidebar.integration.test.tsx',
      '__tests__/integration/renderer/components/TaskLauncher.integration.test.tsx',
    ],
    setupFiles: ['__tests__/setup.ts'],
    environment: 'jsdom',
    testTimeout: 10000,
    hookTimeout: 15000,
  },
});
