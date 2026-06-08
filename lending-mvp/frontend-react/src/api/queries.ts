
// This file is deprecated. Please use the new native fetch API clients.
// Migration guide:
// - Customers: Use @/api/customers.ts
// - Users: Use @/api/users.ts  
// - Loans: Use @/api/loans.ts
// - Branches: Use @/api/client.ts (getBranches)
//
// To migrate a page:
// 1. Replace Apollo useQuery/useMutation with fetch() calls
// 2. Use the new API clients in @/api/
// 3. Remove Apollo Client imports
//
// Example migration for a simple query:
// OLD (Apollo):
//   const { data, loading, error } = useQuery(GET_CUSTOMERS)
//   
// NEW (Native fetch):
//   const [data, setData] = useState(null)
//   useEffect(() => {
//     getCustomers().then(setData).catch(console.error)
//   }, [])

// Apollo Client GraphQL queries (deprecated - keep for backward compatibility)
export const GET_SAVINGS_ACCOUNT = `
  query GetSavingsAccount($id: ID!) {
    savingsAccounts(searchTerm: $id) {
      accounts {
        id
        accountNumber
        userId
        type
        balance
        currency
        openedAt
        status
        createdAt
        updatedAt
        interestRate
        maturityDate
        targetAmount
        targetDate
        customer {
          displayName
        }
      }
    }
  }
`

export const GET_SAVINGS_TRANSACTIONS = `
  query GetSavingsTransactions($accountId: ID!) {
    getTransactions(accountId: $accountId) {
      transactions {
        id
        transactionType
        amount
        timestamp
        notes
      }
    }
  }
`

export const GET_JOURNAL_ENTRY_BY_REFERENCE = `
  query GetJournalEntryByReference($referenceNo: String!) {
    journalEntryByReference(referenceNo: $referenceNo) {
      id
      referenceNo
      description
      timestamp
      lines {
        id
        accountCode
        debit
        credit
        description
      }
    }
  }
`

export const GET_CUSTOMERS = `
  query GetCustomers($searchTerm: String, $limit: Int) {
    customers(searchTerm: $searchTerm, limit: $limit) {
      customers {
        id
        displayName
        firstName
        lastName
        emailAddress
        mobileNumber
        customerType
        customerCategory
        kycStatus
        riskScore
        branch
        createdAt
      }
    }
  }
`

export const GET_LOAN_PRODUCTS = `
  query GetLoanProducts {
    loanProducts {
      id
      name
      interestRate
      description
      minAmount
      maxAmount
      termOptions
    }
  }
`

export const GET_LOANS = `
  query GetLoans {
    loans {
      loans {
        id
        customer {
          id
          displayName
        }
        product {
          id
          name
          interestRate
        }
        principal
        outstandingBalance
        status
        startDate
        endDate
      }
    }
  }
`

export const CREATE_LOAN = `
  mutation CreateLoan($input: LoanInput!) {
    createLoan(input: $input) {
      success
      message
      loan {
        id
        referenceNo
        principal
        outstandingBalance
        status
        startDate
      }
    }
  }
`

export const GET_CUSTOMER_LOANS = `
  query GetCustomerLoans {
    loans {
      id
      customer {
        id
        displayName
      }
      product {
        id
        name
      }
      principal
      outstandingBalance
      status
      startDate
      endDate
      repaymentSchedule {
        id
        dueDate
        amount
        status
        paidAt
      }
    }
  }
`

export const CREATE_FUND_TRANSFER = `
  mutation CreateFundTransfer($input: FundTransferInput!) {
    createFundTransfer(input: $input) {
      success
      message
      transaction {
        id
        referenceNo
        amount
        fromAccount
        toAccount
        status
        timestamp
      }
    }
  }
`

export const GET_LOAN = `
  query GetLoan($id: ID!) {
    loan(id: $id) {
      id
      customerId
      productId
      principal
      termMonths
      approvedPrincipal
      approvedRate
      status
      createdAt
      disbursedAt
      borrowerName
      productName
      startDate
      endDate
    }
  }
`

export const GET_LOAN_AMORTIZATION = `
  query GetLoanAmortization($loanId: ID!) {
    loanAmortization(loanId: $loanId) {
      repaymentFrequency
      rows {
        installmentNumber
        dueDate
        principalDue
        interestDue
        penaltyDue
        principalPaid
        interestPaid
        penaltyPaid
        paymentDate
        status
        totalDue
        totalPaid
      }
    }
  }
`

export const GET_LOAN_TRANSACTIONS = `
  query GetLoanTransactions($loanId: ID) {
    loanTransactions(loanId: $loanId) {
      id
      loanId
      amount
      transactionType
      description
      reference
      createdAt
    }
  }
`
