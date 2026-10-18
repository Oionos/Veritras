import type { components } from './api'

// ─── Generated aliases (single source of truth from openapi.json) ─────────────

export type Product = components['schemas']['ProductResponse']
export type Checkpoint = components['schemas']['CheckpointResponse']
export type CustodyTransfer = components['schemas']['CustodyTransferResponse']
export type Shipment = components['schemas']['ShipmentResponse']
export type Anomaly = components['schemas']['AnomalyResponse']

// ─── Manual interfaces (no clean generated equivalent) ───────────────────────

/** Composite detail view: not a named API schema */
export interface ProductDetail {
  product: Product
  history: Checkpoint[]
  transfers: CustodyTransfer[]
}

export type KPIData = components['schemas']['KPIResponse']
export type BottleneckLocation = components['schemas']['CheckpointInterval']

/** Not a top-level named schema in openapi.json */
export interface VerificationResult {
  is_registered: boolean
  is_delivered: boolean
  checkpoint_count: number
}
