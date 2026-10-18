import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { ethers } from 'hardhat';

async function main() {
  assert.equal((await ethers.provider.getNetwork()).chainId, 31337n);
  const manifest = JSON.parse(readFileSync(process.env.DEPLOYMENT_MANIFEST!, 'utf8'));
  assert.equal(Number(manifest.chainId), 31337);
  const base = process.env.TEST_API_URL!;
  assert.ok(new URL(base).hostname === 'backend', 'Smoke check must target the isolated Compose API');
  const api = async (path: string, init?: RequestInit) => {
    const response = await fetch(`${base}${path}`, init);
    assert.ok(response.ok, `${path}: HTTP ${response.status}: ${await response.clone().text()}`);
    return response.json();
  };
  const health = await api('/health/ready');
  assert.equal(health.environment, 'testing');
  assert.equal(health.chain_id, 31337);
  const [manufacturer, handler] = await ethers.getSigners();
  const { message } = await api('/auth/challenge', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ address: manufacturer.address }),
  });
  const signature = await manufacturer.signMessage(message);
  const auth = await api('/auth/verify', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, signature }),
  });
  assert.ok(auth.access_token);
  const replay = await fetch(`${base}/auth/verify`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, signature }),
  });
  assert.equal(replay.status, 401, 'A signed challenge must be consumed exactly once');
  const json = (body: unknown) => ({ method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${auth.access_token}` }, body: JSON.stringify(body) });
  const draft = await api('/products/', json({ name: 'Isolated testing item', manufacturer_address: manufacturer.address }));
  assert.equal(draft.owner_address, manufacturer.address.toLowerCase());
  assert.equal(draft.ownership_source, 'signed_draft');
  assert.equal(draft.registration_status, 'draft');
  assert.ok(draft.created_at);
  assert.equal(draft.registered_at, null);
  assert.equal(draft.on_chain_product_id, ethers.encodeBytes32String(draft.product_id));
  assert.equal(draft.chain_id, 31337);
  assert.equal(draft.registry_address, manifest.contracts.ProductRegistry.toLowerCase());
  assert.equal((await fetch(`${base}/products/`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'Anonymous write' }),
  })).status, 401);
  assert.equal((await api(`/products/${draft.product_id}/verify`)).is_registered, false);
  const shipment = await api('/shipments/', json({ product_id: draft.product_id, origin: 'Test factory', destination: 'Test depot' }));
  assert.equal((await fetch(`${base}/shipments/`, json({ product_id: draft.product_id, origin: 'Other', destination: 'Other' }))).status, 409);
  assert.equal(shipment.on_chain_product_id, draft.on_chain_product_id);
  assert.equal(shipment.tracker_address, manifest.contracts.ShipmentTracker.toLowerCase());
  const id = draft.on_chain_product_id;
  const registry = await ethers.getContractAt('ProductRegistry', manifest.contracts.ProductRegistry);
  const tracker = await ethers.getContractAt('ShipmentTracker', manifest.contracts.ShipmentTracker);
  await (await registry.registerProduct(id, draft.name, '', '')).wait();
  const edit = { ...json({ name: 'Cannot change a registered name' }), method: 'PUT' };
  assert.equal((await fetch(`${base}/products/${draft.product_id}`, edit)).status, 409);
  await (await tracker.recordCheckpoint(id, 'Test factory', 0, 'Created')).wait();
  await (await tracker.recordCheckpoint(id, 'Test route', 1, 'Departed')).wait();
  await (await tracker.transferCustody(id, handler.address)).wait();
  await (await tracker.connect(handler).recordCheckpoint(id, 'Test depot', 3, 'Delivered')).wait();
  for (let attempt = 0; attempt < 120; attempt++) {
    const detail = await api(`/products/${draft.product_id}`);
    if (detail.history.length >= 3 && detail.transfers.length >= 1) break;
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  const detail = await api(`/products/${draft.product_id}`);
  assert.equal(detail.product.registration_status, 'indexed');
  assert.ok(detail.product.registered_at);
  assert.equal(detail.product.on_chain_product_id, id);
  assert.equal(detail.history.length, 3, 'Delivery must not duplicate the checkpoint');
  assert.equal(detail.transfers.length, 1);
  const verification = await api(`/products/${draft.product_id}/verify`);
  assert.equal(verification.is_registered, true);
  assert.equal(verification.is_delivered, true);
  const rows = await api('/products/?limit=1000');
  assert.equal(rows.items.filter((p: { product_id: string }) => [draft.product_id, id].includes(p.product_id)).length, 1, 'Registration must reconcile the same draft');
  const shipments = await api('/shipments/?limit=100');
  assert.equal(shipments.items.find((s: { shipment_id: string }) => s.shipment_id === shipment.shipment_id).status, '3');
  console.log('PASS: isolated API + PostgreSQL + wallet login + registration + custody + delivery + receipt verification');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
