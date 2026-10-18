import { z } from 'zod'

export const ethereumAddressRegex = /^0x[a-fA-F0-9]{40}$/

export const ProductSchema = z.object({
  name: z
    .string()
    .min(2, 'Name must be at least 2 characters')
    .max(100, 'Name must be at most 100 characters'),
  manufacturer_address: z
    .string()
    .regex(ethereumAddressRegex, 'Must be a valid Ethereum address'),
  description: z
    .union([
      z.string().max(500, 'Description must be at most 500 characters'),
      z.literal(''),
    ])
    .optional(),
  metadata_uri: z
    .union([z.string().url('Must be a valid URL'), z.literal('')])
    .optional(),
})

export const ShipmentSchema = z.object({
  expected_arrival_at: z.string().optional(),
  product_id: z.string().min(1, 'Product ID is required'),
  origin: z
    .string()
    .min(2, 'Origin must be at least 2 characters')
    .max(100, 'Origin must be at most 100 characters'),
  destination: z
    .string()
    .min(2, 'Destination must be at least 2 characters')
    .max(100, 'Destination must be at most 100 characters'),
  notes: z
    .union([
      z.string().max(500, 'Notes must be at most 500 characters'),
      z.literal(''),
    ])
    .optional(),
})

export type ProductFormData = z.infer<typeof ProductSchema>
export type ShipmentFormData = z.infer<typeof ShipmentSchema>
