import { useState, useEffect } from 'react'
import { Plus, Pencil, Trash2, X } from 'lucide-react'
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

interface ProductForm {
    productCode: string
    name: string
    description: string
    amortizationType: string
    repaymentFrequency: string
    interestRate: string
    penaltyRate: string
    gracePeriodMonths: string
}

const emptyForm: ProductForm = {
    productCode: '',
    name: '',
    description: '',
    amortizationType: 'flat_rate',
    repaymentFrequency: 'monthly',
    interestRate: '',
    penaltyRate: '0',
    gracePeriodMonths: '0',
}

const AMORTIZATION_TYPES = [
    { value: 'flat_rate', label: 'Flat Rate' },
    { value: 'declining_balance', label: 'Declining Balance' },
    { value: 'balloon_payment', label: 'Balloon Payment' },
    { value: 'interest_only', label: 'Interest Only' },
]

const REPAYMENT_FREQUENCIES = [
    { value: 'daily', label: 'Daily' },
    { value: 'weekly', label: 'Weekly' },
    { value: 'bi_weekly', label: 'Bi-Weekly' },
    { value: 'monthly', label: 'Monthly' },
    { value: 'quarterly', label: 'Quarterly' },
    { value: 'bullet', label: 'Bullet' },
]

export default function LoanProductsPage() {
    const { user } = useAuth()
    const isAdmin = user?.role === 'admin'

    const [loading, setLoading] = useState(true)
    const [productsData, setProductsData] = useState<LoanProduct[]>([])
    const [showModal, setShowModal] = useState(false)
    const [form, setForm] = useState<ProductForm>(emptyForm)
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState('')

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

    const openCreate = () => {
        setForm(emptyForm)
        setError('')
        setShowModal(true)
    }

    const handleSave = async () => {
        if (!form.productCode.trim() || !form.name.trim() || !form.interestRate) {
            setError('Product Code, Name, and Interest Rate are required')
            return
        }
        setSaving(true)
        setError('')
        const token = localStorage.getItem('access_token')
        try {
            const res = await fetch('/graphql', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': token ? `Bearer ${token}` : '' },
                body: JSON.stringify({
                    query: `mutation CreateLoanProduct($input: LoanProductCreateInput!) {
                        createLoanProduct(input: $input) { success message }
                    }`,
                    variables: {
                        input: {
                            productCode: form.productCode.trim(),
                            name: form.name.trim(),
                            description: form.description.trim() || null,
                            amortizationType: form.amortizationType,
                            repaymentFrequency: form.repaymentFrequency,
                            interestRate: parseFloat(form.interestRate),
                            penaltyRate: parseFloat(form.penaltyRate) || 0,
                            gracePeriodMonths: parseInt(form.gracePeriodMonths) || 0,
                        }
                    }
                })
            })
            const data = await res.json()
            if (data.data?.createLoanProduct?.success) {
                setShowModal(false)
                init()
            } else {
                setError(data.data?.createLoanProduct?.message || data.errors?.[0]?.message || 'Failed to create product')
            }
        } catch (e: any) {
            setError(e.message || 'Failed to create product')
        } finally {
            setSaving(false)
        }
    }

    return (
        <div className="space-y-6 animate-fade-in">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-foreground">Loan Products</h1>
                    <p className="text-muted-foreground text-sm mt-1">Manage loan product offerings</p>
                </div>
                {isAdmin && (
                    <button
                        onClick={openCreate}
                        className="flex items-center gap-2 px-4 py-2 rounded-lg gradient-primary text-white text-sm font-medium shadow-lg hover:opacity-90 transition-opacity"
                    >
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

            {showModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => !saving && setShowModal(false)}>
                    <div className="glass rounded-xl p-6 w-full max-w-lg border border-border/50 shadow-2xl max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="text-lg font-bold text-foreground">New Loan Product</h2>
                            <button onClick={() => setShowModal(false)} disabled={saving} className="p-1 rounded-lg hover:bg-white/10 text-muted-foreground transition-colors">
                                <X className="w-5 h-5" />
                            </button>
                        </div>
                        <div className="space-y-4">
                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">Product Code *</label>
                                    <input
                                        value={form.productCode}
                                        onChange={e => setForm({ ...form, productCode: e.target.value })}
                                        placeholder="e.g. PER-LN-01"
                                        className="w-full px-3 py-2 rounded-lg border border-border bg-background/50 text-foreground text-sm focus:outline-none focus:border-primary/50"
                                    />
                                </div>
                                <div>
                                    <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">Name *</label>
                                    <input
                                        value={form.name}
                                        onChange={e => setForm({ ...form, name: e.target.value })}
                                        placeholder="e.g. Personal Loan"
                                        className="w-full px-3 py-2 rounded-lg border border-border bg-background/50 text-foreground text-sm focus:outline-none focus:border-primary/50"
                                    />
                                </div>
                            </div>
                            <div>
                                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">Description</label>
                                <textarea
                                    value={form.description}
                                    onChange={e => setForm({ ...form, description: e.target.value })}
                                    placeholder="Product description..."
                                    rows={2}
                                    className="w-full px-3 py-2 rounded-lg border border-border bg-background/50 text-foreground text-sm focus:outline-none focus:border-primary/50 resize-none"
                                />
                            </div>
                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">Amortization Type *</label>
                                    <select
                                        value={form.amortizationType}
                                        onChange={e => setForm({ ...form, amortizationType: e.target.value })}
                                        className="w-full px-3 py-2 rounded-lg border border-border bg-background/50 text-foreground text-sm focus:outline-none focus:border-primary/50"
                                    >
                                        {AMORTIZATION_TYPES.map(t => (
                                            <option key={t.value} value={t.value}>{t.label}</option>
                                        ))}
                                    </select>
                                </div>
                                <div>
                                    <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">Repayment Frequency *</label>
                                    <select
                                        value={form.repaymentFrequency}
                                        onChange={e => setForm({ ...form, repaymentFrequency: e.target.value })}
                                        className="w-full px-3 py-2 rounded-lg border border-border bg-background/50 text-foreground text-sm focus:outline-none focus:border-primary/50"
                                    >
                                        {REPAYMENT_FREQUENCIES.map(f => (
                                            <option key={f.value} value={f.value}>{f.label}</option>
                                        ))}
                                    </select>
                                </div>
                            </div>
                            <div className="grid grid-cols-3 gap-3">
                                <div>
                                    <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">Interest Rate (%) *</label>
                                    <input
                                        type="number"
                                        step="0.01"
                                        value={form.interestRate}
                                        onChange={e => setForm({ ...form, interestRate: e.target.value })}
                                        placeholder="e.g. 14"
                                        className="w-full px-3 py-2 rounded-lg border border-border bg-background/50 text-foreground text-sm focus:outline-none focus:border-primary/50"
                                    />
                                </div>
                                <div>
                                    <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">Penalty Rate (%)</label>
                                    <input
                                        type="number"
                                        step="0.01"
                                        value={form.penaltyRate}
                                        onChange={e => setForm({ ...form, penaltyRate: e.target.value })}
                                        placeholder="0"
                                        className="w-full px-3 py-2 rounded-lg border border-border bg-background/50 text-foreground text-sm focus:outline-none focus:border-primary/50"
                                    />
                                </div>
                                <div>
                                    <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">Grace Period (months)</label>
                                    <input
                                        type="number"
                                        value={form.gracePeriodMonths}
                                        onChange={e => setForm({ ...form, gracePeriodMonths: e.target.value })}
                                        placeholder="0"
                                        className="w-full px-3 py-2 rounded-lg border border-border bg-background/50 text-foreground text-sm focus:outline-none focus:border-primary/50"
                                    />
                                </div>
                            </div>
                            {error && (
                                <p className="text-xs text-red-400 bg-red-500/10 rounded-lg px-3 py-2">{error}</p>
                            )}
                            <div className="flex gap-2 justify-end pt-2">
                                <button
                                    onClick={() => setShowModal(false)}
                                    disabled={saving}
                                    className="px-4 py-2 rounded-lg border border-border text-sm text-muted-foreground hover:bg-white/5 transition-colors disabled:opacity-50"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleSave}
                                    disabled={saving}
                                    className="px-4 py-2 rounded-lg gradient-primary text-white text-sm font-medium shadow-lg hover:opacity-90 transition-opacity disabled:opacity-50"
                                >
                                    {saving ? 'Saving...' : 'Create Product'}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
