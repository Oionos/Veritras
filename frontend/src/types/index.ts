import type { components } from './api'

// ─── Generated aliases (single source of truth from openapi.json) ─────────────

export type Product = components['schemas']['ProductResponse']
export type Checkpoint = components['schemas']['CheckpointResponse']
export type CustodyTransfer = components['schemas']['CustodyTransferResponse']
export type Shipment = components['schemas']['ShipmentResponse']
export type Anomaly = components['schemas']['AnomalyResponse']

// ─── Manual interfaces (no clean generated equivalent) ───────────────────────

export type ProductDetail = components['schemas']['ProductDetailResponse']

export type KPIData = components['schemas']['KPIResponse']
export type BottleneckLocation = components['schemas']['CheckpointInterval']

export type VerificationResult = components['schemas']['VerificationResponse']
