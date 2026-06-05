import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery } from '@apollo/client'
import { CREATE_CUSTOMER } from '@/api/queries'
import { Users, Loader2, ArrowLeft } from 'lucide-react'

export default function CreateCustomerPage() {
    const navigate = useNavigate()
    const [createCustomer, { loading }] = useMutation(CREATE_CUSTOMER)
    const [formData, setFormData] = useState({
        customerType: 'individual',
        firstName: '',
        lastName: '',
        displayName: '',
        emailAddress: '',
        mobileNumber: '',
        branch: 'HQ',
    })
    const [error, setError] = useState('')

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setError('')
        try {
            await createCustomer({
                variables: {
                    input: {
                        customer_type: formData.customerType,
                        first_name: formData.firstName,
                        last_name: formData.lastName,
                        display_name: formData.displayName,
                        email_address: formData.emailAddress,
                        mobile_number: formData.mobileNumber,
                        branch: formData.branch,
                    },
                },
            })
            navigate('/customers')
        } catch (err: any) {
            setError(err.message || 'Failed to create customer')
        }
    }

    return (
        <div className="max-w-2xl mx-auto space-y-6 animate-fade-in">
            <button
                onClick={() => navigate('/customers')}
                className="flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors"
            >
                <ArrowLeft className="w-4 h-4" /> Back to Customers
            </button>

            <div className="glass rounded-2xl p-6">
                <h1 className="text-2xl font-bold text-foreground flex items-center gap-2 mb-6">
                    <Users className="w-6 h-6 text-primary" /> Add New Customer
                </h1>

                {error && (
                    <div className="mb-4 px-4 py-3 bg-destructive/10 border border-destructive/20 rounded-lg text-sm text-destructive">
                        {error}
                    </div>
                )}

                <form onSubmit={handleSubmit} className="space-y-5">
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium text-foreground mb-1.5">Customer Type</label>
                            <select
                                value={formData.customerType}
                                onChange={(e) => setFormData({ ...formData, customerType: e.target.value })}
                                className="w-full px-4 py-2.5 bg-secondary/50 border border-border rounded-lg text-sm text-foreground"
                            >
                                <option value="individual">Individual</option>
                                <option value="joint">Joint</option>
                                <option value="corporate">Corporate</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-foreground mb-1.5">Branch</label>
                            <select
                                value={formData.branch}
                                onChange={(e) => setFormData({ ...formData, branch: e.target.value })}
                                className="w-full px-4 py-2.5 bg-secondary/50 border border-border rounded-lg text-sm text-foreground"
                            >
                                <option value="HQ">Head Office</option>
                                <option value="BR-QC">Quezon City Branch</option>
                                <option value="BR-CDO">Cagayan de Oro Branch</option>
                            </select>
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium text-foreground mb-1.5">First Name</label>
                            <input
                                type="text"
                                value={formData.firstName}
                                onChange={(e) => setFormData({ ...formData, firstName: e.target.value })}
                                className="w-full px-4 py-2.5 bg-secondary/50 border border-border rounded-lg text-sm text-foreground"
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-foreground mb-1.5">Last Name</label>
                            <input
                                type="text"
                                value={formData.lastName}
                                onChange={(e) => setFormData({ ...formData, lastName: e.target.value })}
                                className="w-full px-4 py-2.5 bg-secondary/50 border border-border rounded-lg text-sm text-foreground"
                            />
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-foreground mb-1.5">Display Name *</label>
                        <input
                            type="text"
                            value={formData.displayName}
                            onChange={(e) => setFormData({ ...formData, displayName: e.target.value })}
                            required
                            className="w-full px-4 py-2.5 bg-secondary/50 border border-border rounded-lg text-sm text-foreground"
                            placeholder="How customer name appears"
                        />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium text-foreground mb-1.5">Email Address *</label>
                            <input
                                type="email"
                                value={formData.emailAddress}
                                onChange={(e) => setFormData({ ...formData, emailAddress: e.target.value })}
                                required
                                className="w-full px-4 py-2.5 bg-secondary/50 border border-border rounded-lg text-sm text-foreground"
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-foreground mb-1.5">Mobile Number</label>
                            <input
                                type="text"
                                value={formData.mobileNumber}
                                onChange={(e) => setFormData({ ...formData, mobileNumber: e.target.value })}
                                className="w-full px-4 py-2.5 bg-secondary/50 border border-border rounded-lg text-sm text-foreground"
                            />
                        </div>
                    </div>

                    <div className="flex gap-3 pt-4">
                        <button
                            type="button"
                            onClick={() => navigate('/customers')}
                            className="flex-1 px-4 py-2.5 border border-border text-foreground rounded-lg hover:bg-secondary/50 transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={loading}
                            className="flex-1 px-4 py-2.5 gradient-primary text-white font-semibold rounded-lg shadow-lg disabled:opacity-50"
                        >
                            {loading ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : 'Create Customer'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    )
}
