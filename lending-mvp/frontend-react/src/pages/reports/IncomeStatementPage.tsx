import { useState, useEffect } from 'react'
import { FileText, Loader2, AlertCircle } from 'lucide-react'

interface IncomeStatementRow {
    code: string
    name: string
    balance: number
}

interface IncomeStatementReport {
    year: number
    month: number
    revenueRows: IncomeStatementRow[]
    totalRevenue: number
    expenseRows: IncomeStatementRow[]
    totalExpenses: number
    netIncome: number
}

function fetchGraphQL(query: string, variables: Record<string, any> = {}) {
    const token = localStorage.getItem('access_token')
    return fetch('/graphql', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: token ? `Bearer ${token}` : '' },
        body: JSON.stringify({ query, variables }),
    }).then((res) => res.json())
}

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

export default function IncomeStatementPage() {
    const today = new Date()
    const [year, setYear] = useState(today.getFullYear())
    const [month, setMonth] = useState(today.getMonth())
    const [loading, setLoading] = useState(true)
    const [data, setData] = useState<IncomeStatementReport | null>(null)
    const [error, setError] = useState<string | null>(null)

    const fetchData = async () => {
        setLoading(true)
        setError(null)
        try {
            const result = await fetchGraphQL(
                `query IncomeStatement($year: Int!, $month: Int!) {
                    incomeStatement(year: $year, month: $month) { year month totalRevenue totalExpenses netIncome revenueRows { code name balance } expenseRows { code name balance } }
                }`, { year, month }
            )
            if (result.errors) throw new Error(result.errors[0].message)
            setData(result.data?.incomeStatement || null)
        } catch (e: any) {
            setError(e.message || 'Failed to load income statement')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => { fetchData() }, [])

    const fmt = (n: number) => new Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP', minimumFractionDigits: 2 }).format(n)

    const incomeRows = data?.revenueRows || []
    const expenseRows = data?.expenseRows || []

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 space-y-6 p-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white">Income Statement</h1>
                    <p className="text-slate-400 text-sm mt-1">Revenue and expenses for a specific period</p>
                </div>
            </div>

            <div className="glass rounded-xl p-4 border border-slate-700/50 flex flex-wrap items-end gap-4">
                <div>
                    <label className="block text-xs text-slate-400 mb-1">Year</label>
                    <select value={year} onChange={e => setYear(Number(e.target.value))}
                        className="px-3 py-2 bg-slate-800/50 border border-slate-600 rounded-lg text-slate-200 text-sm">
                        {Array.from({ length: 5 }, (_, i) => today.getFullYear() - 2 + i).map(y =>
                            <option key={y} value={y}>{y}</option>
                        )}
                    </select>
                </div>
                <div>
                    <label className="block text-xs text-slate-400 mb-1">Month</label>
                    <select value={month} onChange={e => setMonth(Number(e.target.value))}
                        className="px-3 py-2 bg-slate-800/50 border border-slate-600 rounded-lg text-slate-200 text-sm">
                        {MONTHS.map((m, i) => <option key={i} value={i}>{m}</option>)}
                    </select>
                </div>
                <button onClick={fetchData}
                    className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-white text-sm font-medium transition-colors">
                    <FileText className="w-4 h-4" /> Generate
                </button>
            </div>

            {error && <div className="flex items-center gap-3 p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm"><AlertCircle className="w-5 h-5" />{error}</div>}

            {loading ? (
                <div className="flex items-center justify-center py-16 text-slate-400"><Loader2 className="w-5 h-5 animate-spin mr-2" />Loading income statement...</div>
            ) : !data || (data.revenueRows.length === 0 && data.expenseRows.length === 0) ? (
                <div className="text-center py-16 text-slate-400">No data for {MONTHS[month]} {year}.</div>
            ) : (
                <div className="glass rounded-xl overflow-hidden border border-slate-700/50">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-slate-700/50">
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Code</th>
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Account</th>
                                <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase" style={{ width: '200px' }}>Amount</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr className="bg-slate-800/30"><td colSpan={3} className="px-4 py-2 text-xs font-semibold text-green-400 uppercase tracking-wider">Income</td></tr>
                            {incomeRows.map(row => (
                                <tr key={row.code} className="border-b border-slate-700/30 hover:bg-slate-800/50">
                                    <td className="px-4 py-3 font-mono text-slate-400">{row.code}</td>
                                    <td className="px-4 py-3 text-white">{row.name}</td>
                                    <td className="px-4 py-3 text-right font-mono text-green-400">{fmt(row.balance)}</td>
                                </tr>
                            ))}
                            <tr className="bg-slate-800/40 font-semibold border-b border-slate-700/50">
                                <td colSpan={2} className="px-4 py-3 text-right text-green-400">Total Income</td>
                                <td className="px-4 py-3 text-right font-mono text-green-400" style={{ borderTop: '2px solid rgb(34 197 94 / 0.5)' }}>{fmt(data.totalRevenue)}</td>
                            </tr>
                            <tr className="bg-slate-800/30"><td colSpan={3} className="px-4 py-2 text-xs font-semibold text-amber-400 uppercase tracking-wider">Expenses</td></tr>
                            {expenseRows.map(row => (
                                <tr key={row.code} className="border-b border-slate-700/30 hover:bg-slate-800/50">
                                    <td className="px-4 py-3 font-mono text-slate-400">{row.code}</td>
                                    <td className="px-4 py-3 text-white">{row.name}</td>
                                    <td className="px-4 py-3 text-right font-mono text-red-400">{fmt(row.balance)}</td>
                                </tr>
                            ))}
                            <tr className="bg-slate-800/40 font-semibold border-b border-slate-700/50">
                                <td colSpan={2} className="px-4 py-3 text-right text-red-400">Total Expenses</td>
                                <td className="px-4 py-3 text-right font-mono text-red-400" style={{ borderTop: '2px solid rgb(248 113 113 / 0.5)' }}>{fmt(data.totalExpenses)}</td>
                            </tr>
                        </tbody>
                        <tfoot>
                            <tr className="bg-slate-800/50 font-bold">
                                <td colSpan={2} className="px-4 py-4 text-right text-white uppercase">Net {data.netIncome >= 0 ? 'Income' : 'Loss'}</td>
                                <td className={`px-4 py-4 text-right font-mono text-lg ${data.netIncome >= 0 ? 'text-green-400' : 'text-red-400'}`}
                                    style={{ borderTop: '3px double rgb(148 163 184 / 0.5)' }}>
                                    {fmt(data.netIncome)}
                                </td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
            )}
        </div>
    )
}
