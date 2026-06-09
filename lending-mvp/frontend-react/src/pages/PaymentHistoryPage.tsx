import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { formatDate } from '@/lib/utils'
import { Loader2, ArrowLeft, Printer, History } from 'lucide-react'

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
    paymentDate: string | null
    status: string
    totalDue: number | string
    totalPaid: number | string
}

const LOAN_QUERY = `query GetLoan($id: ID!) { loan(id: $id) { id customerId productId principal termMonths approvedPrincipal approvedRate status createdAt disbursedAt outstandingBalance borrowerName productName } }`
const AMORT_QUERY = `query GetLoanAmortization($loanId: ID!) { loanAmortization(loanId: $loanId) { rows { installmentNumber dueDate principalDue interestDue penaltyDue principalPaid interestPaid penaltyPaid paymentDate status totalDue totalPaid } } }`

function fetchGraphQL<T>(query: string, variables: Record<string, any>): Promise<T> {
    const token = localStorage.getItem('access_token')
    return fetch('/graphql', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: token ? `Bearer ${token}` : '' },
        body: JSON.stringify({ query, variables }),
    }).then(res => res.json())
}

export default function PaymentHistoryPage() {
    const { id } = useParams<{ id: string }>()
    const [showAll, setShowAll] = useState(true)

    const { data: loanData, isLoading: loanLoading, error: loanError } = useQuery({
        queryKey: ['loan', id],
        queryFn: () => fetchGraphQL<any>(LOAN_QUERY, { id }),
        enabled: !!id,
        staleTime: 60000,
    })

    const { data: amortizationData, isLoading: amortizationLoading, error: amortizationError } = useQuery({
        queryKey: ['loanAmortization', id],
        queryFn: () => fetchGraphQL<any>(AMORT_QUERY, { loanId: id }),
        enabled: !!id,
        staleTime: 60000,
    })

    const loan: LoanDetail | undefined = loanData?.data?.loan
    const amortizationRows: AmortizationRow[] = amortizationData?.data?.loanAmortization?.rows || []

    const principal = parseFloat(String(loan?.approvedPrincipal || loan?.principal || 0))
    const annualRatePercent = parseFloat(String(loan?.approvedRate || 0))
    const termMonths = parseInt(String(loan?.termMonths || 0))

    const totalInterest = (amortizationRows || []).reduce((sum, row) => sum + parseFloat(String(row.interestDue || 0)), 0)
    const totalPayments = principal + totalInterest
    const totalPaid = (amortizationRows || []).reduce((sum, row) => sum + parseFloat(String(row.totalPaid || 0)), 0)

    const handlePrint = () => {
        window.print()
    }

    if (loanLoading || amortizationLoading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
            </div>
        )
    }

    if (loanError || !loan) {
        return (
            <div className="p-10 text-center text-muted-foreground">
                Loan data not available. <Link to="/loans" className="text-primary hover:underline">Go to Loans</Link>
            </div>
        )
    }

    const getStatusBadge = (status: string, dueDate: string) => {
        const isOverdue = new Date(dueDate) < new Date() && status !== 'paid'
        
        if (status === 'paid') {
            return <span className="px-2 py-1 rounded text-[10px] font-bold bg-emerald-100 text-emerald-700 uppercase">Paid</span>
        }
        if (isOverdue) {
            return <span className="px-2 py-1 rounded text-[10px] font-bold bg-red-100 text-red-600 uppercase">Overdue</span>
        }
        if (status === 'partial') {
            return <span className="px-2 py-1 rounded text-[10px] font-bold bg-blue-100 text-blue-600 uppercase">Partial</span>
        }
        return <span className="px-2 py-1 rounded text-[10px] font-bold bg-orange-50 text-orange-400 uppercase">Unpaid</span>
    }

    return (
        <div className="space-y-6 animate-fade-in max-w-5xl mx-auto pb-12">
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
                            <History className="w-6 h-6 text-blue-500" /> Payment History
                        </h1>
                        <p className="text-muted-foreground text-sm mt-1">
                            Detailed record of payments against schedule
                        </p>
                    </div>
                </div>
                <div className="flex gap-2">
                    <button
                        onClick={handlePrint}
                        className="flex items-center gap-2 px-4 py-2 bg-secondary border border-border rounded-lg text-sm hover:bg-secondary/80 transition-colors"
                    >
                        <Printer className="w-4 h-4" />
                        Print
                    </button>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Loan Information */}
                <div className="bg-white border border-slate-300 shadow-sm">
                    <div className="bg-slate-100 px-4 py-2 border-b border-slate-300">
                        <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider">Loan Information</h3>
                    </div>
                    <div className="divide-y divide-slate-200">
                        <div className="flex justify-between px-4 py-2">
                            <span className="text-sm text-slate-600">Borrower</span>
                            <span className="text-sm font-bold text-slate-900 uppercase">{loan.borrowerName}</span>
                        </div>
                        <div className="flex justify-between px-4 py-2">
                            <span className="text-sm text-slate-600">Loan Amount</span>
                            <span className="text-sm font-bold text-slate-900">{safeFormatCurrency(principal)}</span>
                        </div>
                        <div className="flex justify-between px-4 py-2">
                            <span className="text-sm text-slate-600">Annual Interest Rate</span>
                            <span className="text-sm font-bold text-slate-900">{annualRatePercent.toFixed(2)}%</span>
                        </div>
                        <div className="flex justify-between px-4 py-2">
                            <span className="text-sm text-slate-600">Term of Loan in Months</span>
                            <span className="text-sm font-bold text-slate-900">{termMonths}</span>
                        </div>
                        <div className="flex justify-between px-4 py-2">
                            <span className="text-sm text-slate-600">Payment Frequency</span>
                            <span className="text-sm font-bold text-slate-900">Monthly</span>
                        </div>
                    </div>
                </div>

                {/* Payment Summary */}
                <div className="bg-white border border-slate-300 shadow-sm">
                    <div className="bg-slate-100 px-4 py-2 border-b border-slate-300">
                        <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider">Payment Summary</h3>
                    </div>
                    <div className="divide-y divide-slate-200">
                        <div className="flex justify-between px-4 py-2">
                            <span className="text-sm text-slate-600">Total Amount Due</span>
                            <span className="text-sm font-bold text-slate-900">{safeFormatCurrency(totalPayments)}</span>
                        </div>
                        <div className="flex justify-between px-4 py-2">
                            <span className="text-sm text-slate-600">Total Paid</span>
                            <span className="text-sm font-bold text-emerald-600">{safeFormatCurrency(totalPaid)}</span>
                        </div>
                        <div className="flex justify-between px-4 py-2">
                            <span className="text-sm text-slate-600">Remaining Balance</span>
                            <span className="text-sm font-bold text-red-600">{safeFormatCurrency(totalPayments - totalPaid)}</span>
                        </div>
                        <div className="flex justify-between px-4 py-2">
                            <span className="text-sm text-slate-600">Payments Made</span>
                            <span className="text-sm font-bold text-slate-900">
                                {amortizationRows.filter(r => r.status === 'paid').length} of {amortizationRows.length}
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            <h2 className="text-lg font-bold text-slate-800 mt-8 mb-4">Payment Schedule</h2>

            {/* Amortization Table */}
            <div className="border border-slate-300 overflow-hidden bg-white shadow-sm">
                <table className="w-full text-[13px]">
                    <thead className="bg-[#2d3748] text-white">
                        <tr>
                            <th className="px-2 py-3 text-center font-semibold border-r border-slate-600 w-10">No.</th>
                            <th className="px-2 py-3 text-center font-semibold border-r border-slate-600">Due Date</th>
                            <th className="px-2 py-3 text-center font-semibold border-r border-slate-600">Amount Due</th>
                            <th className="px-2 py-3 text-center font-semibold border-r border-slate-600">Principal</th>
                            <th className="px-2 py-3 text-center font-semibold border-r border-slate-600">Interest</th>
                            <th className="px-2 py-3 text-center font-semibold border-r border-slate-600">Payment Made</th>
                            <th className="px-2 py-3 text-center font-semibold border-r border-slate-600">Payment Date</th>
                            <th className="px-2 py-3 text-center font-semibold">Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr className="bg-slate-50 border-b border-slate-200 text-slate-800">
                            <td colSpan={7} className="px-3 py-2 text-center font-bold">Initial Balance</td>
                            <td className="px-3 py-2 text-right font-bold border-l border-slate-300">
                                {safeFormatCurrency(principal)}
                            </td>
                        </tr>
                        {amortizationRows.map((row) => (
                            <tr key={row.installmentNumber} className="border-b border-slate-200 hover:bg-slate-50 transition-colors text-slate-900">
                                <td className="px-2 py-2 text-center text-slate-600 border-r border-slate-200">{row.installmentNumber}</td>
                                <td className="px-2 py-2 text-center border-r border-slate-200">{formatDate(row.dueDate)}</td>
                                <td className="px-2 py-2 text-center font-medium border-r border-slate-200">{safeFormatCurrency(row.totalDue)}</td>
                                <td className="px-2 py-2 text-center border-r border-slate-200">{safeFormatCurrency(row.principalDue)}</td>
                                <td className="px-2 py-2 text-center border-r border-slate-200">{safeFormatCurrency(row.interestDue)}</td>
                                <td className="px-2 py-2 text-center font-bold text-slate-700 border-r border-slate-200">
                                    {parseFloat(String(row.totalPaid)) > 0 ? safeFormatCurrency(row.totalPaid) : '-'}
                                </td>
                                <td className="px-2 py-2 text-center text-slate-600 border-r border-slate-200">
                                    {row.paymentDate ? formatDate(row.paymentDate) : '-'}
                                </td>
                                <td className="px-2 py-2 text-center">
                                    {getStatusBadge(row.status, row.dueDate)}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}
