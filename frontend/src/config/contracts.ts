import { appEnvironment } from './runtime'

export const PRODUCT_REGISTRY_ADDRESS = appEnvironment.productRegistry
export const SHIPMENT_TRACKER_ADDRESS = appEnvironment.shipmentTracker

export const productRegistryAbi = [
  {
    inputs: [{ internalType: 'bytes32', name: 'productId', type: 'bytes32' }],
    name: 'getProductManufacturer',
    outputs: [{ internalType: 'address', name: '', type: 'address' }],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [
      { internalType: 'bytes32', name: 'productId', type: 'bytes32' },
      { internalType: 'string', name: 'name', type: 'string' },
      { internalType: 'string', name: 'description', type: 'string' },
      { internalType: 'string', name: 'metadataURI', type: 'string' },
    ],
    name: 'registerProduct',
    outputs: [],
    stateMutability: 'nonpayable',
    type: 'function',
  },
  {
    inputs: [{ internalType: 'bytes32', name: 'productId', type: 'bytes32' }],
    name: 'getProduct',
    outputs: [
      {
        components: [
          { internalType: 'bytes32', name: 'productId', type: 'bytes32' },
          { internalType: 'address', name: 'manufacturer', type: 'address' },
          { internalType: 'string', name: 'name', type: 'string' },
          { internalType: 'string', name: 'description', type: 'string' },
          { internalType: 'string', name: 'metadataURI', type: 'string' },
          { internalType: 'uint256', name: 'timestamp', type: 'uint256' },
        ],
        internalType: 'struct ProductRegistry.Product',
        name: '',
        type: 'tuple',
      },
    ],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [{ internalType: 'bytes32', name: 'productId', type: 'bytes32' }],
    name: 'isProductRegistered',
    outputs: [{ internalType: 'bool', name: '', type: 'bool' }],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [
      { internalType: 'bytes32', name: 'productId', type: 'bytes32' },
      { internalType: 'string', name: 'newMetadataURI', type: 'string' },
    ],
    name: 'updateProductMetadata',
    outputs: [],
    stateMutability: 'nonpayable',
    type: 'function',
  },
  {
    anonymous: false,
    inputs: [
      { indexed: true, internalType: 'bytes32', name: 'productId', type: 'bytes32' },
      { indexed: true, internalType: 'address', name: 'manufacturer', type: 'address' },
      { indexed: false, internalType: 'string', name: 'name', type: 'string' },
      { indexed: false, internalType: 'uint256', name: 'timestamp', type: 'uint256' },
    ],
    name: 'ProductRegistered',
    type: 'event',
  },
] as const

export const shipmentTrackerAbi = [
  {
    inputs: [{ internalType: 'bytes32', name: '', type: 'bytes32' }],
    name: 'currentHandler',
    outputs: [{ internalType: 'address', name: '', type: 'address' }],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [
      { internalType: 'bytes32', name: 'productId', type: 'bytes32' },
      { internalType: 'string', name: 'location', type: 'string' },
      { internalType: 'uint8', name: 'status', type: 'uint8' },
      { internalType: 'string', name: 'notes', type: 'string' },
    ],
    name: 'recordCheckpoint',
    outputs: [],
    stateMutability: 'nonpayable',
    type: 'function',
  },
  {
    inputs: [
      { internalType: 'bytes32', name: 'productId', type: 'bytes32' },
      { internalType: 'address', name: 'newHandler', type: 'address' },
    ],
    name: 'transferCustody',
    outputs: [],
    stateMutability: 'nonpayable',
    type: 'function',
  },
  {
    inputs: [{ internalType: 'bytes32', name: 'productId', type: 'bytes32' }],
    name: 'getProductHistory',
    outputs: [
      {
        components: [
          { internalType: 'bytes32', name: 'productId', type: 'bytes32' },
          { internalType: 'string', name: 'location', type: 'string' },
          { internalType: 'uint8', name: 'status', type: 'uint8' },
          { internalType: 'address', name: 'handler', type: 'address' },
          { internalType: 'uint256', name: 'timestamp', type: 'uint256' },
          { internalType: 'string', name: 'notes', type: 'string' },
        ],
        internalType: 'struct ShipmentTracker.Checkpoint[]',
        name: '',
        type: 'tuple[]',
      },
    ],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [{ internalType: 'bytes32', name: 'productId', type: 'bytes32' }],
    name: 'isDelivered',
    outputs: [{ internalType: 'bool', name: '', type: 'bool' }],
    stateMutability: 'view',
    type: 'function',
  },
  {
    anonymous: false,
    inputs: [
      { indexed: true, internalType: 'bytes32', name: 'productId', type: 'bytes32' },
      { indexed: false, internalType: 'string', name: 'location', type: 'string' },
      { indexed: false, internalType: 'uint8', name: 'status', type: 'uint8' },
      { indexed: true, internalType: 'address', name: 'handler', type: 'address' },
      { indexed: false, internalType: 'uint256', name: 'timestamp', type: 'uint256' },
      { indexed: false, internalType: 'string', name: 'notes', type: 'string' },
    ],
    name: 'CheckpointRecorded',
    type: 'event',
  },
  {
    anonymous: false,
    inputs: [
      { indexed: true, internalType: 'bytes32', name: 'productId', type: 'bytes32' },
      { indexed: true, internalType: 'address', name: 'from', type: 'address' },
      { indexed: true, internalType: 'address', name: 'to', type: 'address' },
      { indexed: false, internalType: 'uint256', name: 'timestamp', type: 'uint256' },
    ],
    name: 'CustodyTransferred',
    type: 'event',
  },
  {
    anonymous: false,
    inputs: [
      { indexed: true, internalType: 'bytes32', name: 'productId', type: 'bytes32' },
      { indexed: true, internalType: 'address', name: 'handler', type: 'address' },
      { indexed: false, internalType: 'uint256', name: 'timestamp', type: 'uint256' },
    ],
    name: 'DeliveryCompleted',
    type: 'event',
  },
] as const
