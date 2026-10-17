import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { visualizer } from 'rollup-plugin-visualizer'
import { resolveEnvironment, connectSources } from './src/config/environment'

export default defineConfig(({ mode, command }) => {
  const raw = { ...loadEnv(mode, process.cwd(), ''), ...process.env }
  const preview = raw.VERCEL_ENV === 'preview'
  const environment = resolveEnvironment(raw, {
    production: command === 'build',
    preview,
    ci: raw.CI === 'true' && !raw.VERCEL_ENV,
  })
  return {
    define: {
      'import.meta.env.VITE_VERCEL_ENV': JSON.stringify(raw.VERCEL_ENV || ''),
      'import.meta.env.CI': JSON.stringify(raw.CI || ''),
    },
    plugins: [
      {
        name: 'environment-csp',
        transformIndexHtml: {
          order: 'pre',
          handler: (html) =>
            html.replace(
              '__VERITRAS_CONNECT_SOURCES__',
              connectSources(environment, command === 'serve'),
            ),
        },
      },
      react(),
      mode === 'analyze'
        ? visualizer({
            open: false,
            gzipSize: true,
            filename: 'dist/stats.html',
          })
        : undefined,
    ].filter(Boolean),
    resolve: {
      alias: {
        '@': path.resolve(import.meta.dirname, './src'),
      },
    },
    server: {
      port: 3000,
      host: true,
    },
    build: {
      outDir: 'dist',
      sourcemap: mode === 'development',
      // Vite 8 (Rolldown): object-form output.manualChunks was removed, so the
      // five vendor bundles are expressed as codeSplitting groups instead.
      rolldownOptions: {
        output: {
          codeSplitting: {
            groups: [
              {
                name: 'react-vendor',
                test: /node_modules\/(?:react|react-dom|react-router-dom)\//,
              },
              {
                name: 'ui-vendor',
                test: /node_modules\/(?:framer-motion|lucide-react)\//,
              },
              {
                name: 'web3-vendor',
                test: /node_modules\/(?:wagmi|viem|@rainbow-me\/rainbowkit)\//,
              },
              { name: 'charts-vendor', test: /node_modules\/recharts\// },
              {
                name: 'query-vendor',
                test: /node_modules\/@tanstack\/(?:react-query|query-core)\//,
                priority: 10,
              },
            ],
          },
        },
      },
    },
  }
})
