import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { visualizer } from 'rollup-plugin-visualizer'

export default defineConfig(({ mode }) => ({
  plugins: [
    react(),
    mode === 'analyze'
      ? visualizer({ open: false, gzipSize: true, filename: 'dist/stats.html' })
      : undefined,
  ].filter(Boolean),
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
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
            { name: 'react-vendor', test: /node_modules\/(?:react|react-dom|react-router-dom)\// },
            { name: 'ui-vendor', test: /node_modules\/(?:framer-motion|lucide-react)\// },
            { name: 'web3-vendor', test: /node_modules\/(?:wagmi|viem|@rainbow-me\/rainbowkit)\// },
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
}))
