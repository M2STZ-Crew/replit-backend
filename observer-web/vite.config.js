import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// :5174 so it runs beside the Admin Console (:5173). Both are in the backend's
// default CORS allow-list (app/core/config.py).
export default defineConfig({
  plugins: [react()],
  server: { port: 5174 },
});
