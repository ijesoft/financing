import { useState, useEffect } from 'react'
import { FileText, Loader2, AlertCircle } from 'lucide-react'

// ── Types matching the GraphQL response ──

type AgingBucket = 'CURRENT' | 'DPD_1_30' | 'DPD_31_60' | 'DPD_61_90' | 'DPD_91_180' | 'DPD_180_PLUS'

interface DelinquencySummary {
    totalPortfolioOutstanding: number
    totalDelinquentAmount: number
    totalDelinquentLoans: number
    par30: number
    par60: number
    par90: number
    nplRatio: number
    delinquentRate: number
}

interface AgingBucketSummary {
    bucket: AgingBucket
    loanCount: number
    outstandingPrincipal: number
    portfolioPercent: number
    principalArrears: number
    interestArrears: number
    penaltyArrears: number
}

interface DelinquentLoanNode {
    loanId: string
    customerId: string
    customerName: string
    branchCode: string | null
    productName: string
    originalPrincipal: number
    outstandingPrincipal: number
    totalArrears: number
    principalArrears: number
    interestArrears: number
    penaltyArrears: number
    dpd: number
    agingBucket: AgingBucket
    oldestDueDate: string | null
    installmentsPastDue: number
    totalInstallments: number
    lastPaymentDate: string | null
    lastPaymentAmount: number | null
    collectionsOfficer: string | null
    assignedCollectionsBranch: string | null
    eclStage: string
    isNpl: boolean
    isRestructured: boolean
    status: string
    monthsPaid: number
}

interface DelinquentLoanConnection {
    nodes: DelinquentLoanNode[]
    totalCount: number
    totalOutstandingPrincipal: number
    totalArrears: number
}

interface DelinquencyReport {
    asOf: string
    generatedAt: string
    branchCode: string | null
    summary: DelinquencySummary
    agingSummary: AgingBucketSummary[]
    loanDetails: DelinquentLoanConnection
}

// ── Helpers ──

function fetchGraphQL(query: string, variables: Record<string, any> = {}) {
    const token = localStorage.getItem('access_token')
    return fetch('/graphql', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: token ? `Bearer ${token}` : '' },
        body: JSON.stringify({ query, variables }),
    }).then((res) => res.json())
}

const fmt = (n: number) =>
    new Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP', minimumFractionDigits: 2 }).format(n)

const fmtPct = (n: number | string) =>
    Number(n).toFixed(2) + '%'

const BUCKET_LABELS: Record<AgingBucket, string> = {
    CURRENT: 'Current (0 DPD)',
    DPD_1_30: '1–30 Days',
    DPD_31_60: '31–60 Days',
    DPD_61_90: '61–90 Days',
    DPD_91_180: '91–180 Days',
    DPD_180_PLUS: '180+ Days',
}

const BUCKET_COLORS: Record<AgingBucket, string> = {
    CURRENT: 'text-emerald-400',
    DPD_1_30: 'text-yellow-400',
    DPD_31_60: 'text-orange-400',
    DPD_61_90: 'text-red-400',
    DPD_91_180: 'text-red-500',
    DPD_180_PLUS: 'text-red-600',
}

const BUCKET_BG: Record<AgingBucket, string> = {
    CURRENT: 'bg-emerald-500/10',
    DPD_1_30: 'bg-yellow-500/10',
    DPD_31_60: 'bg-orange-500/10',
    DPD_61_90: 'bg-red-500/10',
    DPD_91_180: 'bg-red-500/20',
    DPD_180_PLUS: 'bg-red-600/20',
}

const STATUS_COLORS: Record<string, string> = {
    active: 'text-emerald-400 bg-emerald-500/10',
    defaulted: 'text-red-400 bg-red-500/10',
    non_accrual: 'text-orange-400 bg-orange-500/10',
}

// ── Page Component ──

