import { useState, useEffect } from 'react'
import { Search, FileText, RefreshCw, Loader2, AlertCircle } from 'lucide-react'

interface TrialBalanceRow {
    code: string
    name: string
    type: string
    totalDebit: number
    totalCredit: number
    balance: number
}

interface TrialBalanceReport {
    asOf: string
    rows: TrialBalanceRow[]
    totalDebit: number
    totalCredit: number
    rowCount: number
}

function fetchGraphQL(query: string, variables: Record<string, any> = {}) {
    const token = localStorage.getItem('access_token')
    return fetch('/graphql', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: token ? `Bearer ${token}` : '' },
        body: JSON.stringify({ query, variables }),
    }).then((res) => res.json())
}

const TYPE_LABELS: Record<string, string> = {
    asset: 'Asset', liability: 'Liability', equity: 'Equity', income: 'Income', expense: 'Expense',
}
const TYPE_COLORS: Record<string, string> = {
    asset: 'text-blue-400', liability: 'text-red-400', equity: 'text-emerald-400',
    income: 'text-green-400', expense: 'text-amber-400',
}

export default function TrialBalancePage() {
    const [loading, setLoading] = useState(true)
    const [data, setData] = useState<TrialBalanceReport | null>(null)
    const [asOf, setAsOf] = useState(new Date().toISOString().split('T')[0])
    const [error, setError] = useState<string | null>(null)
    const [filterType, setFilterType] = useState('')
    const [search, setSearch] = useState('')

    const fetchData = async () => {
        setLoading(true)
        setError(null)
        try {
            const result = await fetchGraphQL(
                `query TrialBalance($asOf: Date) {
                    trialBalance(asOf: $asOf) { asOf totalDebit totalCredit rowCount rows { code name type totalDebit totalCredit balance } }
                }`, { asOf }
            )
            if (result.errors) throw new Error(result.errors[0].message)
            setData(result.data?.trialBalance || null)
        } catch (e: any) {
            setError(e.message || 'Failed to load trial balance')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => { fetchData() }, [])

    const filteredRows = (data?.rows || []).filter(r => {
        if (filterType && r.type !== filterType) return false
        if (search) {
            const q = search.toLowerCase()
            if (!r.code.toLowerCase().includes(q) && !r.name.toLowerCase().includes(q)) return false
        }
        return true
    })

    const fmt = (n: number) => new Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP', minimumFractionDigits: 2 }).format(n)

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 space-y-6 animate-fade-in p-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white">Trial Balance</h1>
                    <p className="text-slate-400 text-sm mt-1">General ledger account balances as of a specific date</p>
                </div>
            </div>

            <div className="glass rounded-xl p-4 border border-slate-700/50">
                <div className="flex flex-wrap items-center gap-4">
                    <div>
                        <label className="block text-xs text-slate-400 mb-1">As of Date</label>
                        <input type="date" value={asOf} onChange={e => setAsOf(e.target.value)}
                            className="px-3 py-2 bg-slate-800/50 border border-slate-600 rounded-lg text-slate-200 text-sm" />
                    </div>
                    <div>
                        <label className="block text-xs text-slate-400 mb-1">Account Type</label>
                        <select value={filterType} onChange={e => setFilterType(e.target.value)}
                            className="px-3 py-2 bg-slate-800/50 border border-slate-600 rounded-lg text-slate-200 text-sm">
                            <option value="">All Types</option>
                            {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                        </select>
                    </div>
                    <div>
                        <label className="block text-xs text-slate-400 mb-1">Search</label>
                        <div className="relative">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Code or name..."
                                className="pl-9 pr-3 py-2 bg-slate-800/50 border border-slate-600 rounded-lg text-slate-200 text-sm w-48" />
                        </div>
                    </div>
                    <div className="flex-1" />
                    <button onClick={fetchData}
                        className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-white text-sm font-medium transition-colors">
                        <FileText className="w-4 h-4" /> Generate
                    </button>
                </div>
            </div>

            {error && <div className="flex items-center gap-3 p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm"><AlertCircle className="w-5 h-5" />{error}</div>}

            {loading ? (
                <div className="flex items-center justify-center py-16 text-slate-400"><Loader2 className="w-5 h-5 animate-spin mr-2" />Loading trial balance...</div>
            ) : !data || data.rows.length === 0 ? (
                <div className="text-center py-16 text-slate-400">No data for this period.</div>
            ) : (
                <div className="glass rounded-xl overflow-hidden border border-slate-700/50">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-slate-700/50">
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Code</th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Account</th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Type</th>
                                <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Total Debit</th>
                                <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Total Credit</th>
                                <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Balance</th>
                            </tr>
                        </thead>
                        <tbody>
                            {filteredRows.map(row => (
                                <tr key={row.code} className="border-b border-slate-700/30 hover:bg-slate-800/50 transition-colors">
                                    <td className="px-4 py-3 font-mono text-white">{row.code}</td>
                                    <td className="px-4 py-3 text-white">{row.name}</td>
                                    <td className={`px-4 py-3 ${TYPE_COLORS[row.type] || 'text-slate-400'}`}>{TYPE_LABELS[row.type] || row.type}</td>
                                    <td className="px-4 py-3 text-right text-green-400 font-mono">{row.totalDebit > 0 ? fmt(row.totalDebit) : '\u2014'}</td>
                                    <td className="px-4 py-3 text-right text-red-400 font-mono">{row.totalCredit > 0 ? fmt(row.totalCredit) : '\u2014'}</td>
                                    <td className={`px-4 py-3 text-right font-mono font-medium ${row.balance >= 0 ? 'text-white' : 'text-red-400'}`}>{fmt(row.balance)}</td>
                                </tr>
                            ))}
                        </tbody>
                        <tfoot>
                            <tr className="border-t-2 border-slate-600 bg-slate-800/50 font-semibold">
                                <td colSpan={3} className="px-4 py-3 text-right text-white">Totals</td>
                                <td className="px-4 py-3 text-right text-green-400 font-mono">{fmt(data.totalDebit)}</td>
                                <td className="px-4 py-3 text-right text-red-400 font-mono">{fmt(data.totalCredit)}</td>
                                <td className="px-4 py-3 text-right text-slate-400 font-mono">
                                    {data.totalDebit === data.totalCredit ? '\u2713 Balanced' : '\u2717 Unbalanced'}
                                </td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
            )}
        </div>
    )
}
