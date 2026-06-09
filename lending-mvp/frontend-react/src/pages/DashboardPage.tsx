import { useQuery } from '@tanstack/react-query'
import { formatCurrency } from '@/lib/utils'
import {
    Users,
    PiggyBank,
    CreditCard,
    AlertCircle,
    TrendingUp,
} from 'lucide-react'
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts'

const DASHBOARD_QUERY = `query {
    dashboardStats {
        customersTotal loansTotal activeLoans totalPortfolio overdueLoans totalCollections collectedThisMonth totalOutstanding
    }
    collectionsDashboard {
        totalLoans totalOutstanding totalCollections pendingCollections overdueCollections collectedThisMonth
        buckets { label loanCount totalOutstanding }
    }
}`

interface DashboardData {
    dashboardStats: {
        customersTotal: number
        loansTotal: number
        activeLoans: number
        totalPortfolio: string
        overdueLoans: number
        totalCollections: string
        collectedThisMonth: string
        totalOutstanding: string
    }
    collectionsDashboard: {
        totalLoans: number
        totalOutstanding: string
        totalCollections: string
        pendingCollections: string
        overdueCollections: string
        collectedThisMonth: string
        buckets: Array<{ label: string; loanCount: number; totalOutstanding: string }>
    }
}

function fetchGraphQL<T>(query: string): Promise<T> {
    const token = localStorage.getItem('access_token')
    return fetch('/graphql', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: token ? `Bearer ${token}` : '' },
        body: JSON.stringify({ query }),
    }).then(res => res.json())
}

interface StatCardProps {
    title: string
    value: string
    subtitle?: string
    icon: React.ElementType
    gradient: string
    trend?: string
}

function StatCard({ title, value, subtitle, icon: Icon, gradient, trend }: StatCardProps) {
    return (
        <div className="stat-card group">
            <div className="flex items-start justify-between">
                <div>
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{title}</p>
                    <p className="text-2xl font-bold text-foreground mt-1">{value}</p>
                    {subtitle && <p className="text-xs text-muted-foreground mt-0.5">{subtitle}</p>}
                </div>
                <div className={`w-10 h-10 rounded-xl ${gradient} flex items-center justify-center shadow-lg flex-shrink-0`}>
                    <Icon className="w-5 h-5 text-white" />
                </div>
            </div>
            {trend && (
                <div className="flex items-center gap-1 text-xs text-emerald-400">
                    <TrendingUp className="w-3 h-3" />
                    {trend}
                </div>
            )}
        </div>
    )
}

export default function DashboardPage() {
    const { data, isLoading } = useQuery({
        queryKey: ['dashboard'],
        queryFn: () => fetchGraphQL<{ data: DashboardData }>(DASHBOARD_QUERY),
        refetchInterval: 30000,
        staleTime: 10000,
    })

    const stats = data?.data?.dashboardStats
    const coll = data?.data?.collectionsDashboard
    const loading = isLoading

    const totalCustomers = stats?.customersTotal ?? 0
    const activeLoans = stats?.activeLoans ?? 0
    const totalPortfolio = parseFloat(String(stats?.totalPortfolio || 0))
    const overdueLoans = stats?.overdueLoans ?? 0
    const totalCollections = parseFloat(String(coll?.totalCollections || stats?.totalCollections || 0))
    const collectedThisMonth = parseFloat(String(coll?.collectedThisMonth || stats?.collectedThisMonth || 0))
    const totalOutstanding = parseFloat(String(coll?.totalOutstanding || stats?.totalOutstanding || 0))

    const buckets = coll?.buckets || []
    const chartData = buckets.length > 0
        ? buckets.map(b => ({ name: b.label, amount: parseFloat(String(b.totalOutstanding)), count: b.loanCount }))
        : [
            { name: 'Current', amount: Math.max(0, totalPortfolio - totalOutstanding), count: Math.max(0, activeLoans - overdueLoans) },
            { name: 'Overdue', amount: totalOutstanding, count: overdueLoans },
        ]

    return (
        <div className="space-y-6 animate-fade-in">
            {/* Header */}
            <div>
                <h1 className="text-2xl font-bold text-foreground">Dashboard</h1>
                <p className="text-muted-foreground text-sm mt-1">
                    Overview of your lending portfolio
                </p>
            </div>

            {/* Stats Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
                <StatCard
                    title="Total Customers"
                    value={loading ? '—' : totalCustomers.toLocaleString()}
                    subtitle="Registered members"
                    icon={Users}
                    gradient="gradient-primary"
                />
                <StatCard
                    title="Collections"
                    value={loading ? '—' : formatCurrency(collectedThisMonth)}
                    subtitle="Collected this month"
                    icon={PiggyBank}
                    gradient="gradient-success"
                    trend={loading ? undefined : `${totalCollections > 0 ? ((collectedThisMonth / totalCollections) * 100).toFixed(1) : 0}% of total`}
                />
                <StatCard
                    title="Loan Portfolio"
                    value={loading ? '—' : formatCurrency(totalPortfolio)}
                    subtitle={`${activeLoans} active loans`}
                    icon={CreditCard}
                    gradient="gradient-warning"
                />
                <StatCard
                    title="Overdue Loans"
                    value={loading ? '—' : overdueLoans.toString()}
                    subtitle={`₱${totalOutstanding.toLocaleString()} outstanding`}
                    icon={AlertCircle}
                    gradient="gradient-destructive"
                />
            </div>

            {/* Portfolio Chart */}
            <div className="glass rounded-2xl p-6 shadow-xl">
                <h2 className="text-lg font-semibold text-foreground mb-4">Portfolio Aging</h2>
                <div className="h-[300px]">
                    <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={chartData}>
                            <defs>
                                <linearGradient id="colorAmount" x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="5%" stopColor="#8884d8" stopOpacity={0.8}/>
                                    <stop offset="95%" stopColor="#8884d8" stopOpacity={0}/>
                                </linearGradient>
                            </defs>
                            <XAxis dataKey="name" stroke="#888888" fontSize={12} tickLine={false} axisLine={false} />
                            <YAxis stroke="#888888" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(value) => `₱${value/1000}k`} />
                            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                            <Tooltip 
                                contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: '8px' }}
                                itemStyle={{ color: '#fff' }}
                            />
                            <Area type="monotone" dataKey="amount" stroke="#8884d8" fillOpacity={1} fill="url(#colorAmount)" name="Amount" />
                        </AreaChart>
                    </ResponsiveContainer>
                </div>
            </div>
        </div>
    )
}
