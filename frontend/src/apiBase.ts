/**
 * Base URL for all backend API calls.
 *
 * Defaults to '/api', which is what the Docker Compose deployment expects —
 * frontend/nginx.conf proxies '/api/*' to the backend service in production,
 * and vite.config.ts's dev-server proxy does the same thing locally.
 *
 * A standalone frontend deploy (e.g. Vercel) has neither of those proxies, so
 * set VITE_API_BASE_URL at build time to the backend's real, publicly
 * reachable URL (e.g. https://api.yourdomain.com) in that environment.
 */
export const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'
