import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev server runs on :5173 (already in the backend's CORS allow-list).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
