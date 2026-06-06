import { useState, useEffect } from 'react'
import { Plus, Pencil, Trash2 } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { formatCurrency } from '@/lib/utils'

interface LoanProduct {
    id: string
    name: string
    productCode: string
    description: string
    interestRate: number
    termMonths: number
    minLoanAmount?: number
    maxLoanAmount?: number
}

export default function LoanProductsPage() {
    const { user } = useAuth()
    const isAdmin = user?.role === 'admin'

    const [loading, setLoading] = useState(true)
    const [productsData, setProductsData] = useState<LoanProduct[]>([])

    const init = async () => {
        try {
            const res = await fetch('/graphql', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query: `query GetLoanProducts { loanProducts { id name productCode description interestRate termMonths minLoanAmount maxLoanAmount } }`
                })
            })
            const data = await res.json()
            setProductsData((data.data?.loanProducts || []).map((p: any) => ({
                ...p,
                interestRate: Number(p.interestRate),
                minLoanAmount: p.minLoanAmount ? Number(p.minLoanAmount) : undefined,
                maxLoanAmount: p.maxLoanAmount ? Number(p.maxLoanAmount) : undefined,
            })))
        } catch (e) {
            console.error('Failed to fetch loan products:', e)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => { init() }, [])

    return (
        <div className="space-y-6 animate-fade-in">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-foreground">Loan Products</h1>
                    <p className="text-muted-foreground text-sm mt-1">Manage loan product offerings</p>
                </div>
                {isAdmin && (
                    <button className="flex items-center gap-2 px-4 py-2 rounded-lg gradient-primary text-white text-sm font-medium shadow-lg hover:opacity-90 transition-opacity">
                        <Plus className="w-4 h-4" /> New Product
                    </button>
                )}
            </div>

            {loading ? (
                <div className="text-center py-16 text-muted-foreground">Loading loan products…</div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {productsData.length === 0 ? (
                        <div className="col-span-full text-center py-12 text-muted-foreground">No loan products found.</div>
                    ) : productsData.map((product) => (
                        <div key={product.id} className="glass rounded-xl p-4 space-y-3">
                            <div className="flex items-start justify-between">
                                <div>
                                    <h3 className="font-semibold text-foreground">{product.name}</h3>
                                    <p className="text-xs text-muted-foreground">{product.productCode}</p>
                                </div>
                                {isAdmin && (
                                    <div className="flex gap-1">
                                        <button className="p-1 rounded-lg hover:bg-primary/15 text-primary transition-colors">
                                            <Pencil className="w-4 h-4" />
                                        </button>
                                        <button className="p-1 rounded-lg hover:bg-destructive/15 text-destructive transition-colors">
                                            <Trash2 className="w-4 h-4" />
                                        </button>
                                    </div>
                                )}
                            </div>
                            <p className="text-sm text-muted-foreground line-clamp-2">{product.description}</p>
                            <div className="pt-3 border-t border-border/50 space-y-2">
                                <div className="flex justify-between text-sm">
                                    <span className="text-muted-foreground">Interest Rate:</span>
                                    <span className="text-foreground font-medium">{product.interestRate}%</span>
                                </div>
                                <div className="flex justify-between text-sm">
                                    <span className="text-muted-foreground">Term:</span>
                                    <span className="text-foreground font-medium">{product.termMonths} months</span>
                                </div>
                                {product.minLoanAmount && (
                                    <div className="flex justify-between text-sm">
                                        <span className="text-muted-foreground">Min Amount:</span>
                                        <span className="text-foreground font-medium">{formatCurrency(product.minLoanAmount)}</span>
                                    </div>
                                )}
                                {product.maxLoanAmount && (
                                    <div className="flex justify-between text-sm">
                                        <span className="text-muted-foreground">Max Amount:</span>
                                        <span className="text-foreground font-medium">{formatCurrency(product.maxLoanAmount)}</span>
                                    </div>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
