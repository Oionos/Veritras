import { readFileSync } from 'node:fs'
import { spawn } from 'node:child_process'

const manifest = JSON.parse(readFileSync(process.env.DEPLOYMENT_MANIFEST, 'utf8'))
if (process.env.VITE_APP_ENV !== 'testing' || Number(manifest.chainId) !== 31337) {
  throw new Error('Local frontend requires the isolated Hardhat deployment')
}
const child = spawn('npm', ['run', 'dev', '--', '--host', '0.0.0.0', '--port', '3000', '--mode', 'testing'], {
  stdio: 'inherit',
  env: {
    ...process.env,
    VITE_PRODUCT_REGISTRY_CONTRACT: manifest.contracts.ProductRegistry,
    VITE_SHIPMENT_TRACKER_CONTRACT: manifest.contracts.ShipmentTracker,
  },
})
for (const signal of ['SIGTERM', 'SIGINT']) {
  process.on(signal, () => child.kill(signal))
}
child.on('exit', (code) => process.exit(code ?? 1))
