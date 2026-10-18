/** Real PostgreSQL/API/Hardhat reorganization; only accepts the local test stack. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { ethers, network } from 'hardhat';

async function main() {
  assert.equal((await ethers.provider.getNetwork()).chainId, 31337n);
  const base = process.env.TEST_API_URL!;
  assert.equal(new URL(base).hostname, 'backend');
  const manifest = JSON.parse(readFileSync(process.env.DEPLOYMENT_MANIFEST!, 'utf8'));
  assert.equal(Number(manifest.chainId), 31337);
  const api = async (path: string, init?: RequestInit) => {
    const response = await fetch(`${base}${path}`, init);
    assert.ok(response.ok, `${path}: ${response.status}`);
    return response.json();
  };
  const [owner, handler] = await ethers.getSigners();
  const post = (body: unknown, token?: string) => ({ method: 'POST', headers: {
    'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }, body: JSON.stringify(body) });
  const { message } = await api('/auth/challenge', post({ address: owner.address }));
  const { access_token } = await api('/auth/verify', post({ message, signature: await owner.signMessage(message) }));
  const draft = await api('/products/', post({ name: 'Durable recovery regression' }, access_token));
  const shipment = await api('/shipments/', post({ product_id: draft.product_id, origin: 'Recovery factory', destination: 'Recovery depot', notes: 'Preserve planning' }, access_token));
  const id = ethers.encodeBytes32String(draft.product_id);
  const registry = await ethers.getContractAt('ProductRegistry', manifest.contracts.ProductRegistry);
  const tracker = await ethers.getContractAt('ShipmentTracker', manifest.contracts.ShipmentTracker);
  await (await registry.registerProduct(id, draft.name, 'Original description', 'ipfs://original')).wait();
  await (await tracker.recordCheckpoint(id, 'Factory', 0, 'Canonical checkpoint')).wait();
  const wait = async (predicate: () => Promise<boolean>) => {
    for (let i = 0; i < 120; i++) {
      if (await predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    throw new Error('Indexer did not converge within 60 seconds');
  };
  await wait(async () => (await api(`/products/${draft.product_id}`)).history.length === 1);
  const snapshot = await network.provider.send('evm_snapshot');
  await (await registry.updateProductMetadata(id, 'ipfs://orphan')).wait();
  await (await tracker.transferCustody(id, handler.address)).wait();
  await (await tracker.connect(handler).recordCheckpoint(id, 'Orphan route', 1, '')).wait();
  await (await tracker.connect(handler).recordCheckpoint(id, 'Orphan delivery', 3, '')).wait();
  await wait(async () => (await api(`/products/${draft.product_id}/verify`)).is_delivered);
  assert.equal((await api(`/products/${draft.product_id}`)).transfers.length, 1);
  const oldHead = await ethers.provider.getBlockNumber();
  assert.equal(await network.provider.send('evm_revert', [snapshot]), true);
  // A shorter RPC head is treated as stale, not permission to erase history.
  // Mine beyond the previous tip so the actual fork can be compared/recovered.
  await network.provider.send('hardhat_mine', [ethers.toQuantity(oldHead + 1)]);
  await (await tracker.recordCheckpoint(id, 'Replacement route', 1, 'Canonical replacement')).wait();
  await wait(async () => {
    const detail = await api(`/products/${draft.product_id}`);
    return detail.history.length === 2 && detail.history[1].location === 'Replacement route' && detail.transfers.length === 0;
  });
  const detail = await api(`/products/${draft.product_id}`);
  assert.equal(detail.product.metadata_uri, 'ipfs://original');
  assert.equal(detail.product.description, 'Original description');
  const verification = await api(`/products/${draft.product_id}/verify`);
  assert.equal(verification.is_registered, true);
  assert.equal(verification.is_delivered, false);
  const rows = await api('/shipments/?limit=100');
  const current = rows.items.find((row: { shipment_id: string }) => row.shipment_id === shipment.shipment_id);
  assert.equal(current.status, '1');
  assert.equal(current.current_handler.toLowerCase(), owner.address.toLowerCase());
  assert.equal(current.notes, 'Preserve planning');
  console.log(`PASS: real chain reorganization restored metadata, custody, checkpoints and shipment; ${draft.product_id}`);
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
