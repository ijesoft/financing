import { useState, useEffect, Fragment } from 'react'
import { FileText, Loader2, AlertCircle } from 'lucide-react'

interface BalanceSheetRow {
    code: string
    name: string
    balance: number
}

interface BalanceSheetSection {
    sectionName: string
    total: number
    rows: BalanceSheetRow[]
}

interface BalanceSheetReport {
    asOf: string
    sections: BalanceSheetSection[]
}

function fetchGraphQL(query: string, variables: Record<string, any> = {}) {
    const token = localStorage.getItem('access_token')
    return fetch('/graphql', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: token ? `Bearer ${token}` : '' },
        body: JSON.stringify({ query, variables }),
    }).then((res) => res.json())
}

export default function BalanceSheetPage() {
    const [loading, setLoading] = useState(true)
    const [data, setData] = useState<BalanceSheetReport | null>(null)
    const [asOf, setAsOf] = useState(new Date().toISOString().split('T')[0])
    const [error, setError] = useState<string | null>(null)

    const fetchData = async () => {
        setLoading(true)
        setError(null)
        try {
            const result = await fetchGraphQL(
                `query BalanceSheet($asOf: Date) {
                    balanceSheet(asOf: $asOf) { asOf sections { sectionName total rows { code name balance } } }
                }`, { asOf }
            )
            if (result.errors) throw new Error(result.errors[0].message)
            setData(result.data?.balanceSheet || null)
        } catch (e: any) {
            setError(e.message || 'Failed to load balance sheet')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => { fetchData() }, [])

    const fmt = (n: number) => new Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP', minimumFractionDigits: 2 }).format(n)

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 space-y-6 p-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white">Balance Sheet</h1>
                    <p className="text-slate-400 text-sm mt-1">Financial position as of a specific date</p>
                </div>
            </div>

            <div className="glass rounded-xl p-4 border border-slate-700/50 flex flex-wrap items-end gap-4">
                <div>
                    <label className="block text-xs text-slate-400 mb-1">As of Date</label>
                    <input type="date" value={asOf} onChange={e => setAsOf(e.target.value)}
                        className="px-3 py-2 bg-slate-800/50 border border-slate-600 rounded-lg text-slate-200 text-sm" />
                </div>
                <button onClick={fetchData}
                    className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-white text-sm font-medium transition-colors">
                    <FileText className="w-4 h-4" /> Generate
                </button>
            </div>

            {error && <div className="flex items-center gap-3 p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm"><AlertCircle className="w-5 h-5" />{error}</div>}

            {loading ? (
                <div className="flex items-center justify-center py-16 text-slate-400"><Loader2 className="w-5 h-5 animate-spin mr-2" />Loading balance sheet...</div>
            ) : !data || data.sections.every(s => s.rows.length === 0) ? (
                <div className="text-center py-16 text-slate-400">No data as of {asOf}.</div>
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
                            {data.sections.map((section, si) => (
                                <Fragment key={si}>
                                    <tr className="bg-slate-800/30">
                                        <td colSpan={3} className="px-4 py-2 text-xs font-semibold uppercase tracking-wider"
                                            style={{ color: section.sectionName === 'Assets' ? 'rgb(96 165 250)' : section.sectionName === 'Liabilities' ? 'rgb(251 146 60)' : 'rgb(52 211 153)' }}>
                                            {section.sectionName}
                                        </td>
                                    </tr>
                                    {section.rows.map(row => (
                                        <tr key={row.code} className="border-b border-slate-700/30 hover:bg-slate-800/50">
                                            <td className="px-4 py-3 font-mono text-slate-400">{row.code}</td>
                                            <td className="px-4 py-3 text-white">{row.name}</td>
                                            <td className="px-4 py-3 text-right font-mono text-white">{fmt(row.balance)}</td>
                                        </tr>
                                    ))}
                                    <tr className="bg-slate-800/40 font-semibold border-b border-slate-700/50">
                                        <td colSpan={2} className="px-4 py-3 text-right text-white">Total {section.sectionName}</td>
                                        <td className="px-4 py-3 text-right font-mono text-white" style={{ borderTop: '2px solid rgb(148 163 184 / 0.3)' }}>{fmt(section.total)}</td>
                                    </tr>
                                </Fragment>
                            ))}
                        </tbody>
                        <tfoot>
                            <tr className="bg-slate-800/50 font-bold">
                                <td colSpan={2} className="px-4 py-4 text-right text-white uppercase">Total Liabilities &amp; Equity</td>
                                <td className="px-4 py-4 text-right font-mono text-lg text-emerald-400"
                                    style={{ borderTop: '3px double rgb(148 163 184 / 0.5)' }}>
                                    {data.sections.length >= 2 ? fmt(data.sections.slice(1).reduce((sum, s) => sum + s.total, 0)) : '\u2014'}
                                </td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
            )}
        </div>
    )
}
