import { useState, useEffect, useMemo } from 'react'
import { Search, AlertCircle, FileText, Calendar, TrendingUp, CreditCard, RefreshCw } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { formatCurrency } from '@/lib/utils'

interface CollectionEntry {
    loanId: string
    customerId: string
    customerName: string
    branchCode?: string
    assignedCollectionsBranch?: string
    installmentNo: number
    dueDate: string
    principalDue: number
    interestDue: number
    penaltyDue: number
    totalDue: number
    amountPaid: number
    balanceDue: number
    dpd: number
    agingBucket: string
    collectionsOfficer?: string
}

export default function CollectionDuePage() {
    const { user } = useAuth()
    const isAdmin = user?.role === 'admin'
    const isBranchManager = user?.role === 'branch_manager'
    const isCollectionsOfficer = user?.role === 'collections_officer'
    const canAssign = isAdmin || isBranchManager
    const canFilter = isAdmin || isBranchManager

    const [loading, setLoading] = useState(true)
    const [entries, setEntries] = useState<CollectionEntry[]>([])
    const [datePreset, setDatePreset] = useState('today')
    const [customFrom, setCustomFrom] = useState('')
    const [customTo, setCustomTo] = useState('')
    const [search, setSearch] = useState('')
    const [selectedOfficer, setSelectedOfficer] = useState('')
    const [selectedBranch, setSelectedBranch] = useState('')
    const [officers, setOfficers] = useState<Array<{id: string, fullName: string}>>([])
    const [branches, setBranches] = useState<Array<{code: string, name: string}>>([])

    const getDateRange = () => {
        const today = new Date()
        const from = new Date(today)
        const to = new Date(today)
        switch (datePreset) {
            case 'today':
                break
            case 'week': {
                const dayOfWeek = today.getDay()
                from.setDate(today.getDate() - dayOfWeek)
                to.setDate(from.getDate() + 6)
                break
            }
            case 'month':
                from.setDate(1)
                to.setMonth(today.getMonth() + 1, 0)
                break
            case 'custom':
                return { from: customFrom ? new Date(customFrom) : from, to: customTo ? new Date(customTo) : to }
        }
        return { from, to }
    }

    const fetchData = async () => {
        setLoading(true)
        try {
            const token = localStorage.getItem('access_token')
            const { from, to } = getDateRange()

            const variables: Record<string, any> = {
                dueDateFrom: from.toISOString().split('T')[0],
                dueDateTo: to.toISOString().split('T')[0],
                limit: 1000,
                offset: 0,
            }
            if (canFilter && selectedBranch) variables.branchCode = selectedBranch
            if (canFilter && selectedOfficer) variables.collectionsOfficerId = selectedOfficer

            const res = await fetch('/graphql', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': token ? `Bearer ${token}` : ''
                },
                body: JSON.stringify({
                    query: `query GetCollectionsDue($branchCode: String, $collectionsOfficerId: String, $dueDateFrom: Date, $dueDateTo: Date, $limit: Int, $offset: Int) {
  collectionsDue(branchCode: $branchCode, collectionsOfficerId: $collectionsOfficerId, dueDateFrom: $dueDateFrom, dueDateTo: $dueDateTo, limit: $limit, offset: $offset) {
    entries {
      loanId customerId customerName branchCode assignedCollectionsBranch installmentNo dueDate principalDue interestDue penaltyDue totalDue amountPaid balanceDue dpd agingBucket collectionsOfficer
    }
  }
}`,
                    variables,
                })
            })
            const data = await res.json()
            setEntries(data.data?.collectionsDue?.entries || [])
        } catch (e) {
            console.error('Failed to fetch collections due:', e)
        } finally {
            setLoading(false)
        }
    }

    const fetchFilterData = async () => {
        const token = localStorage.getItem('access_token')
        try {
            if (canFilter) {
                const officerRes = await fetch('/graphql', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': token ? `Bearer ${token}` : '' },
                    body: JSON.stringify({
                        query: `query { usersByRole(role: "collections_officer") { id fullName } }`
                    })
                })
                const officerData = await officerRes.json()
                setOfficers(officerData.data?.usersByRole || [])
            }
            if (isAdmin) {
                const branchRes = await fetch('/graphql', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': token ? `Bearer ${token}` : '' },
                    body: JSON.stringify({
                        query: `query { branches { code name } }`
                    })
                })
                const branchData = await branchRes.json()
                setBranches(branchData.data?.branches || [])
            }
        } catch (e) {
            console.error('Failed to fetch filter data:', e)
        }
    }

    useEffect(() => {
        fetchFilterData()
    }, [])

    // Fetch on mount + whenever date preset or filters change
    useEffect(() => {
        if (datePreset !== 'custom') {
            fetchData()
        }
    }, [datePreset, selectedOfficer, selectedBranch])

    const assignOfficer = async (loanId: string, officerId: string) => {
        const token = localStorage.getItem('access_token')
        try {
            await fetch('/graphql', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': token ? `Bearer ${token}` : '' },
                body: JSON.stringify({
                    query: `mutation ($loanId: ID!, $collectionsOfficerId: String) {
                        assignLoanCollectionsOfficer(loanId: $loanId, collectionsOfficerId: $collectionsOfficerId) { success message }
                    }`,
                    variables: { loanId, collectionsOfficerId: officerId || null }
                })
            })
            fetchData()
        } catch (e) {
            console.error('Failed to assign officer:', e)
        }
    }

    const assignBranch = async (loanId: string, branchCode: string) => {
        const token = localStorage.getItem('access_token')
        try {
            await fetch('/graphql', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': token ? `Bearer ${token}` : '' },
                body: JSON.stringify({
                    query: `mutation ($loanId: ID!, $branchCode: String) {
                        assignLoanCollectionsBranch(loanId: $loanId, branchCode: $branchCode) { success message }
                    }`,
                    variables: { loanId, branchCode: branchCode || null }
                })
            })
            fetchData()
        } catch (e) {
            console.error('Failed to assign branch:', e)
        }
    }

    const searchFiltered = useMemo(() => {
        if (!search.trim()) return entries
        const q = search.toLowerCase()
        return entries.filter(e =>
            e.customerName?.toLowerCase().includes(q) ||
            e.customerId.toLowerCase().includes(q) ||
            e.loanId.toLowerCase().includes(q)
        )
    }, [entries, search])

    const totalBalanceDue = searchFiltered.reduce((sum, e) => sum + e.balanceDue, 0)
    const overdueCount = searchFiltered.filter(e => e.dpd > 0).length
    const dueTodayCount = searchFiltered.filter(e => e.dpd === 0).length
    const totalPrincipalDue = searchFiltered.reduce((sum, e) => sum + e.principalDue, 0)

    const getDpdColor = (dpd: number) => {
        if (dpd > 30) return 'text-red-400'
        if (dpd > 0) return 'text-amber-400'
        return 'text-emerald-400'
    }

    const getAgingBadge = (bucket: string) => {
        const colors: { [key: string]: string } = {
            'current': 'bg-emerald-500/20 text-emerald-400',
            '1-30_days': 'bg-amber-500/20 text-amber-400',
            '31-60_days': 'bg-orange-500/20 text-orange-400',
            '61-90_days': 'bg-red-500/20 text-red-400',
            '90+_days': 'bg-rose-500/20 text-rose-400'
        }
        return colors[bucket] || 'bg-gray-500/20 text-gray-400'
    }

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 space-y-6 animate-fade-in p-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white">Due Collections</h1>
                    <p className="text-slate-400 text-sm mt-1">Loan repayment schedule and receivables overview</p>
                </div>
                <div className="flex gap-2">
                    {(canFilter || isCollectionsOfficer) && (
                        <button className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-blue-600 to-blue-500 text-white text-sm font-medium shadow-lg hover:opacity-90 transition-opacity">
                            <FileText className="w-4 h-4" /> Generate Report
                        </button>
                    )}
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="glass rounded-xl p-4 border border-slate-700/50">
                    <div className="flex items-center gap-3">
                        <div className="p-2 rounded-lg bg-amber-500/20">
                            <Calendar className="w-5 h-5 text-amber-400" />
                        </div>
                        <div>
                            <p className="text-xs text-slate-400 uppercase tracking-wider">Total Balance Due</p>
                            <p className="text-lg font-bold text-white">{formatCurrency(totalBalanceDue)}</p>
                        </div>
                    </div>
                </div>
                <div className="glass rounded-xl p-4 border border-slate-700/50">
                    <div className="flex items-center gap-3">
                        <div className="p-2 rounded-lg bg-red-500/20">
                            <AlertCircle className="w-5 h-5 text-red-400" />
                        </div>
                        <div>
                            <p className="text-xs text-slate-400 uppercase tracking-wider">Overdue</p>
                            <p className="text-lg font-bold text-white">{overdueCount}</p>
                        </div>
                    </div>
                </div>
                <div className="glass rounded-xl p-4 border border-slate-700/50">
                    <div className="flex items-center gap-3">
                        <div className="p-2 rounded-lg bg-blue-500/20">
                            <CreditCard className="w-5 h-5 text-blue-400" />
                        </div>
                        <div>
                            <p className="text-xs text-slate-400 uppercase tracking-wider">Principal Due</p>
                            <p className="text-lg font-bold text-white">{formatCurrency(totalPrincipalDue)}</p>
                        </div>
                    </div>
                </div>
                <div className="glass rounded-xl p-4 border border-slate-700/50">
                    <div className="flex items-center gap-3">
                        <div className="p-2 rounded-lg bg-emerald-500/20">
                            <TrendingUp className="w-5 h-5 text-emerald-400" />
                        </div>
                        <div>
                            <p className="text-xs text-slate-400 uppercase tracking-wider">Due Today</p>
                            <p className="text-lg font-bold text-white">{dueTodayCount}</p>
                        </div>
                    </div>
                </div>
            </div>

            <div className="flex gap-2 flex-wrap">
                {['today', 'week', 'month', 'custom'].map(preset => (
                    <button
                        key={preset}
                        onClick={() => setDatePreset(preset)}
                        className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                            datePreset === preset
                                ? 'bg-blue-600 text-white'
                                : 'bg-slate-800/50 text-slate-300 border border-slate-600 hover:bg-slate-700/50'
                        }`}
                    >
                        {preset === 'today' ? 'Today' : preset === 'week' ? 'This Week' : preset === 'month' ? 'This Month' : 'Custom'}
                    </button>
                ))}
                {datePreset === 'custom' && (
                    <>
                        <input type="date" value={customFrom} onChange={e => setCustomFrom(e.target.value)}
                            className="px-2 py-1.5 rounded-lg border border-slate-600 bg-slate-800/50 text-slate-200 text-sm" />
                        <input type="date" value={customTo} onChange={e => setCustomTo(e.target.value)}
                            className="px-2 py-1.5 rounded-lg border border-slate-600 bg-slate-800/50 text-slate-200 text-sm" />
                    </>
                )}
                {canFilter && officers.length > 0 && (
                    <select value={selectedOfficer} onChange={e => setSelectedOfficer(e.target.value)}
                        className="px-3 py-1.5 rounded-lg border border-slate-600 bg-slate-800/50 text-slate-200 text-sm">
                        <option value="">All Officers</option>
                        {officers.map(o => (
                            <option key={o.id} value={o.id}>{o.fullName}</option>
                        ))}
                    </select>
                )}
                {isAdmin && branches.length > 0 && (
                    <select value={selectedBranch} onChange={e => setSelectedBranch(e.target.value)}
                        className="px-3 py-1.5 rounded-lg border border-slate-600 bg-slate-800/50 text-slate-200 text-sm">
                        <option value="">All Branches</option>
                        {branches.map(b => (
                            <option key={b.code} value={b.code}>{b.name}</option>
                        ))}
                    </select>
                )}
                <button onClick={fetchData} className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-600 bg-slate-800/50 hover:bg-slate-700/50 text-slate-200 text-sm transition-colors">
                    <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                </button>
            </div>

            {loading ? (
                <div className="text-center py-16 text-slate-400">Loading collections…</div>
            ) : (
                <div className="glass rounded-xl overflow-hidden border border-slate-700/50">
                    <div className="p-4 border-b border-slate-700/50">
                        <div className="relative">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                            <input
                                value={search}
                                onChange={e => setSearch(e.target.value)}
                                placeholder="Search by customer, ID, or reference..."
                                className="w-full pl-10 pr-4 py-2 rounded-lg border border-slate-600 bg-slate-800/50 focus:outline-none focus:border-blue-400 text-slate-200"
                            />
                        </div>
                    </div>
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-slate-700/50">
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Customer</th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Loan ID</th>
                                <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Total Due</th>
                                <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Balance Due</th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Due Date</th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">DPD</th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Status</th>
                                {canAssign && (
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Collections Officer</th>
                                )}
                                {canAssign && (
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Branch</th>
                                )}
                            </tr>
                        </thead>
                        <tbody>
                            {searchFiltered.length === 0 ? (
                                <tr><td colSpan={9} className="text-center py-12 text-slate-400">No due collections found</td></tr>
                            ) : searchFiltered.map((entry) => (
                                <tr key={entry.loanId} className="border-b border-slate-700/30 hover:bg-slate-800/50 transition-colors">
                                    <td className="px-4 py-3 text-white font-medium">{entry.customerName || entry.customerId}</td>
                                    <td className="px-4 py-3 text-slate-400 font-mono text-xs">{entry.loanId.slice(-8).toUpperCase()}</td>
                                    <td className="px-4 py-3 text-white font-medium text-right">{formatCurrency(entry.totalDue)}</td>
                                    <td className="px-4 py-3 text-white font-medium text-right">{formatCurrency(entry.balanceDue)}</td>
                                    <td className="px-4 py-3 text-slate-400">{new Date(entry.dueDate).toLocaleDateString()}</td>
                                    <td className="px-4 py-3">
                                        <span className={`text-xs font-medium ${getDpdColor(entry.dpd)}`}>
                                            {entry.dpd > 0 ? `${entry.dpd} days overdue` : entry.dpd === 0 ? 'Due today' : `${Math.abs(entry.dpd)} days`}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3">
                                        <span className={`text-xs px-2 py-1 rounded-full ${getAgingBadge(entry.agingBucket)}`}>
                                            {entry.agingBucket.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                                        </span>
                                    </td>
                                    {canAssign && (
                                        <td className="px-4 py-3">
                                            <select
                                                value={entry.collectionsOfficer || ''}
                                                onChange={e => assignOfficer(entry.loanId, e.target.value)}
                                                className="text-xs px-1 py-0.5 rounded border border-slate-600 bg-slate-800/50 text-slate-200"
                                            >
                                                <option value="">Unassigned</option>
                                                {officers.map(o => (
                                                    <option key={o.id} value={o.id}>{o.fullName}</option>
                                                ))}
                                            </select>
                                        </td>
                                    )}
                                    {canAssign && (
                                        <td className="px-4 py-3">
                                            <select
                                                value={entry.assignedCollectionsBranch || ''}
                                                onChange={e => assignBranch(entry.loanId, e.target.value)}
                                                className="text-xs px-1 py-0.5 rounded border border-slate-600 bg-slate-800/50 text-slate-200"
                                            >
                                                <option value="">Unassigned</option>
                                                {branches.map(b => (
                                                    <option key={b.code} value={b.code}>{b.name}</option>
                                                ))}
                                            </select>
                                        </td>
                                    )}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    )
}
