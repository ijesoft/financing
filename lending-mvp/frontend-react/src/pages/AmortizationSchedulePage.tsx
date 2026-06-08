import { gql } from '@apollo/client'
import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@apollo/client'
import { GET_LOAN, GET_LOAN_AMORTIZATION } from '@/api/queries'
import { formatDate } from '@/lib/utils'
import { Calculator, Loader2, ArrowLeft, Printer } from 'lucide-react'

const safeFormatCurrency = (value: any) => {
    try {
        const num = parseFloat(String(value || 0))
        return new Intl.NumberFormat('en-PH', {
            style: 'currency',
            currency: 'PHP',
        }).format(num)
    } catch (e) {
        return `₱${value}`
    }
}

interface LoanDetail {
    id: string
    customerId: string
    productId: string
    principal: number
    termMonths: number
    approvedPrincipal?: number
    approvedRate?: number
    status: string
    createdAt: string
    disbursedAt?: string
    outstandingBalance?: number
    borrowerName: string
    productName: string
}

interface AmortizationRow {
    installmentNumber: number
    dueDate: string
    principalDue: number | string
    interestDue: number | string
    penaltyDue: number | string
    principalPaid: number | string
    interestPaid: number | string
    penaltyPaid: number | string
    status: string
    totalDue: number | string
    totalPaid: number | string
}

