import { defineConfig } from 'astro/config';
import react from '@astrojs/react';

export default defineConfig({
  integrations: [react()],
  vite: {
    server: {
      proxy: { '/api': { target: process.env.STARTNUMMER_API_URL || 'http://127.0.0.1:8000' } },
    },
  },
});
