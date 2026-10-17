import { resolveEnvironment } from './environment'

export const appEnvironment = resolveEnvironment(import.meta.env, {
  production: import.meta.env.PROD,
  preview: import.meta.env.VITE_VERCEL_ENV === 'preview',
  ci: !import.meta.env.VITE_VERCEL_ENV && (import.meta.env.CI === 'true' || import.meta.env.MODE === 'test'),
})