export default function AmortizationSchedulePage() {
    const { id } = useParams<{ id: string }>()
    const [showAll, setShowAll] = useState(false)

    const { data: loanData, loading: loanLoading, error: loanError } = useQuery(gql(GET_LOAN), {
        variables: { id },
        skip: !id
    })

    const { data: amortizationData, loading: amortizationLoading, error: amortizationError } = useQuery(gql(GET_LOAN_AMORTIZATION), {
        variables: { loanId: id },
        skip: !id
    })

    const loan: LoanDetail = loanData?.loan
    const amortizationRows: AmortizationRow[] = amortizationData?.loanAmortization?.rows || []
    const repaymentFrequency: string = amortizationData?.loanAmortization?.repaymentFrequency || 'monthly'

    const principal = parseFloat(String(loan?.approvedPrincipal || loan?.principal || 0))
    const annualRatePercent = parseFloat(String(loan?.approvedRate || 0))
    const termMonths = parseInt(String(loan?.termMonths || 0))

    // Frequency labels and divisors
    const FREQ_CONFIG: Record<string, { label: string, divisor: number, periods: number }> = {
        daily:       { label: 'Daily',       divisor: 365, periods: termMonths * 30 },
        weekly:      { label: 'Weekly',      divisor: 52,  periods: termMonths * 4 },
        bi_weekly:   { label: 'Bi-Weekly',   divisor: 26,  periods: termMonths * 2 },
        semi_monthly:{ label: 'Semi-Monthly',divisor: 24,  periods: termMonths * 2 },
        monthly:     { label: 'Monthly',     divisor: 12,  periods: termMonths },
        quarterly:   { label: 'Quarterly',   divisor: 4,   periods: Math.max(1, Math.floor(termMonths / 3)) },
        semi_annual: { label: 'Semi-Annual', divisor: 2,   periods: Math.max(1, Math.floor(termMonths / 6)) },
        bullet:      { label: 'Bullet',      divisor: 12,  periods: 1 },
    }
    const freqConfig = FREQ_CONFIG[repaymentFrequency] || FREQ_CONFIG.monthly

    // Calculate amortization locally if backend returns empty
    const calculateLocalAmortization = (): AmortizationRow[] => {
        if (amortizationRows.length > 0) return amortizationRows
        if (principal <= 0 || freqConfig.periods <= 0) return []
        
        const ratePerPeriod = annualRatePercent / 100 / freqConfig.divisor
        const payment = (principal * ratePerPeriod * Math.pow(1 + ratePerPeriod, freqConfig.periods)) / (Math.pow(1 + ratePerPeriod, freqConfig.periods) - 1)
        
        const rows: AmortizationRow[] = []
        let balance = principal
        
        for (let i = 1; i <= freqConfig.periods; i++) {
            const interestDue = balance * ratePerPeriod
            const principalDue = payment - interestDue
            balance = Math.max(0, balance - principalDue)
            
            const dueDate = new Date()
            if (repaymentFrequency === 'daily') {
                dueDate.setDate(dueDate.getDate() + i)
            } else if (repaymentFrequency === 'weekly') {
                dueDate.setDate(dueDate.getDate() + i * 7)
            } else if (repaymentFrequency === 'bi_weekly') {
                dueDate.setDate(dueDate.getDate() + i * 14)
            } else if (repaymentFrequency === 'semi_monthly') {
                dueDate.setDate(dueDate.getDate() + i * 15)
            } else {
                dueDate.setMonth(dueDate.getMonth() + i)
            }
            
            rows.push({
                installmentNumber: i,
                dueDate: dueDate.toISOString().split('T')[0],
                principalDue: principalDue,
                interestDue: interestDue,
                penaltyDue: 0,
                principalPaid: 0,
                interestPaid: 0,
                penaltyPaid: 0,
                status: 'pending',
                totalDue: principalDue + interestDue,
                totalPaid: 0
            })
        }
        return rows
    }

    const effectiveRows = amortizationRows.length > 0 ? amortizationRows : calculateLocalAmortization()
    
    const totalInterest = effectiveRows.reduce((sum, row) => sum + parseFloat(String(row.interestDue || 0)), 0)
    const totalPayments = principal + totalInterest
    const periodicPayment = freqConfig.periods > 0 ? totalPayments / freqConfig.periods : 0

    const displayRows = showAll ? effectiveRows : effectiveRows.slice(0, 12)

    const handlePrint = () => {
        window.print()
    }

    if (loanLoading || amortizationLoading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Loader2 className="w-6 h-6 animate-spin text-yellow-400" />
            </div>
        )
    }

    if (loanError) {
        return (
            <div className="p-10 text-center text-destructive">
                Error loading loan: {loanError.message}
            </div>
        )
    }

    if (!loan) {
        return (
            <div className="p-10 text-center text-muted-foreground">
                Loan not found. <Link to="/loans" className="text-primary hover:underline">Go to Loans</Link>
            </div>
        )
    }

    // Pre-calculate balances for display
    let currentBalance = principal
    const rowsWithBalance = (amortizationRows || []).map(row => {
        const pDue = parseFloat(String(row.principalDue || 0))
        const iDue = parseFloat(String(row.interestDue || 0))
        const tDue = parseFloat(String(row.totalDue || (pDue + iDue)))
        
        currentBalance = Math.max(0, currentBalance - pDue)
        
        return {
            ...row,
            calculatedBalance: currentBalance,
            parsedPrincipalDue: pDue,
            parsedInterestDue: iDue,
            parsedTotalDue: tDue
        }
    })

    const displayRowsWithBalance = showAll ? rowsWithBalance : rowsWithBalance.slice(0, 12)

    return (
        <div className="space-y-6 animate-fade-in">
            {/* Header */}
            <div className="flex items-center justify-between no-print">
                <div className="flex items-center gap-4">
                    <Link
                        to={`/loans/${id}`}
                        className="p-2 hover:bg-secondary rounded-lg transition-colors"
                    >
                        <ArrowLeft className="w-5 h-5" />
                    </Link>
                    <div>
                        <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
                            <Calculator className="w-6 h-6 text-yellow-400" /> Amortization Schedule
                        </h1>
                        <p className="text-muted-foreground text-sm mt-1">
                            Loan ID: ...{loan.id?.slice(-6)} | {loan.borrowerName || 'N/A'}
                        </p>
                    </div>
                </div>
                <button
                    onClick={handlePrint}
                    className="flex items-center gap-2 px-4 py-2 bg-secondary border border-border rounded-lg text-sm hover:bg-secondary/80 transition-colors"
                >
                    <Printer className="w-4 h-4" />
                    Print
                </button>
            </div>

            {/* Loan Summary */}
            <div className="glass p-6 rounded-xl">
                <div className="flex justify-between items-start mb-6 border-b border-border/50 pb-4">
                    <div>
                        <h2 className="text-xl font-bold text-gray-800">Loan Amortization Schedule</h2>
                        <p className="text-blue-600 text-sm mt-1">Generated by LendingMVP System</p>
                    </div>
                    <div className="text-right">
                        <div className="flex items-center justify-end">
                            <span className="text-xl font-bold text-gray-700">Lending<span className="text-blue-500 italic">MVP</span></span>
                        </div>
                        <p className="text-xs text-gray-400 mt-1">© 2026 IJE Software LLC</p>
                    </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mb-6">
                    <div>
                        <p className="text-xs text-muted-foreground uppercase tracking-wider">Principal</p>
                        <p className="text-lg font-bold mt-1">{safeFormatCurrency(principal)}</p>
                    </div>
                    <div>
                        <p className="text-xs text-muted-foreground uppercase tracking-wider">Interest Rate</p>
                        <p className="text-lg font-bold mt-1">{annualRatePercent}%</p>
                    </div>
                    <div>
                        <p className="text-xs text-muted-foreground uppercase tracking-wider">Term</p>
                        <p className="text-lg font-bold mt-1">{termMonths} months</p>
                    </div>
                    <div>
                        <p className="text-xs text-muted-foreground uppercase tracking-wider">Disbursement Date</p>
                        <p className="text-lg font-bold mt-1">{loan.disbursedAt ? formatDate(loan.disbursedAt) : formatDate(loan.createdAt)}</p>
                    </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-6 pt-4 border-t border-border/50">
                    <div>
                        <p className="text-xs text-muted-foreground uppercase tracking-wider">Payment Frequency</p>
                        <p className="text-lg font-bold mt-1">{freqConfig.label}</p>
                    </div>
                    <div>
                        <p className="text-xs text-muted-foreground uppercase tracking-wider">Periodic Rate</p>
                        <p className="text-lg font-bold mt-1">{(annualRatePercent / freqConfig.divisor).toFixed(4)}%</p>
                    </div>
                    <div>
                        <p className="text-xs text-muted-foreground uppercase tracking-wider">Total Interest</p>
                        <p className="text-lg font-bold mt-1">{safeFormatCurrency(totalInterest)}</p>
                    </div>
                    <div>
                        <p className="text-xs text-muted-foreground uppercase tracking-wider">Total Payments</p>
                        <p className="text-lg font-bold mt-1">{safeFormatCurrency(totalPayments)}</p>
                    </div>
                </div>
            </div>

            {/* Periodic Payment Summary */}
            <div className="glass p-6 rounded-xl">
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-2">{freqConfig.label} Payment</p>
                <p className="text-3xl font-bold text-gray-900">{safeFormatCurrency(periodicPayment)}</p>
            </div>

            {/* Amortization Table */}
            <div className="glass rounded-xl overflow-hidden">
                <table className="w-full text-sm">
                    <thead className="bg-secondary/40">
                        <tr>
                            <th className="px-3 py-3 text-center font-semibold text-muted-foreground">No.</th>
                            <th className="px-3 py-3 text-left font-semibold text-muted-foreground">Due Date</th>
                            <th className="px-3 py-3 text-right font-semibold text-muted-foreground">Payment</th>
                            <th className="px-3 py-3 text-right font-semibold text-muted-foreground">Principal</th>
                            <th className="px-3 py-3 text-right font-semibold text-muted-foreground">Interest</th>
                            <th className="px-3 py-3 text-right font-semibold text-muted-foreground">Total</th>
                            <th className="px-3 py-3 text-right font-semibold text-muted-foreground">Balance</th>
                        </tr>
                    </thead>
                    <tbody>
                        {/* Initial Balance Row */}
                        <tr className="border-b border-gray-300 bg-gray-50">
                            <td className="px-3 py-2 text-center text-gray-500">-</td>
                            <td className="px-3 py-2 text-gray-500">Starting Balance</td>
                            <td className="px-3 py-2 text-right text-gray-500">-</td>
                            <td className="px-3 py-2 text-right text-gray-500">-</td>
                            <td className="px-3 py-2 text-right text-gray-500">-</td>
                            <td className="px-3 py-2 text-right text-gray-500">-</td>
                            <td className="px-3 py-2 text-right font-medium text-yellow-400 border border-gray-300 bg-white">
                                {safeFormatCurrency(principal)}
                            </td>
                        </tr>
                        {displayRowsWithBalance.map((row) => (
                            <tr key={row.installmentNumber} className="border-b border-gray-200 hover:bg-gray-50/50">
                                <td className="px-3 py-2 text-center text-gray-600">{row.installmentNumber}</td>
                                <td className="px-3 py-2 text-center">{formatDate(row.dueDate)}</td>
                                <td className="px-3 py-2 text-right font-medium">{safeFormatCurrency(row.parsedTotalDue)}</td>
                                <td className="px-3 py-2 text-right text-white">{safeFormatCurrency(row.parsedPrincipalDue)}</td>
                                <td className="px-3 py-2 text-right text-white">{safeFormatCurrency(row.parsedInterestDue)}</td>
                                <td className="px-3 py-2 text-right font-semibold text-primary">{safeFormatCurrency(row.parsedTotalDue)}</td>
                                <td className="px-3 py-2 text-right font-bold text-yellow-400 border-l border-gray-200">
                                    {safeFormatCurrency(row.calculatedBalance)}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Show More / Less */}
            {amortizationRows.length > 12 && (
                <div className="text-center no-print">
                    <button
                        onClick={() => setShowAll(!showAll)}
                        className="px-6 py-2 bg-secondary border border-border rounded-lg text-sm hover:bg-secondary/80 transition-colors"
                    >
                        {showAll ? 'Show Less' : `Show All (${amortizationRows.length} payments)`}
                    </button>
                </div>
            )}

            {/* Error Message */}
            {amortizationError && (
                <div className="glass p-4 rounded-xl border border-yellow-500/30 bg-yellow-500/10">
                    <p className="text-yellow-400 text-sm">
                        Could not load amortization schedule from server. Showing calculated values instead.
                    </p>
                </div>
            )}
        </div>
    )
}