export default function DelinquencyReportPage() {
    const [loading, setLoading] = useState(true)
    const [data, setData] = useState<DelinquencyReport | null>(null)
    const [asOf, setAsOf] = useState(new Date().toISOString().split('T')[0])
    const [error, setError] = useState<string | null>(null)

    const fetchData = async () => {
        setLoading(true)
        setError(null)
        try {
            const result = await fetchGraphQL(
                `query DelinquencyReport($asOf: Date) {
                    delinquencyReport(asOf: $asOf) {
                        asOf
                        generatedAt
                        branchCode
                        summary {
                            totalPortfolioOutstanding
                            totalDelinquentAmount
                            totalDelinquentLoans
                            par30
                            par60
                            par90
                            nplRatio
                            delinquentRate
                        }
                        agingSummary {
                            bucket
                            loanCount
                            outstandingPrincipal
                            portfolioPercent
                            principalArrears
                            interestArrears
                            penaltyArrears
                        }
                        loanDetails {
                            totalCount
                            totalOutstandingPrincipal
                            totalArrears
                            nodes {
                                loanId
                                customerId
                                customerName
                                branchCode
                                productName
                                originalPrincipal
                                outstandingPrincipal
                                totalArrears
                                principalArrears
                                interestArrears
                                penaltyArrears
                                dpd
                                agingBucket
                                oldestDueDate
                                installmentsPastDue
                                totalInstallments
                                lastPaymentDate
                                lastPaymentAmount
                                collectionsOfficer
                                assignedCollectionsBranch
                                eclStage
                                isNpl
                                isRestructured
                                status
                                monthsPaid
                            }
                        }
                    }
                }`, { asOf }
            )
            if (result.errors) throw new Error(result.errors[0].message)
            setData(result.data?.delinquencyReport || null)
        } catch (e: any) {
            setError(e.message || 'Failed to load delinquency report')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => { fetchData() }, [])

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 space-y-6 p-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white">Delinquency Report</h1>
                    <p className="text-slate-400 text-sm mt-1">
                        Portfolio at Risk (PAR) analysis with aging breakdown
                        {data && <span className="ml-2 text-slate-500">· Generated {new Date(data.generatedAt).toLocaleString()}</span>}
                    </p>
                </div>
            </div>

            {/* Filters */}
            <div className="glass rounded-xl p-4 border border-slate-700/50 flex flex-wrap items-end gap-4">
                <div>
                    <label className="block text-xs text-slate-400 mb-1">As of Date</label>
                    <input
                        type="date"
                        value={asOf}
                        onChange={e => setAsOf(e.target.value)}
                        className="px-3 py-2 bg-slate-800/50 border border-slate-600 rounded-lg text-slate-200 text-sm"
                    />
                </div>
                <button
                    onClick={fetchData}
                    className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-white text-sm font-medium transition-colors"
                >
                    <FileText className="w-4 h-4" /> Generate
                </button>
            </div>

            {error && (
                <div className="flex items-center gap-3 p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                    <AlertCircle className="w-5 h-5" />{error}
                </div>
            )}

            {loading ? (
                <div className="flex items-center justify-center py-16 text-slate-400">
                    <Loader2 className="w-5 h-5 animate-spin mr-2" />Loading delinquency report...
                </div>
            ) : !data || data.summary.totalPortfolioOutstanding === 0 ? (
                <div className="text-center py-16 text-slate-400">No active loans as of {asOf}.</div>
            ) : (
                <>
                    {/* KPI Cards */}
                    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
                        <KPICard label="Portfolio Outstanding" value={fmt(data.summary.totalPortfolioOutstanding)} color="text-blue-400" />
                        <KPICard label="Delinquent Amount" value={fmt(data.summary.totalDelinquentAmount)} color="text-orange-400" />
                        <KPICard label="Delinquent Loans" value={`${data.summary.totalDelinquentLoans} / ${data.loanDetails.totalCount}`} color="text-yellow-400" />
                        <KPICard
                            label="PAR ≥ 30"
                            value={fmtPct(data.summary.par30)}
                            color={data.summary.par30 > 10 ? 'text-red-400' : data.summary.par30 > 5 ? 'text-yellow-400' : 'text-emerald-400'}
                        />
                        <KPICard
                            label="PAR ≥ 60"
                            value={fmtPct(data.summary.par60)}
                            color={data.summary.par60 > 5 ? 'text-red-400' : data.summary.par60 > 2 ? 'text-yellow-400' : 'text-emerald-400'}
                        />
                        <KPICard
                            label="NPL (≥90 DPD)"
                            value={fmtPct(data.summary.nplRatio)}
                            color={data.summary.nplRatio > 5 ? 'text-red-400' : data.summary.nplRatio > 2 ? 'text-yellow-400' : 'text-emerald-400'}
                        />
                    </div>

                    {/* Aging Bucket Summary Table */}
                    <div className="glass rounded-xl overflow-hidden border border-slate-700/50">
                        <div className="px-4 py-3 border-b border-slate-700/50">
                            <h2 className="text-sm font-semibold text-white">Aging Bucket Summary</h2>
                        </div>
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-slate-700/50">
                                    <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Bucket</th>
                                    <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider"># Loans</th>
                                    <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Outstanding</th>
                                    <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">% of Portfolio</th>
                                    <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Principal Arrears</th>
                                    <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Interest Arrears</th>
                                    <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Penalty Arrears</th>
                                </tr>
                            </thead>
                            <tbody>
                                {data.agingSummary.map((bucket) => (
                                    <tr key={bucket.bucket} className="border-b border-slate-700/30 hover:bg-slate-800/50 transition-colors">
                                        <td className="px-4 py-3">
                                            <div className="flex items-center gap-2">
                                                <div className={`w-2.5 h-2.5 rounded-full ${BUCKET_COLORS[bucket.bucket].replace('text-', 'bg-')}`} />
                                                <span className={`font-medium ${BUCKET_COLORS[bucket.bucket]}`}>
                                                    {BUCKET_LABELS[bucket.bucket]}
                                                </span>
                                            </div>
                                        </td>
                                        <td className="px-4 py-3 text-right text-slate-300 font-mono">{bucket.loanCount}</td>
                                        <td className="px-4 py-3 text-right text-white font-mono">{fmt(bucket.outstandingPrincipal)}</td>
                                        <td className={`px-4 py-3 text-right font-mono ${BUCKET_COLORS[bucket.bucket]}`}>{Number(bucket.portfolioPercent).toFixed(2)}%</td>
                                        <td className="px-4 py-3 text-right text-slate-300 font-mono">{fmt(bucket.principalArrears)}</td>
                                        <td className="px-4 py-3 text-right text-slate-300 font-mono">{fmt(bucket.interestArrears)}</td>
                                        <td className="px-4 py-3 text-right text-slate-300 font-mono">{fmt(bucket.penaltyArrears)}</td>
                                    </tr>
                                ))}
                            </tbody>
                            <tfoot>
                                <tr className="bg-slate-800/50 font-bold border-t-2 border-slate-600">
                                    <td className="px-4 py-3 text-white">Total</td>
                                    <td className="px-4 py-3 text-right text-white font-mono">{data.loanDetails.totalCount}</td>
                                    <td className="px-4 py-3 text-right text-white font-mono">{fmt(data.loanDetails.totalOutstandingPrincipal)}</td>
                                    <td className="px-4 py-3 text-right text-white font-mono">100.00%</td>
                                    <td className="px-4 py-3 text-right text-slate-300 font-mono">{fmt(data.agingSummary.reduce((s, b) => s + Number(b.principalArrears), 0))}</td>
                                    <td className="px-4 py-3 text-right text-slate-300 font-mono">{fmt(data.agingSummary.reduce((s, b) => s + Number(b.interestArrears), 0))}</td>
                                    <td className="px-4 py-3 text-right text-slate-300 font-mono">{fmt(data.agingSummary.reduce((s, b) => s + Number(b.penaltyArrears), 0))}</td>
                                </tr>
                            </tfoot>
                        </table>
                    </div>

                    {/* Detailed Loan Listing */}
                    {data.loanDetails.nodes.length > 0 && (
                        <div className="glass rounded-xl overflow-hidden border border-slate-700/50">
                            <div className="px-4 py-3 border-b border-slate-700/50 flex items-center justify-between">
                                <h2 className="text-sm font-semibold text-white">Delinquent Loan Details</h2>
                                <span className="text-xs text-slate-400">{data.loanDetails.nodes.length} loans</span>
                            </div>
                            <div className="overflow-x-auto">
                                <table className="w-full text-sm">
                                    <thead>
                                        <tr className="border-b border-slate-700/50">
                                            <th className="text-left px-3 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Customer</th>
                                            <th className="text-left px-3 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Loan ID</th>
                                            <th className="text-left px-3 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Product</th>
                                            <th className="text-right px-3 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Outstanding</th>
                                            <th className="text-right px-3 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">DPD</th>
                                            <th className="text-left px-3 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Bucket</th>
                                            <th className="text-right px-3 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Arrears</th>
                                            <th className="text-left px-3 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Status</th>
                                            <th className="text-left px-3 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Officer</th>
                                            <th className="text-right px-3 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Missed</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.loanDetails.nodes
                                            .sort((a, b) => b.dpd - a.dpd)
                                            .map((loan) => (
                                                <tr
                                                    key={loan.loanId}
                                                    className="border-b border-slate-700/30 hover:bg-slate-800/50 transition-colors"
                                                >
                                                    <td className="px-3 py-3">
                                                        <div className="font-medium text-white">{loan.customerName}</div>
                                                        <div className="text-xs text-slate-500">{loan.customerId}</div>
                                                    </td>
                                                    <td className="px-3 py-3 text-slate-300 font-mono text-xs">LOAN-{loan.loanId}</td>
                                                    <td className="px-3 py-3 text-slate-300">{loan.productName}</td>
                                                    <td className="px-3 py-3 text-right text-white font-mono">{fmt(loan.outstandingPrincipal)}</td>
                                                    <td className={`px-3 py-3 text-right font-mono font-bold ${loan.dpd >= 90 ? 'text-red-400' : loan.dpd >= 30 ? 'text-yellow-400' : 'text-slate-300'}`}>
                                                        {loan.dpd}
                                                    </td>
                                                    <td className="px-3 py-3">
                                                        <span className={`text-xs px-2 py-1 rounded-full font-medium ${BUCKET_COLORS[loan.agingBucket]} ${BUCKET_BG[loan.agingBucket]}`}>
                                                            {BUCKET_LABELS[loan.agingBucket]}
                                                        </span>
                                                    </td>
                                                    <td className="px-3 py-3 text-right text-orange-400 font-mono">{fmt(loan.totalArrears)}</td>
                                                    <td className="px-3 py-3">
                                                        <span className={`text-xs px-2 py-1 rounded-full font-medium ${STATUS_COLORS[loan.status] || 'text-slate-400 bg-slate-500/10'}`}>
                                                            {loan.status.charAt(0).toUpperCase() + loan.status.slice(1)}
                                                        </span>
                                                        {loan.isNpl && (
                                                            <span className="ml-1 text-xs px-1.5 py-0.5 rounded bg-red-500/20 text-red-400">NPL</span>
                                                        )}
                                                    </td>
                                                    <td className="px-3 py-3 text-slate-400 text-xs">{loan.collectionsOfficer || '—'}</td>
                                                    <td className="px-3 py-3 text-right text-slate-400 font-mono">
                                                        {loan.installmentsPastDue}/{loan.totalInstallments}
                                                    </td>
                                                </tr>
                                            ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}
                </>
            )}
        </div>
    )
}

// ── KPI Card Component ──

function KPICard({ label, value, color }: { label: string; value: string; color: string }) {
    return (
        <div className="glass rounded-xl p-4 border border-slate-700/50">
            <p className="text-xs text-slate-400 mb-1 truncate">{label}</p>
            <p className={`text-lg font-bold ${color} font-mono`}>{value}</p>
        </div>
    )
}
