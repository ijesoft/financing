import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { formatCurrency } from '@/lib/utils'
import { Search, Plus, UserCog, X, Loader2 } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { getLoans } from '@/api/loans'
import { useNavigate } from 'react-router-dom'

interface Loan {
    id: string
    principal: number
    status: string
    customerId: string
    productId: string
    borrowerName: string
    productName: string
    termMonths: number
    approvedPrincipal?: number
    approvedRate?: number
    createdAt: string
    disbursedAt?: string
    outstandingBalance?: number
    collectionsOfficer?: string
    assignedCollectionsBranch?: string
}

interface DropdownItem {
    id: string
    fullName: string
}

interface BranchItem {
    code: string
    name: string
}

const OFFICERS_QUERY = `query { usersByRole(role: "collections_officer") { id fullName } }`
const BRANCHES_QUERY = `query { branches { code name } }`

async function fetchDropdowns(): Promise<{ officers: DropdownItem[]; branches: BranchItem[] }> {
    const token = localStorage.getItem('access_token')
    const headers = { 'Content-Type': 'application/json', 'Authorization': token ? `Bearer ${token}` : '' }
    const [officerRes, branchRes] = await Promise.all([
        fetch('/graphql', { method: 'POST', headers, body: JSON.stringify({ query: OFFICERS_QUERY }) }),
        fetch('/graphql', { method: 'POST', headers, body: JSON.stringify({ query: BRANCHES_QUERY }) }),
    ])
    const [officerData, branchData] = await Promise.all([officerRes.json(), branchRes.json()])
    return {
        officers: officerData.data?.usersByRole || [],
        branches: branchData.data?.branches || [],
    }
}

