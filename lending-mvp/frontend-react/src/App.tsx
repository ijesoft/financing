import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from '@/context/AuthContext'
import Sidebar from '@/components/layout/Sidebar'
import LoginPage from '@/pages/LoginPage'
import DashboardPage from '@/pages/DashboardPage'
import CustomersPage from '@/pages/CustomersPage'
import CustomerDetailPage from '@/pages/CustomerDetailPage'
import SavingsPage from '@/pages/SavingsPage'
import LoansPage from '@/pages/LoansPage'
import LoanDetailPage from '@/pages/LoanDetailPage'
import LoanProductsPage from '@/pages/LoanProductsPage'
import TransactionsPage from '@/pages/TransactionsPage'
import BranchesPage from '@/pages/BranchesPage'
import AuditLogPage from '@/pages/AuditLogPage'
import UsersPage from '@/pages/UsersPage'
import CollectionsPage from '@/pages/CollectionsPage'
import ChartOfAccountsPage from '@/pages/ChartOfAccountsPage'
import JournalEntriesPage from '@/pages/JournalEntriesPage'
import CreateJournalEntryPage from '@/pages/CreateJournalEntryPage'
import SavingsDetailPage from '@/pages/SavingsDetailPage'
import SavingsTransactionPage from '@/pages/SavingsTransactionPage'
import CustomerDashboardPage from '@/pages/CustomerDashboardPage'
import CustomerLoanApplicationPage from '@/pages/CustomerLoanApplicationPage'
import CustomerRepaymentHistoryPage from '@/pages/CustomerRepaymentHistoryPage'
import CustomerTransferPage from '@/pages/CustomerTransferPage'
import NewCustomerPage from '@/pages/NewCustomerPage'
import EditCustomerPage from '@/pages/EditCustomerPage'
import TellerCashDrawerPage from '@/pages/TellerCashDrawerPage'
import TellerPaymentGatewayPage from '@/pages/TellerPaymentGatewayPage'
import TellerTransactionLimitsPage from '@/pages/TellerTransactionLimitsPage'
import TellerQRCodePage from '@/pages/TellerQRCodePage'
import NotificationPreferencesPage from '@/pages/NotificationPreferencesPage'
import CollectionDuePage from '@/pages/CollectionDuePage'
import AmortizationSchedulePage from '@/pages/AmortizationSchedulePage'
import PaymentHistoryPage from '@/pages/PaymentHistoryPage'
import TrialBalancePage from '@/pages/reports/TrialBalancePage'
import IncomeStatementPage from '@/pages/reports/IncomeStatementPage'
import BalanceSheetPage from '@/pages/reports/BalanceSheetPage'
import ARAgingPage from '@/pages/reports/ARAgingPage'
import APAgingPage from '@/pages/reports/APAgingPage'

function ProtectedLayout() {
    const { isAuthenticated } = useAuth()
    if (!isAuthenticated) return <Navigate to="/login" replace />
    return (
        <div className="flex min-h-screen bg-background">
            <Sidebar />
            <main
                className="flex-1 overflow-auto"
                style={{ marginLeft: 'var(--sidebar-width)' }}
            >
                <div className="p-6 max-w-screen-2xl mx-auto">
                    <Routes>
                        <Route path="/dashboard" element={<DashboardPage />} />
                        <Route path="/customer/dashboard" element={<CustomerDashboardPage />} />
                        <Route path="/customer/loans/new" element={<CustomerLoanApplicationPage />} />
                        <Route path="/customer/loans/repayment" element={<CustomerRepaymentHistoryPage />} />
                        <Route path="/customer/transfer" element={<CustomerTransferPage />} />
                        <Route path="/teller/cash-drawer" element={<TellerCashDrawerPage />} />
                        <Route path="/teller/payment-gateway" element={<TellerPaymentGatewayPage />} />
                        <Route path="/teller/transaction-limits" element={<TellerTransactionLimitsPage />} />
                        <Route path="/teller/qrcode" element={<TellerQRCodePage />} />
                        <Route path="/customer/notifications" element={<NotificationPreferencesPage />} />
                        <Route path="/customers" element={<CustomersPage />} />
                        <Route path="/customers/new" element={<NewCustomerPage />} />
                        <Route path="/customers/:id/edit" element={<EditCustomerPage />} />
                        <Route path="/customers/:id" element={<CustomerDetailPage />} />
                        <Route path="/savings" element={<SavingsPage />} />
                        <Route path="/loans" element={<LoansPage />} />
                        <Route path="/loans/:id" element={<LoanDetailPage />} />
                        <Route path="/loan-products" element={<LoanProductsPage />} />
                        <Route path="/transactions" element={<TransactionsPage />} />
                        <Route path="/branches" element={<BranchesPage />} />
                        <Route path="/audit-logs" element={<AuditLogPage />} />
                        <Route path="/users" element={<UsersPage />} />
                        <Route path="/collections" element={<CollectionsPage />} />
                        <Route path="/collection-due" element={<CollectionDuePage />} />
                        <Route path="/loans/:id/amortization" element={<AmortizationSchedulePage />} />
                        <Route path="/loans/:id/payment-history" element={<PaymentHistoryPage />} />
                        <Route path="/chart-of-accounts" element={<ChartOfAccountsPage />} />
                        <Route path="/journal-entries" element={<JournalEntriesPage />} />
                        <Route path="/journal-entries/create" element={<CreateJournalEntryPage />} />
                        <Route path="/reports/trial-balance" element={<TrialBalancePage />} />
                        <Route path="/reports/income-statement" element={<IncomeStatementPage />} />
                        <Route path="/reports/balance-sheet" element={<BalanceSheetPage />} />
                        <Route path="/reports/ar-aging" element={<ARAgingPage />} />
                        <Route path="/reports/ap-aging" element={<APAgingPage />} />
                        <Route path="/savings/:id" element={<SavingsDetailPage />} />
                        <Route path="/savings/:id/transaction" element={<SavingsTransactionPage />} />
                        <Route path="*" element={<Navigate to="/dashboard" replace />} />
                    </Routes>
                </div>
            </main>
        </div>
    )
}


function AppRoutes() {
    const { isAuthenticated } = useAuth()
    return (
        <Routes>
            <Route
                path="/login"
                element={isAuthenticated ? <Navigate to="/dashboard" replace /> : <LoginPage />}
            />
            <Route path="/*" element={<ProtectedLayout />} />
        </Routes>
    )
}

export default function App() {
    return (
        <AuthProvider>
            <AppRoutes />
        </AuthProvider>
    )
}
