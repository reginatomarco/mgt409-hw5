import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The board runs on http://localhost:5173 and calls the FastAPI backend at
// http://localhost:8000 directly; backend/main.py allows this origin (CORS).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
})