export default function LoansPage() {
    const { user } = useAuth()
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const canCreateLoan = user?.role === 'admin' || user?.role === 'branch_manager'
    const canAssign = user?.role === 'admin' || user?.role === 'branch_manager'

    const [search, setSearch] = useState('')
    const [assignTarget, setAssignTarget] = useState<Loan | null>(null)
    const [assignOfficerId, setAssignOfficerId] = useState('')
    const [assignBranchCode, setAssignBranchCode] = useState('')

    const { data: loansData, isLoading } = useQuery({
        queryKey: ['loans'],
        queryFn: () => getLoans().then(r => r.data?.loans?.loans || []),
        staleTime: 30_000,
        refetchOnWindowFocus: true,
    })

    const { data: dropdowns } = useQuery({
        queryKey: ['dropdowns', 'collections'],
        queryFn: fetchDropdowns,
        staleTime: 300_000,
    })

    const officers = dropdowns?.officers ?? []
    const branches = dropdowns?.branches ?? []
    const loans = loansData ?? []
    const officerMap = Object.fromEntries(officers.map((o: DropdownItem) => [o.id, o.fullName]))
    const branchMap = Object.fromEntries(branches.map((b: BranchItem) => [b.code, b.name]))

    const filteredLoans = loans.filter((loan: Loan) =>
        loan.borrowerName.toLowerCase().includes(search.toLowerCase()) ||
        loan.productName.toLowerCase().includes(search.toLowerCase()) ||
        loan.id.toLowerCase().includes(search.toLowerCase()) ||
        loan.status.toLowerCase().includes(search.toLowerCase())
    )

    const assignMutation = useMutation({
        mutationFn: async ({ loanId, officerId, branchCode }: { loanId: string; officerId: string; branchCode: string }) => {
            const token = localStorage.getItem('access_token')
            const headers = { 'Content-Type': 'application/json', 'Authorization': token ? `Bearer ${token}` : '' }
            const [officerRes, branchRes] = await Promise.all([
                fetch('/graphql', {
                    method: 'POST', headers,
                    body: JSON.stringify({
                        query: `mutation ($loanId: ID!, $collectionsOfficerId: String) {
                            assignLoanCollectionsOfficer(loanId: $loanId, collectionsOfficerId: $collectionsOfficerId) { success message }
                        }`,
                        variables: { loanId, collectionsOfficerId: officerId || null }
                    })
                }).then(r => r.json()),
                fetch('/graphql', {
                    method: 'POST', headers,
                    body: JSON.stringify({
                        query: `mutation ($loanId: ID!, $branchCode: String) {
                            assignLoanCollectionsBranch(loanId: $loanId, branchCode: $branchCode) { success message }
                        }`,
                        variables: { loanId, branchCode: branchCode || null }
                    })
                }).then(r => r.json())
            ])
            if (officerRes.data?.assignLoanCollectionsOfficer?.success === false)
                throw new Error(officerRes.data.assignLoanCollectionsOfficer.message)
            if (branchRes.data?.assignLoanCollectionsBranch?.success === false)
                throw new Error(branchRes.data.assignLoanCollectionsBranch.message)
        },
        onSuccess: () => {
            setAssignTarget(null)
            queryClient.invalidateQueries({ queryKey: ['loans'] })
        },
    })

    const openAssign = (loan: Loan) => {
        setAssignTarget(loan)
        setAssignBranchCode(loan.assignedCollectionsBranch || '')
        setAssignOfficerId(loan.collectionsOfficer || '')
    }

    const getStatusColor = (status: string) => {
        const colors: { [key: string]: string } = {
            'pending': 'text-amber-400',
            'approved': 'text-emerald-400',
            'disbursed': 'text-blue-400',
            'repaid': 'text-emerald-400',
            'default': 'text-red-400',
            'written_off': 'text-red-500'
        }
        return colors[status] || 'text-muted-foreground'
    }

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 space-y-6 animate-fade-in p-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white">Loans</h1>
                    <p className="text-slate-400 text-sm mt-1">Manage loan applications and collections assignments</p>
                </div>
                {canCreateLoan && (
                    <button
                        onClick={() => navigate('/customer/loans/new')}
                        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-blue-600 to-blue-500 text-white text-sm font-medium shadow-lg hover:opacity-90 transition-opacity"
                    >
                        <Plus className="w-4 h-4" /> New Loan
                    </button>
                )}
            </div>

            <div className="glass rounded-xl p-4 border border-slate-700/50">
                <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                    <input value={search} onChange={e => setSearch(e.target.value)}
                        placeholder="Search loans..."
                        className="w-full pl-10 pr-4 py-2 rounded-lg border border-slate-600 bg-slate-800/50 focus:outline-none focus:border-blue-400 text-slate-200" />
                </div>
            </div>

            {isLoading ? (
                <div className="flex items-center justify-center py-16 text-slate-400">
                    <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading loans...
                </div>
            ) : (
                <div className="glass rounded-xl overflow-hidden border border-slate-700/50">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-slate-700/50">
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Borrower</th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Product</th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Amount</th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Status</th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Term</th>
                                {canAssign && (
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Assignment</th>
                                )}
                            </tr>
                        </thead>
                        <tbody>
                            {filteredLoans.length === 0 ? (
                                <tr><td colSpan={canAssign ? 7 : 5} className="text-center py-12 text-slate-400">No loans found.</td></tr>
                            ) : filteredLoans.map((loan: Loan) => (
                                <tr
                                    key={loan.id}
                                    onClick={() => navigate(`/loans/${loan.id}`)}
                                    className="border-b border-slate-700/30 hover:bg-slate-800/50 transition-colors cursor-pointer"
                                >
                                    <td className="px-4 py-3">
                                        <div className="font-medium text-white">{loan.borrowerName}</div>
                                        <div className="text-xs text-slate-500">{loan.customerId}</div>
                                    </td>
                                    <td className="px-4 py-3">
                                        <div className="font-medium text-white">{loan.productName}</div>
                                        <div className="text-xs text-slate-500">{loan.productId}</div>
                                    </td>
                                    <td className="px-4 py-3 text-white font-medium">
                                        {loan.principal ? formatCurrency(loan.principal) : '—'}
                                    </td>
                                    <td className="px-4 py-3">
                                        <span className={`text-xs px-2 py-1 rounded-full ${getStatusColor(loan.status)}`}>
                                            {loan.status.charAt(0).toUpperCase() + loan.status.slice(1)}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3 text-slate-400">{loan.termMonths} months</td>
                                    {canAssign && (
                                        <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                                            <div className="flex items-center gap-2">
                                                <div className="flex-1 min-w-0">
                                                    <div className="text-xs text-slate-300 truncate">
                                                        {loan.collectionsOfficer ? officerMap[loan.collectionsOfficer] || loan.collectionsOfficer : '—'}
                                                    </div>
                                                    <div className="text-xs text-slate-500 truncate">
                                                        {loan.assignedCollectionsBranch ? branchMap[loan.assignedCollectionsBranch] || loan.assignedCollectionsBranch : '—'}
                                                    </div>
                                                </div>
                                                <button
                                                    onClick={() => openAssign(loan)}
                                                    className="p-1.5 rounded-lg hover:bg-slate-700/50 text-slate-400 hover:text-white transition-colors"
                                                    title="Assign officer & branch"
                                                >
                                                    <UserCog className="w-4 h-4" />
                                                </button>
                                            </div>
                                        </td>
                                    )}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {assignTarget && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setAssignTarget(null)}>
                    <div className="glass rounded-xl p-6 w-full max-w-md border border-slate-700/50 shadow-2xl" onClick={e => e.stopPropagation()}>
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="text-lg font-bold text-white">Assign Collections</h2>
                            <button onClick={() => setAssignTarget(null)} className="p-1 rounded-lg hover:bg-slate-700/50 text-slate-400 transition-colors">
                                <X className="w-5 h-5" />
                            </button>
                        </div>
                        <div className="space-y-3 mb-2 text-sm text-slate-400">
                            <p>Loan: <span className="text-white font-medium">{assignTarget.id}</span></p>
                            <p>Borrower: <span className="text-white font-medium">{assignTarget.borrowerName}</span></p>
                        </div>
                        <div className="space-y-4">
                            <div>
                                <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Collections Officer</label>
                                <select
                                    value={assignOfficerId}
                                    onChange={e => setAssignOfficerId(e.target.value)}
                                    className="w-full px-3 py-2 rounded-lg border border-slate-600 bg-slate-800/50 text-white text-sm focus:outline-none focus:border-blue-400"
                                >
                                    <option value="">Unassigned</option>
                                    {officers.map((o: DropdownItem) => (
                                        <option key={o.id} value={o.id}>{o.fullName}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Branch / Area</label>
                                <select
                                    value={assignBranchCode}
                                    onChange={e => setAssignBranchCode(e.target.value)}
                                    className="w-full px-3 py-2 rounded-lg border border-slate-600 bg-slate-800/50 text-white text-sm focus:outline-none focus:border-blue-400"
                                >
                                    <option value="">Unassigned</option>
                                    {branches.map((b: BranchItem) => (
                                        <option key={b.code} value={b.code}>{b.name}</option>
                                    ))}
                                </select>
                            </div>
                            <div className="flex gap-2 justify-end pt-2">
                                <button
                                    onClick={() => setAssignTarget(null)}
                                    disabled={assignMutation.isPending}
                                    className="px-4 py-2 rounded-lg border border-slate-600 text-sm text-slate-300 hover:bg-slate-700/50 transition-colors disabled:opacity-50"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={() => assignMutation.mutate({ loanId: assignTarget.id, officerId: assignOfficerId, branchCode: assignBranchCode })}
                                    disabled={assignMutation.isPending}
                                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-blue-600 to-blue-500 text-white text-sm font-medium shadow-lg hover:opacity-90 transition-opacity disabled:opacity-50"
                                >
                                    {assignMutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
                                    {assignMutation.isPending ? 'Saving...' : 'Save'}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
