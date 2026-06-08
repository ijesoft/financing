import { useState, useEffect } from 'react'
import { FileText, Loader2, AlertCircle } from 'lucide-react'

interface APAgingBucket {
    label: string
    total: number
}

interface APAgingRow {
    branchCode: string
    totalBalance: number
    buckets: APAgingBucket[]
}

interface APAgingReport {
    asOf: string
    grandTotal: number
    rows: APAgingRow[]
}

function fetchGraphQL(query: string, variables: Record<string, any> = {}) {
    const token = localStorage.getItem('access_token')
    return fetch('/graphql', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: token ? `Bearer ${token}` : '' },
        body: JSON.stringify({ query, variables }),
    }).then((res) => res.json())
}

const BUCKET_COLORS = ['text-emerald-400', 'text-yellow-400', 'text-orange-400', 'text-red-400', 'text-red-600']

export default function APAgingPage() {
    const [loading, setLoading] = useState(true)
    const [data, setData] = useState<APAgingReport | null>(null)
    const [asOf, setAsOf] = useState(new Date().toISOString().split('T')[0])
    const [error, setError] = useState<string | null>(null)

    const fetchData = async () => {
        setLoading(true)
        setError(null)
        try {
            const result = await fetchGraphQL(
                `query APAging($asOf: Date) {
                    apAging(asOf: $asOf) { asOf grandTotal rows { branchCode totalBalance buckets { label total } } }
                }`, { asOf }
            )
            if (result.errors) throw new Error(result.errors[0].message)
            setData(result.data?.apAging || null)
        } catch (e: any) {
            setError(e.message || 'Failed to load AP aging')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => { fetchData() }, [])

    const fmt = (n: number) => new Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP', minimumFractionDigits: 2 }).format(n)

    const bucketLabels = data?.rows[0]?.buckets.map(b => b.label) || []

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 space-y-6 p-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white">Accounts Payable Aging</h1>
                    <p className="text-slate-400 text-sm mt-1">Aging analysis of undisbursed loan principal by branch</p>
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
                <div className="flex items-center justify-center py-16 text-slate-400"><Loader2 className="w-5 h-5 animate-spin mr-2" />Loading AP aging...</div>
            ) : !data || data.rows.length === 0 ? (
                <div className="text-center py-16 text-slate-400">No outstanding payables as of {asOf}.</div>
            ) : (
                <div className="glass rounded-xl overflow-hidden border border-slate-700/50">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-slate-700/50">
                                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Branch</th>
                                {bucketLabels.map((label, i) => (
                                    <th key={i} className={`text-right px-4 py-3 text-xs font-semibold uppercase ${BUCKET_COLORS[i] || 'text-slate-400'}`}>{label}</th>
                                ))}
                                <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase">Total</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.rows.map(row => (
                                <tr key={row.branchCode} className="border-b border-slate-700/30 hover:bg-slate-800/50 transition-colors">
                                    <td className="px-4 py-3 text-white font-medium">{row.branchCode}</td>
                                    {row.buckets.map((bucket, i) => (
                                        <td key={i} className={`px-4 py-3 text-right font-mono ${BUCKET_COLORS[i] || 'text-white'}`}>
                                            {bucket.total > 0 ? fmt(bucket.total) : '\u2014'}
                                        </td>
                                    ))}
                                    <td className="px-4 py-3 text-right font-mono font-semibold text-white">{fmt(row.totalBalance)}</td>
                                </tr>
                            ))}
                        </tbody>
                        <tfoot>
                            <tr className="bg-slate-800/50 font-bold border-t-2 border-slate-600">
                                <td className="px-4 py-4 text-right text-white uppercase">Grand Total</td>
                                {bucketLabels.map((_, i) => (
                                    <td key={i} className={`px-4 py-4 text-right font-mono ${BUCKET_COLORS[i] || 'text-white'}`}>
                                        {fmt(data.rows.reduce((sum, r) => sum + (r.buckets[i]?.total || 0), 0))}
                                    </td>
                                ))}
                                <td className="px-4 py-4 text-right font-mono text-lg text-white">{fmt(data.grandTotal)}</td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
            )}
        </div>
    )
}
