import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Search, AlertCircle, ChevronLeft, ChevronRight, Loader2, RefreshCw, Plus } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { CurrencyAmount } from '@/lib/currency'
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
    DialogFooter, DialogClose,
} from '@/components/ui/dialog'

interface CollectionNode {
    id: string
    customerId: string
    borrowerName: string | null
    amount: string
    status: string
    dueDate: string
    daysPastDue: number
    agingBucket: string
    collectionDate: string | null
    collectedBy: string | null
    referenceNumber: string | null
    collectionType: string | null
    notes: string | null
    createdAt: string
}

interface CollectionConnection {
    collections: CollectionNode[]
    total: number
}

const PAGE_SIZE = 50

const STATUS_OPTIONS = ['', 'pending', 'overdue', 'collected', 'partial', 'written_off'] as const

const AGING_COLORS: Record<string, string> = {
    current: 'bg-emerald-500/20 text-emerald-400',
    '1-30_days': 'bg-emerald-500/20 text-emerald-400',
    '31-60_days': 'bg-amber-500/20 text-amber-400',
    '61-90_days': 'bg-orange-500/20 text-orange-400',
    '90+_days': 'bg-red-500/20 text-red-400',
}

const STATUS_COLORS: Record<string, string> = {
    pending: 'bg-amber-500/20 text-amber-400',
    overdue: 'bg-red-500/20 text-red-400',
    collected: 'bg-emerald-500/20 text-emerald-400',
    partial: 'bg-blue-500/20 text-blue-400',
    written_off: 'bg-gray-500/20 text-gray-400',
}

const GRAPHQL_QUERY = `query GetCollections($first: Int!, $offset: Int!, $search: String, $status: String) {
  collections(first: $first, offset: $offset, search: $search, status: $status) {
    collections {
      id customerId borrowerName amount status dueDate daysPastDue agingBucket
      collectionDate collectedBy referenceNumber collectionType notes createdAt
    }
    total
  }
}`

const GRAPHQL_MUTATION = `mutation CreateCollection($input: CollectionCreateInput!) {
  createCollection(input: $input) { success message }
}`

function getAgingLabel(bucket: string): string {
    const labels: Record<string, string> = {
        current: 'Current',
        '1-30_days': '1-30 Days',
        '31-60_days': '31-60 Days',
        '61-90_days': '61-90 Days',
        '90+_days': '90+ Days',
    }
    return labels[bucket] || bucket.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function fetchCollections(variables: Record<string, any>): Promise<CollectionConnection> {
    const token = localStorage.getItem('access_token')
    return fetch('/graphql', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': token ? `Bearer ${token}` : '',
        },
        body: JSON.stringify({ query: GRAPHQL_QUERY, variables }),
    }).then(res => res.json()).then(data => {
        if (data.errors) throw new Error(data.errors[0]?.message || 'GraphQL error')
        return data.data?.collections || { collections: [], total: 0 }
    })
}

