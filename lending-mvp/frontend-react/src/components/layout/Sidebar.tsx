import { cn } from '@/lib/utils'
import { useAuth } from '@/context/AuthContext'
import { NavLink, useNavigate } from 'react-router-dom'
import {
    LayoutDashboard,
    Users,
    PiggyBank,
    CreditCard,
    ArrowLeftRight,
    Package,
    LogOut,
    ChevronRight,
    Building2,
    GitBranch,
    ScrollText,
    ShieldCheck,
    UserCog,
    AlertTriangle,
    BookOpen,
    FileText,
    Plus,
    Send,
    QrCode,
    Wallet,
    Settings,
    Smartphone,
    Calendar,
    BarChart3,
    Receipt,
    Landmark,
    TrendingUp,
    TrendingDown,
    Bot,
} from 'lucide-react'

// Role-based nav configuration
// Each item can define `roles` (whitelist) — if omitted, visible to all authenticated users
const navItems = [
    { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard', roles: null },
    { to: '/customer/dashboard', icon: LayoutDashboard, label: 'My Portal', roles: ['customer'] },
    { to: '/customers', icon: Users, label: 'Customers', roles: ['admin', 'loan_officer', 'branch_manager', 'teller'] },
    { to: '/savings', icon: PiggyBank, label: 'Savings Accounts', roles: ['admin', 'loan_officer', 'branch_manager', 'teller'] },
    { to: '/loans', icon: CreditCard, label: 'Loans', roles: ['admin', 'loan_officer', 'branch_manager'] },
    { to: '/transactions', icon: ArrowLeftRight, label: 'Transactions', roles: ['admin', 'teller', 'loan_officer', 'branch_manager'] },
    { to: '/loan-products', icon: Package, label: 'Loan Products', roles: ['admin', 'loan_officer', 'branch_manager'] },
    { to: '/collections', icon: AlertTriangle, label: 'Collections', roles: ['admin', 'loan_officer', 'branch_manager'] },
    { to: '/collection-due', icon: Calendar, label: 'Due Collections', roles: ['admin', 'loan_officer', 'branch_manager'] },
    { to: '/ai-assistant', icon: Bot, label: 'AI Assistant', roles: ['admin', 'loan_officer', 'branch_manager', 'collections_officer'] },
    { to: '/chart-of-accounts', icon: BookOpen, label: 'Chart of Accounts', roles: ['admin', 'branch_manager'] },
    { to: '/journal-entries', icon: FileText, label: 'Journal Entries', roles: ['admin', 'branch_manager', 'auditor'] },
    { to: '/branches', icon: GitBranch, label: 'Branches', roles: ['admin', 'branch_manager'] },
    { to: '/audit-logs', icon: ScrollText, label: 'Audit Logs', roles: ['admin', 'auditor'] },
    { to: '/users', icon: UserCog, label: 'User Management', roles: ['admin'] },
    { to: '/teller/cash-drawer', icon: Wallet, label: 'Cash Drawer', roles: ['teller', 'admin'] },
    { to: '/teller/payment-gateway', icon: Smartphone, label: 'Payment Gateway', roles: ['teller', 'admin'] },
    { to: '/teller/transaction-limits', icon: Settings, label: 'Transaction Limits', roles: ['admin'] },
    { to: '/teller/qrcode', icon: QrCode, label: 'QR Code', roles: ['teller', 'admin'] },
    { to: '/customer/notifications', icon: Settings, label: 'Notifications', roles: ['customer'] },
]

export default function Sidebar() {
    const { user, logout } = useAuth()
    const navigate = useNavigate()

    const handleLogout = () => {
        logout()
        navigate('/login')
    }

    // Filter nav items based on role
    const visibleNav = navItems.filter(item =>
        !item.roles || (user?.role && item.roles.includes(user.role))
    )

    const roleLabel: Record<string, string> = {
        admin: 'Administrator',
        loan_officer: 'Loan Officer',
        teller: 'Teller',
        branch_manager: 'Branch Manager',
        auditor: 'Auditor',
        customer: 'Member',
    }

    return (
        <aside
            className="fixed left-0 top-0 h-full flex flex-col glass border-r border-border/50 z-50"
            style={{ width: 'var(--sidebar-width)' }}
        >
            {/* Brand */}
            <div className="px-5 py-5 border-b border-border/50">
                <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-lg gradient-primary flex items-center justify-center shadow-lg">
                        <Building2 className="w-5 h-5 text-white" />
                    </div>
                    <div>
                        <p className="font-bold text-sm text-foreground leading-none">LendingMVP</p>
                        <p className="text-xs text-muted-foreground mt-0.5">Financial Platform</p>
                    </div>
                </div>
            </div>

            {/* Navigation */}
            <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
                {user?.role === 'customer' && (
                    <>
                        <p className="px-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                            My Account
                        </p>
                        <NavLink
                            to="/customer/dashboard"
                            className={({ isActive }) => cn('sidebar-item group', isActive && 'active')}
                        >
                            <LayoutDashboard className="w-4 h-4 flex-shrink-0" />
                            <span className="flex-1">Dashboard</span>
                            <ChevronRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-50 transition-opacity" />
                        </NavLink>
                        <NavLink
                            to="/customer/loans/new"
                            className={({ isActive }) => cn('sidebar-item group', isActive && 'active')}
                        >
                            <FileText className="w-4 h-4 flex-shrink-0" />
                            <span className="flex-1">New Loan</span>
                            <ChevronRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-50 transition-opacity" />
                        </NavLink>
                        <NavLink
                            to="/customer/loans/repayment"
                            className={({ isActive }) => cn('sidebar-item group', isActive && 'active')}
                        >
                            <FileText className="w-4 h-4 flex-shrink-0" />
                            <span className="flex-1">Repayment History</span>
                            <ChevronRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-50 transition-opacity" />
                        </NavLink>
                        <NavLink
                            to="/customer/transfer"
                            className={({ isActive }) => cn('sidebar-item group', isActive && 'active')}
                        >
                            <Send className="w-4 h-4 flex-shrink-0" />
                            <span className="flex-1">Transfer Funds</span>
                            <ChevronRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-50 transition-opacity" />
                        </NavLink>
                        <NavLink
                            to="/customer/notifications"
                            className={({ isActive }) => cn('sidebar-item group', isActive && 'active')}
                        >
                            <Settings className="w-4 h-4 flex-shrink-0" />
                            <span className="flex-1">Notifications</span>
                            <ChevronRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-50 transition-opacity" />
                        </NavLink>
                        <p className="px-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3 mt-4">
                            Settings
                        </p>
                    </>
                )}

                {visibleNav.map(({ to, icon: Icon, label }) => (
                    <NavLink
                        key={to}
                        to={to}
                        className={({ isActive }) =>
                            cn('sidebar-item group', isActive && 'active')
                        }
                    >
                        <Icon className="w-4 h-4 flex-shrink-0" />
                        <span className="flex-1">{label}</span>
                        <ChevronRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-50 transition-opacity" />
                    </NavLink>
                ))}

                {/* Reports section for financial roles */}
                {user?.role && ['admin', 'branch_manager', 'auditor'].includes(user.role) && (
                    <>
                        <p className="px-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3 mt-4">
                            Financial Reports
                        </p>
                        <NavLink to="/reports/trial-balance" className={({ isActive }) => cn('sidebar-item group', isActive && 'active')}>
                            <BarChart3 className="w-4 h-4" />
                            <span className="flex-1">Trial Balance</span>
                            <ChevronRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-50 transition-opacity" />
                        </NavLink>
                        <NavLink to="/reports/income-statement" className={({ isActive }) => cn('sidebar-item group', isActive && 'active')}>
                            <TrendingUp className="w-4 h-4" />
                            <span className="flex-1">Income Statement</span>
                            <ChevronRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-50 transition-opacity" />
                        </NavLink>
                        <NavLink to="/reports/balance-sheet" className={({ isActive }) => cn('sidebar-item group', isActive && 'active')}>
                            <Landmark className="w-4 h-4" />
                            <span className="flex-1">Balance Sheet</span>
                            <ChevronRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-50 transition-opacity" />
                        </NavLink>
                        <NavLink to="/reports/ar-aging" className={({ isActive }) => cn('sidebar-item group', isActive && 'active')}>
                            <Receipt className="w-4 h-4" />
                            <span className="flex-1">AR Aging</span>
                            <ChevronRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-50 transition-opacity" />
                        </NavLink>
                                                <NavLink to="/reports/delinquency" className={({ isActive }) => cn('sidebar-item group', isActive && 'active')}>
                            <AlertTriangle className="w-4 h-4" />
                            <span className="flex-1">Delinquency</span>
                            <ChevronRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-50 transition-opacity" />
                        </NavLink>
                        <NavLink to="/reports/ap-aging" className={({ isActive }) => cn('sidebar-item group', isActive && 'active')}>
                            <TrendingDown className="w-4 h-4" />
                            <span className="flex-1">AP Aging</span>
                            <ChevronRight className="w-3.5 h-3.5 opacity-0 group-hover:opacity-50 transition-opacity" />
                        </NavLink>
                    </>
                )}

                {/* Security indicator for admin */}
                {user?.role === 'admin' && (
                    <div className="mt-4 px-3 py-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                        <div className="flex items-center gap-2 text-xs text-emerald-400">
                            <ShieldCheck className="w-3.5 h-3.5" />
                            <span>Admin Access</span>
                        </div>
                    </div>
                )}
            </nav>

            {/* User Profile */}
            <div className="px-3 py-4 border-t border-border/50">
                <div className="glass rounded-lg p-3 mb-2">
                    <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-full gradient-primary flex items-center justify-center text-white font-semibold text-xs flex-shrink-0">
                            {user?.fullName?.[0]?.toUpperCase() ?? user?.username?.[0]?.toUpperCase() ?? 'U'}
                        </div>
                        <div className="min-w-0 flex-1">
                            <p className="text-sm font-medium text-foreground truncate">
                                {user?.fullName || user?.username}
                            </p>
                            <p className="text-xs text-muted-foreground capitalize">
                                {roleLabel[user?.role ?? ''] ?? user?.role}
                            </p>
                        </div>
                    </div>
                </div>
                <button
                    onClick={handleLogout}
                    className="sidebar-item w-full text-destructive hover:text-destructive hover:bg-destructive/10"
                >
                    <LogOut className="w-4 h-4" />
                    <span>Sign Out</span>
                </button>
            </div>
        </aside>
    )
}
