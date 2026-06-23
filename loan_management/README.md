# Loan Management — Custom App for Frappe HRMS

A standalone employee loan app: apply, approve, disburse, and auto-deduct EMIs
through Payroll.

## What's included

| DocType | Purpose |
|---|---|
| **Loan Type** | Master: loan name, max amount, yearly interest rate |
| **Loan Application** | Employee requests a loan; HR Manager approves/rejects |
| **Loan** | Created from an approved application; tracks disbursement, EMI, balance |
| **Loan Repayment Schedule** | Child table on Loan — full month-by-month amortization schedule |

### Functionality
- EMI calculated with the standard reducing-balance formula (interest-free loans supported too — just set rate to 0)
- One-click **Approve / Reject** on Loan Application, **Create Loan** once approved
- One-click **Disburse Loan**, which generates the full repayment schedule
- **Automatic payroll integration**: every Salary Slip run for an employee with
  an active loan automatically gets a "Loan Repayment" deduction row for that
  month's EMI. On submission of the Salary Slip, the matching schedule row is
  marked paid and the loan auto-closes once fully repaid. Cancelling a Salary
  Slip reverses the settlement.

## Installation

You said your bench is already set up, so:

```bash
# 1. From your bench directory, scaffold the app (answer the prompts:
#    app title "Loan Management", same as default works fine)
bench new-app loan_management

# 2. Replace/merge the generated doctype-less app with the files in this package:
#    Copy everything from this package's loan_management/loan_management/ folder
#    into apps/loan_management/loan_management/, overwriting only where it
#    overlaps (it won't, since bench new-app doesn't create any doctypes).
cp -r loan_management/loan_management/* apps/loan_management/loan_management/

# 3. Open apps/loan_management/loan_management/hooks.py and paste in the
#    contents of HOOKS_TO_ADD.py (see comments in that file — don't replace
#    the whole hooks.py, just add those blocks).

# 4. Install on your site
bench --site [your-site-name] install-app loan_management
bench --site [your-site-name] migrate
bench restart
```

This creates the 4 doctypes, sets up permissions for System Manager / HR
Manager / HR User / Employee, and auto-creates a "Loan Repayment" Salary
Component for payroll.

## Usage flow

1. **HR / Setup** → create one or more **Loan Type** records (e.g. "Personal
   Loan", max ₹200,000, 10% yearly interest).
2. **Employee or HR** → creates a **Loan Application**: pick employee, loan
   type, amount, repayment period in months.
3. **HR Manager** → opens the application, clicks **Approve** (or Reject).
4. **HR Manager** → clicks **Create Loan** on the approved application. This
   creates a Loan record in "Sanctioned" status with the EMI already
   calculated.
5. **HR Manager** → opens the Loan, clicks **Disburse Loan**, picks the
   disbursement date. This generates the full repayment schedule and moves
   status to "Disbursed".
6. **Payroll** → from this point on, every monthly Salary Slip for that
   employee automatically picks up the due EMI as a deduction. No manual
   entry needed. The loan auto-closes when the final installment is paid.

## Notes / things you may want to extend later

- **Multiple loans per employee**: already supported — all active loans are
  summed into a single "Loan Repayment" deduction line per Salary Slip. If you
  want them itemized separately, swap the single component for one row per
  loan (the schedule already tracks per-loan amounts).
- **Employee self-service**: Employee role currently gets read + create
  (`if_owner`) on Loan Application. If you're using HRMS's Employee
  Self-Service portal, you may want to add a portal page so employees can
  apply for loans themselves rather than going through the desk UI.
- **Approval workflow**: this uses simple status + whitelisted methods rather
  than Frappe's Workflow engine. If you need multi-level approval, you can
  layer a Workflow on top of the `status` field without touching the Python.
- **Foreclosure / part-payment**: not included in this basic version — would
  need an extra "Loan Repayment" transaction doctype to log out-of-cycle
  payments and a method to regenerate the remaining schedule.
