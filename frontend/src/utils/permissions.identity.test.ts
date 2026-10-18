import { describe, expect, it } from 'vitest'
import { hasCurrentIdentity } from './permissions'
import { toProductBytes32 } from './productId'
import type { AppEnvironment } from '@/config/environment'
const environment: AppEnvironment = { name: 'testing', apiUrl:'https://testing.invalid', chainId:11155111, productRegistry:`0x${'1'.repeat(40)}`, shipmentTracker:`0x${'2'.repeat(40)}` }
const record = { on_chain_product_id:toProductBytes32('PROD-TEST'), chain_id:11155111, registry_address:environment.productRegistry, tracker_address:environment.shipmentTracker }
describe('contract scope checks',()=>{
  it('accepts only the configured full canonical identity',()=> expect(hasCurrentIdentity(record, environment)).toBe(true))
  it.each([{ chain_id:31337 },{ registry_address:`0x${'3'.repeat(40)}` },{ tracker_address:`0x${'3'.repeat(40)}` },{ on_chain_product_id:null },{ on_chain_product_id:`0x${'0'.repeat(64)}` }])('rejects a missing or different identity %j',change=>expect(hasCurrentIdentity({...record,...change},environment)).toBe(false))
})
