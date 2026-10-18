import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import RegistrationPanel from './RegistrationPanel'
import { fetchApi, useVerifyProduct } from '@/hooks/useApi'
import { useAuth } from '@/hooks/useAuth'
import type { Product } from '@/types'
vi.mock('@/hooks/useApi', () => ({fetchApi:vi.fn(),useVerifyProduct:vi.fn()}))
vi.mock('@/hooks/useAuth', () => ({ useAuth:vi.fn(),getAuthToken:()=>null }))
vi.mock('@/hooks/useRegisterProduct', () => ({ useRegisterProduct:()=>({register:vi.fn(),isPending:false,isConfirming:false}) }))
const product = {product_id:'PROD-1',name:'Widget',registration_status:'draft',owner_address:'0x1234567890123456789012345678901234567890',ownership_source:'signed_draft',block_number:0,tx_hash:'0x'} as Product
function mount() {
  return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false,gcTime:0}}})}><RegistrationPanel product={product}/></QueryClientProvider>)
}
beforeEach(()=>{
  vi.resetAllMocks();localStorage.clear()
  vi.mocked(useAuth).mockReturnValue({isAuthenticated:false,address:null} as ReturnType<typeof useAuth>)
  vi.mocked(useVerifyProduct).mockReturnValue({data:{evidence:{registration_status:'submitted',reason:'awaiting_receipt'}}} as ReturnType<typeof useVerifyProduct>)
  vi.mocked(fetchApi).mockImplementation(async path=>path.includes('metadata-history') ? {items:[]} : {attempts:[{tx_hash:`0x${'a'.repeat(64)}`,operation:'registration',status:'submitted',reason:'awaiting_receipt'}]})
})
describe('registration lifecycle panel',()=>{
  it('loads persisted transaction progress after remount without offering anonymous writes',async()=>{
    const view=mount()
    expect(await screen.findByText('registration · submitted · awaiting receipt')).toBeInTheDocument()
    expect(screen.queryByText('Save transaction hash')).not.toBeInTheDocument()
    expect(screen.getByText(/does not authenticate a physical item/)).toBeInTheDocument()
    view.unmount();mount()
    expect(await screen.findByText('registration · submitted · awaiting receipt')).toBeInTheDocument()
  })
  it('shows an explanatory state during an API outage',async()=>{
    vi.mocked(fetchApi).mockRejectedValue(new Error('offline'))
    mount()
    await waitFor(()=>expect(screen.getByRole('alert')).toHaveTextContent('tracking is unavailable'))
  })
  it('renders canonical and orphaned metadata versions as separate evidence',async()=>{
    vi.mocked(fetchApi).mockImplementation(async path=>path.includes('metadata-history') ? {items:[{transaction_hash:`0x${'b'.repeat(64)}`,block_number:12,block_hash:'canonical',log_index:1,canonical:true,metadata_uri:'ipfs://two'},{transaction_hash:`0x${'c'.repeat(64)}`,block_number:11,block_hash:'orphan',log_index:0,canonical:false,metadata_uri:'ipfs://orphan'}]} : {attempts:[]})
    mount()
    fireEvent.click(await screen.findByText('Metadata version history'))
    expect(screen.getByText(/Canonical · ipfs:\/\/two/)).toBeInTheDocument()
    expect(screen.getByText(/Orphaned · ipfs:\/\/orphan/)).toBeInTheDocument()
  })
})
