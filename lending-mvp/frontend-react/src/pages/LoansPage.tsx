import { useState, useEffect } from 'react'
import { formatCurrency } from '@/lib/utils'
import { Search, Plus, UserCog, X } from 'lucide-react'
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

export default function LoansPage() {
    const { user } = useAuth()
    const navigate = useNavigate()
    const canCreateLoan = user?.role === 'admin' || user?.role === 'branch_manager'
    const canAssign = user?.role === 'admin' || user?.role === 'branch_manager'

    const [loading, setLoading] = useState(true)
    const [loansData, setLoansData] = useState<Loan[]>([])
    const [search, setSearch] = useState('')
    const [officers, setOfficers] = useState<Array<{id: string, fullName: string}>>([])
    const [branches, setBranches] = useState<Array<{code: string, name: string}>>([])

    const [assignTarget, setAssignTarget] = useState<Loan | null>(null)
    const [assignOfficerId, setAssignOfficerId] = useState('')
    const [assignBranchCode, setAssignBranchCode] = useState('')
    const [saving, setSaving] = useState(false)

    const officerMap = Object.fromEntries(officers.map(o => [o.id, o.fullName]))
    const branchMap = Object.fromEntries(branches.map(b => [b.code, b.name]))

    const filteredLoans = loansData.filter(loan => 
        loan.borrowerName.toLowerCase().includes(search.toLowerCase()) ||
        loan.productName.toLowerCase().includes(search.toLowerCase()) ||
        loan.id.toLowerCase().includes(search.toLowerCase()) ||
        loan.status.toLowerCase().includes(search.toLowerCase())
    )

    const openAssign = async (loan: Loan) => {
        // Await data fetch so modal appears with officers already populated
        await fetchModalData()
        setAssignTarget(loan)
        setAssignBranchCode(loan.assignedCollectionsBranch || '')
        setAssignOfficerId(loan.collectionsOfficer || '')
    }

    const fetchModalData = async () => {
        const token = localStorage.getItem('access_token')
        const headers = { 'Content-Type': 'application/json', 'Authorization': token ? `Bearer ${token}` : '' }
        try {
            const [officerRes, branchRes] = await Promise.all([
                fetch('/graphql', {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({ query: `query { usersByRole(role: "collections_officer") { id fullName } }` })
                }),
                fetch('/graphql', {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({ query: `query { branches { code name } }` })
                })
            ])
            const [officerData, branchData] = await Promise.all([
                officerRes.json(),
                branchRes.json()
            ])
            // Log GraphQL errors silently so they don't break the UX but are visible in devtools
            if (officerData.errors) {
                console.warn('GraphQL errors fetching officers:', officerData.errors)
            }
            if (branchData.errors) {
                console.warn('GraphQL errors fetching branches:', branchData.errors)
            }
            setOfficers(officerData.data?.usersByRole || [])
            setBranches(branchData.data?.branches || [])
        } catch (e) {
            console.error('Failed to fetch modal data:', e)
        }
    }

    const saveAssign = async () => {
        if (!assignTarget) return
        setSaving(true)
        const token = localStorage.getItem('access_token')
        try {
            const [officerRes, branchRes] = await Promise.all([
                fetch('/graphql', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': token ? `Bearer ${token}` : '' },
                    body: JSON.stringify({
                        query: `mutation ($loanId: ID!, $collectionsOfficerId: String) {
                            assignLoanCollectionsOfficer(loanId: $loanId, collectionsOfficerId: $collectionsOfficerId) { success message }
                        }`,
                        variables: { loanId: assignTarget.id, collectionsOfficerId: assignOfficerId || null }
                    })
                }).then(r => r.json()),
                fetch('/graphql', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': token ? `Bearer ${token}` : '' },
                    body: JSON.stringify({
                        query: `mutation ($loanId: ID!, $branchCode: String) {
                            assignLoanCollectionsBranch(loanId: $loanId, branchCode: $branchCode) { success message }
                        }`,
                        variables: { loanId: assignTarget.id, branchCode: assignBranchCode || null }
                    })
                }).then(r => r.json())
            ])
            if (officerRes.data?.assignLoanCollectionsOfficer?.success === false) {
                console.error('Failed to assign officer:', officerRes.data.assignLoanCollectionsOfficer.message)
                return
            }
            if (branchRes.data?.assignLoanCollectionsBranch?.success === false) {
                console.error('Failed to assign branch:', branchRes.data.assignLoanCollectionsBranch.message)
                return
            }
            setAssignTarget(null)
            await init()
        } catch (e) {
            console.error('Failed to assign:', e)
        } finally {
            setSaving(false)
        }
    }

    const init = async () => {
        try {
            const loansRes = await getLoans()
            setLoansData(loansRes.data?.loans?.loans || [])
        } catch (e) {
            console.error('Failed to fetch loans:', e)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        init()
        fetchModalData()
    }, [])

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
        <div className="space-y-6 animate-fade-in">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-foreground">Loans</h1>
                    <p className="text-muted-foreground text-sm mt-1">Manage loan applications</p>
                </div>
                {canCreateLoan && (
                    <button 
                        onClick={() => navigate('/customer/loans/new')}
                        className="flex items-center gap-2 px-4 py-2 rounded-lg gradient-primary text-white text-sm font-medium shadow-lg hover:opacity-90 transition-opacity"
                    >
                        <Plus className="w-4 h-4" /> New Loan
                    </button>
                )}
            </div>

            {loading ? (
                <div className="text-center py-16 text-muted-foreground">Loading loans…</div>
            ) : (
                <div className="glass rounded-xl overflow-hidden">
                    <div className="p-4 border-b border-border/50">
                        <div className="relative">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search loans..." className="w-full pl-10 pr-4 py-2 rounded-lg border border-border bg-background/50 focus:outline-none focus:border-primary/50" />
                        </div>
                    </div>
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-border/50">
                                <th className="text-left px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Borrower</th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Product</th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Amount</th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Status</th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Term</th>
                                {canAssign && (
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Assignment</th>
                                )}
                            </tr>
                        </thead>
                        <tbody>
                            {filteredLoans.length === 0 ? (
                                <tr><td colSpan={canAssign ? 7 : 5} className="text-center py-12 text-muted-foreground">No loans found.</td></tr>
                            ) : filteredLoans.map((loan) => (
                                <tr 
                                    key={loan.id} 
                                    onClick={() => navigate(`/loans/${loan.id}`)}
                                    className="border-b border-border/30 hover:bg-white/5 transition-colors cursor-pointer"
                                >
                                    <td className="px-4 py-3">
                                        <div className="font-medium text-foreground">{loan.borrowerName}</div>
                                        <div className="text-xs text-muted-foreground">{loan.customerId}</div>
                                    </td>
                                    <td className="px-4 py-3">
                                        <div className="font-medium text-foreground">{loan.productName}</div>
                                        <div className="text-xs text-muted-foreground">{loan.productId}</div>
                                    </td>
                                    <td className="px-4 py-3 text-foreground font-medium">
                                        {loan.principal ? formatCurrency(loan.principal) : '—'}
                                    </td>
                                    <td className="px-4 py-3">
                                        <span className={`text-xs px-2 py-1 rounded-full ${getStatusColor(loan.status)}`}>
                                            {loan.status.charAt(0).toUpperCase() + loan.status.slice(1)}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3 text-muted-foreground">{loan.termMonths} months</td>
                                    {canAssign && (
                                        <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                                            <div className="flex items-center gap-2">
                                                <div className="flex-1 min-w-0">
                                                    <div className="text-xs text-foreground truncate">
                                                        {loan.collectionsOfficer ? officerMap[loan.collectionsOfficer] || loan.collectionsOfficer : '—'}
                                                    </div>
                                                    <div className="text-xs text-muted-foreground truncate">
                                                        {loan.assignedCollectionsBranch ? branchMap[loan.assignedCollectionsBranch] || loan.assignedCollectionsBranch : '—'}
                                                    </div>
                                                </div>
                                                <button
                                                    onClick={() => openAssign(loan)}
                                                    className="p-1.5 rounded-lg hover:bg-white/10 text-muted-foreground hover:text-foreground transition-colors"
                                                    title="Assign officer &amp; branch"
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
                    <div className="glass rounded-xl p-6 w-full max-w-md border border-border/50 shadow-2xl" onClick={e => e.stopPropagation()}>
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="text-lg font-bold text-foreground">Assign Collections</h2>
                            <button onClick={() => setAssignTarget(null)} className="p-1 rounded-lg hover:bg-white/10 text-muted-foreground transition-colors">
                                <X className="w-5 h-5" />
                            </button>
                        </div>
                        <div className="space-y-3 mb-2 text-sm text-muted-foreground">
                            <p>Loan: <span className="text-foreground font-medium">{assignTarget.id}</span></p>
                            <p>Borrower: <span className="text-foreground font-medium">{assignTarget.borrowerName}</span></p>
                        </div>
                        <div className="space-y-4">
                            <div>
                                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Collections Officer</label>
                                <select
                                    value={assignOfficerId}
                                    onChange={e => setAssignOfficerId(e.target.value)}
                                    className="w-full px-3 py-2 rounded-lg border border-border bg-background/50 text-foreground text-sm focus:outline-none focus:border-primary/50"
                                >
                                    <option value="">Unassigned</option>
                                    {officers.map(o => (
                                        <option key={o.id} value={o.id}>{o.fullName}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Branch / Area</label>
                                <select
                                    value={assignBranchCode}
                                    onChange={e => setAssignBranchCode(e.target.value)}
                                    className="w-full px-3 py-2 rounded-lg border border-border bg-background/50 text-foreground text-sm focus:outline-none focus:border-primary/50"
                                >
                                    <option value="">Unassigned</option>
                                    {branches.map(b => (
                                        <option key={b.code} value={b.code}>{b.name}</option>
                                    ))}
                                </select>
                            </div>
                            <div className="flex gap-2 justify-end pt-2">
                                <button
                                    onClick={() => setAssignTarget(null)}
                                    disabled={saving}
                                    className="px-4 py-2 rounded-lg border border-border text-sm text-muted-foreground hover:bg-white/5 transition-colors disabled:opacity-50"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={saveAssign}
                                    disabled={saving}
                                    className="px-4 py-2 rounded-lg gradient-primary text-white text-sm font-medium shadow-lg hover:opacity-90 transition-opacity disabled:opacity-50"
                                >
                                    {saving ? 'Saving...' : 'Save'}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