export default function CollectionsPage() {
    const { user } = useAuth()
    const queryClient = useQueryClient()
    const canCreate = ['admin', 'branch_manager', 'collections_officer'].includes(user?.role ?? '')

    const [search, setSearch] = useState('')
    const [debouncedSearch, setDebouncedSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState('')
    const [page, setPage] = useState(0)
    const [showCreateDialog, setShowCreateDialog] = useState(false)
    const searchTimer = useRef<ReturnType<typeof setTimeout>>()

    const variables = {
        first: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        ...(debouncedSearch.trim() && { search: debouncedSearch.trim() }),
        ...(statusFilter && { status: statusFilter }),
    }

    const { data, isLoading, isFetching, error, refetch } = useQuery({
        queryKey: ['collections', variables],
        queryFn: () => fetchCollections(variables),
        placeholderData: (prev) => prev,
        staleTime: 30_000,
        refetchOnWindowFocus: true,
    })

    const createMutation = useMutation({
        mutationFn: (input: Record<string, any>) => {
            const token = localStorage.getItem('access_token')
            return fetch('/graphql', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': token ? `Bearer ${token}` : '',
                },
                body: JSON.stringify({ query: GRAPHQL_MUTATION, variables: { input } }),
            }).then(res => res.json())
        },
        onSuccess: (data) => {
            if (data.data?.createCollection?.success) {
                setShowCreateDialog(false)
                setPage(0)
                queryClient.invalidateQueries({ queryKey: ['collections'] })
            } else {
                alert(data.data?.createCollection?.message || 'Failed to create collection')
            }
        },
        onError: () => alert('Failed to create collection'),
    })

    const connection = data ?? { collections: [], total: 0 }
    const totalPages = Math.ceil(connection.total / PAGE_SIZE)

    const handleSearch = (value: string) => {
        setSearch(value)
        if (searchTimer.current) clearTimeout(searchTimer.current)
        searchTimer.current = setTimeout(() => {
            setDebouncedSearch(value)
            setPage(0)
        }, 300)
    }

    const handleCreateCollection = (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault()
        const form = new FormData(e.currentTarget)
        createMutation.mutate({
            customerId: form.get('customerId') as string,
            amount: parseFloat(form.get('amount') as string),
            dueDate: form.get('dueDate') as string,
            referenceNumber: (form.get('referenceNumber') as string) || null,
            collectionType: (form.get('collectionType') as string) || null,
            notes: (form.get('notes') as string) || null,
        })
    }

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 space-y-6 animate-fade-in p-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white">Collections</h1>
                    <p className="text-slate-400 text-sm mt-1">Loan collection management and aging monitoring</p>
                </div>
                {canCreate && (
                    <button
                        onClick={() => setShowCreateDialog(true)}
                        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-blue-600 to-blue-500 text-white text-sm font-medium shadow-lg hover:opacity-90 transition-opacity"
                    >
                        <Plus className="w-4 h-4" /> New Collection
                    </button>
                )}
            </div>

            <div className="glass rounded-xl p-4 border border-slate-700/50">
                <div className="flex flex-wrap gap-3 items-center">
                    <div className="relative flex-1 min-w-[200px]">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                        <input
                            value={search}
                            onChange={e => handleSearch(e.target.value)}
                            placeholder="Search by borrower name, ID, or reference..."
                            className="w-full pl-10 pr-4 py-2 rounded-lg border border-slate-600 bg-slate-800/50 focus:outline-none focus:border-blue-400 text-slate-200"
                        />
                    </div>
                    <select
                        value={statusFilter}
                        onChange={e => { setStatusFilter(e.target.value); setPage(0) }}
                        className="px-3 py-2 rounded-lg border border-slate-600 bg-slate-800/50 text-slate-200 text-sm"
                    >
                        <option value="">All Statuses</option>
                        {STATUS_OPTIONS.filter(Boolean).map(s => (
                            <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ')}</option>
                        ))}
                    </select>
                    <button
                        onClick={() => refetch()}
                        className="flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-600 bg-slate-800/50 hover:bg-slate-700/50 text-slate-200 text-sm transition-colors"
                    >
                        <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
                    </button>
                </div>
            </div>

            {error && (
                <div className="flex items-center gap-3 p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400">
                    <AlertCircle className="w-5 h-5 shrink-0" />
                    <p className="text-sm">{(error as Error).message}</p>
                    <button onClick={() => refetch()} className="ml-auto text-xs underline hover:no-underline">Retry</button>
                </div>
            )}

            {isLoading ? (
                <div className="flex items-center justify-center py-16 text-slate-400">
                    <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading collections...
                </div>
            ) : (
                <div className="glass rounded-xl overflow-hidden border border-slate-700/50">
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-slate-700/50">
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Borrower</th>
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Reference</th>
                                    <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Amount</th>
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Due Date</th>
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">DPD</th>
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Aging</th>
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Status</th>
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Collector</th>
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Collected</th>
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Created</th>
                                </tr>
                            </thead>
                            <tbody>
                                {connection.collections.length === 0 ? (
                                    <tr><td colSpan={10} className="text-center py-12 text-slate-400">No collections found.</td></tr>
                                ) : connection.collections.map((c) => (
                                    <tr key={c.id} className="border-b border-slate-700/30 hover:bg-slate-800/50 transition-colors">
                                        <td className="px-4 py-3">
                                            <div className="text-white font-medium">{c.borrowerName || `Customer #${c.customerId.slice(-6)}`}</div>
                                            <div className="text-xs text-slate-500 font-mono">{c.customerId.slice(-8).toUpperCase()}</div>
                                        </td>
                                        <td className="px-4 py-3 text-slate-400 font-mono text-xs">{c.referenceNumber || '—'}</td>
                                        <td className="px-4 py-3 text-white font-medium text-right">{new CurrencyAmount(c.amount).format()}</td>
                                        <td className="px-4 py-3 text-slate-400">{new Date(c.dueDate).toLocaleDateString()}</td>
                                        <td className="px-4 py-3">
                                            <span className={`text-xs font-medium ${c.daysPastDue > 30 ? 'text-red-400' : c.daysPastDue > 0 ? 'text-amber-400' : 'text-emerald-400'}`}>
                                                {c.daysPastDue > 0 ? `${c.daysPastDue}d` : '—'}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className={`text-xs px-2 py-1 rounded-full ${AGING_COLORS[c.agingBucket] || 'bg-gray-500/20 text-gray-400'}`}>
                                                {getAgingLabel(c.agingBucket)}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className={`text-xs px-2 py-1 rounded-full ${STATUS_COLORS[c.status] || 'bg-gray-500/20 text-gray-400'}`}>
                                                {c.status.charAt(0).toUpperCase() + c.status.slice(1).replace(/_/g, ' ')}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3 text-slate-400 text-xs">{c.collectedBy || '—'}</td>
                                        <td className="px-4 py-3 text-slate-400">{c.collectionDate ? new Date(c.collectionDate).toLocaleDateString() : '—'}</td>
                                        <td className="px-4 py-3 text-slate-500 text-xs">{new Date(c.createdAt).toLocaleDateString()}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>

                    {totalPages > 1 && (
                        <div className="flex items-center justify-between px-4 py-3 border-t border-slate-700/50">
                            <span className="text-xs text-slate-400">
                                Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, connection.total)} of {connection.total}
                            </span>
                            <div className="flex gap-2">
                                <button
                                    onClick={() => setPage(p => Math.max(0, p - 1))}
                                    disabled={page === 0}
                                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-600 bg-slate-800/50 text-slate-200 text-xs disabled:opacity-40 hover:bg-slate-700/50 transition-colors"
                                >
                                    <ChevronLeft className="w-3 h-3" /> Prev
                                </button>
                                <button
                                    onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                                    disabled={page >= totalPages - 1}
                                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-600 bg-slate-800/50 text-slate-200 text-xs disabled:opacity-40 hover:bg-slate-700/50 transition-colors"
                                >
                                    Next <ChevronRight className="w-3 h-3" />
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            )}

            <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
                <DialogContent className="sm:max-w-md bg-slate-800 border-slate-600 text-white">
                    <DialogHeader>
                        <DialogTitle>Confirm New Collection</DialogTitle>
                        <DialogDescription className="text-slate-400">
                            This will create a new collection entry. All entries are subject to audit review.
                        </DialogDescription>
                    </DialogHeader>
                    <form onSubmit={handleCreateCollection}>
                        <div className="grid gap-4 py-4">
                            <div>
                                <label className="text-xs text-slate-400 block mb-1">Customer ID *</label>
                                <input name="customerId" required
                                    className="w-full px-3 py-2 rounded-lg border border-slate-600 bg-slate-700/50 text-white text-sm focus:outline-none focus:border-blue-400" />
                            </div>
                            <div>
                                <label className="text-xs text-slate-400 block mb-1">Amount (PHP) *</label>
                                <input name="amount" type="number" step="0.01" min="0" required
                                    className="w-full px-3 py-2 rounded-lg border border-slate-600 bg-slate-700/50 text-white text-sm focus:outline-none focus:border-blue-400" />
                            </div>
                            <div>
                                <label className="text-xs text-slate-400 block mb-1">Due Date *</label>
                                <input name="dueDate" type="date" required
                                    className="w-full px-3 py-2 rounded-lg border border-slate-600 bg-slate-700/50 text-white text-sm focus:outline-none focus:border-blue-400" />
                            </div>
                            <div>
                                <label className="text-xs text-slate-400 block mb-1">Reference Number</label>
                                <input name="referenceNumber"
                                    className="w-full px-3 py-2 rounded-lg border border-slate-600 bg-slate-700/50 text-white text-sm focus:outline-none focus:border-blue-400" />
                            </div>
                            <div>
                                <label className="text-xs text-slate-400 block mb-1">Collection Type</label>
                                <select name="collectionType"
                                    className="w-full px-3 py-2 rounded-lg border border-slate-600 bg-slate-700/50 text-white text-sm focus:outline-none focus:border-blue-400">
                                    <option value="">Standard</option>
                                    <option value="principal">Principal</option>
                                    <option value="interest">Interest</option>
                                    <option value="penalty">Penalty</option>
                                </select>
                            </div>
                            <div>
                                <label className="text-xs text-slate-400 block mb-1">Notes</label>
                                <textarea name="notes" rows={2}
                                    className="w-full px-3 py-2 rounded-lg border border-slate-600 bg-slate-700/50 text-white text-sm focus:outline-none focus:border-blue-400" />
                            </div>
                        </div>
                        <DialogFooter>
                            <DialogClose asChild>
                                <button type="button"
                                    className="px-4 py-2 rounded-lg border border-slate-600 text-slate-300 text-sm hover:bg-slate-700/50 transition-colors">
                                    Cancel
                                </button>
                            </DialogClose>
                            <button type="submit" disabled={createMutation.isPending}
                                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-blue-600 to-blue-500 text-white text-sm font-medium disabled:opacity-50 hover:opacity-90 transition-opacity">
                                {createMutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
                                Confirm & Create
                            </button>
                        </DialogFooter>
                    </form>
                </DialogContent>
            </Dialog>
        </div>
    )
}
