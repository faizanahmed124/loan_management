# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import math
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, cint, flt, getdate, today


class HRLoan(Document):
	def validate(self):
		self.calculate_repayment_summary()
		self.balance_amount = flt(self.total_payable_amount) - flt(self.total_amount_paid)

	def on_trash(self):
		if self.loan_application and frappe.db.exists("HR Loan Application", self.loan_application):
			frappe.db.set_value("HR Loan Application", self.loan_application, "loan", None)
		# Cancel linked JE if any
		if self.disbursement_journal_entry:
			cancel_journal_entry(self.disbursement_journal_entry)

	def calculate_repayment_summary(self):
		loan = flt(self.loan_amount)
		inst = flt(self.monthly_installment_amount)
		if not loan or not inst:
			return
		self.repayment_periods        = math.ceil(loan / inst)
		self.monthly_repayment_amount = inst
		self.total_payable_amount     = flt(loan, 2)
		self.total_interest_payable   = 0

	def generate_repayment_schedule(self):
		self.set("repayment_schedule", [])
		loan    = flt(self.loan_amount)
		inst    = flt(self.monthly_installment_amount)
		if not loan or not inst:
			return
		balance = loan
		month   = 0
		while balance > 0:
			month        += 1
			payment       = flt(min(inst, balance), 2)
			balance       = flt(balance - payment, 2)
			self.append("repayment_schedule", {
				"payment_date":        add_months(self.disbursement_date, month),
				"principal_amount":    payment,
				"interest_amount":     0,
				"total_payment":       payment,
				"balance_loan_amount": flt(balance, 2),
			})


# ── GL helpers ────────────────────────────────────────────────────────────────

def make_disbursement_journal_entry(loan_doc):
	"""
	Dr: Loan Account (employee receivable)
	Cr: Payment Account (bank / cash)
	"""
	if not loan_doc.loan_account or not loan_doc.payment_account:
		frappe.msgprint(
			_("Loan Account or Disbursement Account not set on Loan Type — skipping GL entry."),
			alert=True, indicator="orange"
		)
		return None

	company_currency = frappe.get_cached_value("Company", loan_doc.company, "default_currency")

	je = frappe.new_doc("Journal Entry")
	je.voucher_type  = "Journal Entry"
	je.company       = loan_doc.company
	je.posting_date  = loan_doc.disbursement_date
	je.user_remark   = f"Loan disbursed to {loan_doc.employee_name} ({loan_doc.employee}) — {loan_doc.name}"
	je.cheque_no     = loan_doc.name
	je.cheque_date   = loan_doc.disbursement_date

	# Debit: Loan (receivable) Account
	je.append("accounts", {
		"account":                    loan_doc.loan_account,
		"debit_in_account_currency":  flt(loan_doc.loan_amount, 2),
		"credit_in_account_currency": 0,
		"party_type":                 "Employee",
		"party":                      loan_doc.employee,
		"reference_type":             "HR Loan",
		"reference_name":             loan_doc.name,
		"user_remark":                f"Loan disbursement — {loan_doc.name}",
	})

	# Credit: Bank / Cash Account
	je.append("accounts", {
		"account":                    loan_doc.payment_account,
		"credit_in_account_currency": flt(loan_doc.loan_amount, 2),
		"debit_in_account_currency":  0,
		"reference_type":             "HR Loan",
		"reference_name":             loan_doc.name,
		"user_remark":                f"Loan disbursement — {loan_doc.name}",
	})

	je.insert(ignore_permissions=True)
	je.submit()
	return je.name


def make_repayment_journal_entry(loan_name, amount, posting_date, salary_slip_name=None):
	"""
	Dr: Payment Account (bank / cash — money coming back via salary)
	Cr: Loan Account (reducing the receivable)
	Called from utils.py on each salary slip submission.
	"""
	loan = frappe.get_doc("HR Loan", loan_name)

	if not loan.loan_account or not loan.payment_account:
		return None

	remark = f"Loan repayment — {loan_name}"
	if salary_slip_name:
		remark += f" via Salary Slip {salary_slip_name}"

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company      = loan.company
	je.posting_date = posting_date
	je.user_remark  = remark
	je.cheque_no    = salary_slip_name or loan_name
	je.cheque_date  = posting_date

	# Debit: Payment Account (salary deduction received)
	je.append("accounts", {
		"account":                    loan.payment_account,
		"debit_in_account_currency":  flt(amount, 2),
		"credit_in_account_currency": 0,
		"reference_type":             "HR Loan",
		"reference_name":             loan_name,
		"user_remark":                remark,
	})

	# Credit: Loan Account (reducing outstanding)
	je.append("accounts", {
		"account":                    loan.loan_account,
		"credit_in_account_currency": flt(amount, 2),
		"debit_in_account_currency":  0,
		"party_type":                 "Employee",
		"party":                      loan.employee,
		"reference_type":             "HR Loan",
		"reference_name":             loan_name,
		"user_remark":                remark,
	})

	je.insert(ignore_permissions=True)
	je.submit()
	return je.name


def cancel_journal_entry(je_name):
	"""Cancel and delete a submitted JE if it exists."""
	if not je_name or not frappe.db.exists("Journal Entry", je_name):
		return
	try:
		je = frappe.get_doc("Journal Entry", je_name)
		if je.docstatus == 1:
			je.cancel()
	except Exception:
		pass


# ── Whitelisted API methods ───────────────────────────────────────────────────

@frappe.whitelist()
def reschedule(loan):
	doc         = frappe.get_doc("HR Loan", loan)
	paid_rows   = [r for r in doc.repayment_schedule if r.is_paid]
	unpaid_rows = [r for r in doc.repayment_schedule if not r.is_paid and flt(r.total_payment) > 0]

	if not unpaid_rows:
		frappe.throw(_("No unpaid installments left to reschedule"))

	paid_amount       = flt(sum(flt(r.total_payment) for r in paid_rows), 2)
	remaining_balance = flt(flt(doc.loan_amount) - paid_amount, 2)

	if remaining_balance <= 0:
		frappe.throw(_("No outstanding balance remaining"))

	running_balance = remaining_balance
	for row in unpaid_rows:
		row.principal_amount    = flt(row.total_payment, 2)
		row.interest_amount     = 0
		running_balance         = flt(running_balance - row.total_payment, 2)
		row.balance_loan_amount = flt(running_balance if running_balance > 0 else 0, 2)

	doc.set("repayment_schedule", [])
	for r in paid_rows:
		doc.append("repayment_schedule", {
			"payment_date": r.payment_date, "principal_amount": r.principal_amount,
			"interest_amount": r.interest_amount, "total_payment": r.total_payment,
			"balance_loan_amount": r.balance_loan_amount,
			"is_paid": r.is_paid, "paid_on": r.paid_on, "salary_slip": r.salary_slip,
		})
	for r in unpaid_rows:
		if flt(r.total_payment) > 0:
			doc.append("repayment_schedule", {
				"payment_date": r.payment_date, "principal_amount": r.principal_amount,
				"interest_amount": r.interest_amount, "total_payment": r.total_payment,
				"balance_loan_amount": r.balance_loan_amount,
			})

	doc.balance_amount = flt(remaining_balance, 2)
	doc.save()
	return doc.name


@frappe.whitelist()
def disburse(loan, disbursement_date=None):
	if not ("HR Manager" in frappe.get_roles() or "System Manager" in frappe.get_roles()):
		frappe.throw(_("Only HR Manager can disburse"), frappe.PermissionError)

	doc = frappe.get_doc("HR Loan", loan)
	if doc.status != "Sanctioned":
		frappe.throw(_("Only Sanctioned loans can be disbursed"))

	doc.disbursement_date = getdate(disbursement_date or today())
	doc.generate_repayment_schedule()
	doc.status = "Disbursed"
	doc.save()

	# Create GL Journal Entry
	je_name = make_disbursement_journal_entry(doc)
	if je_name:
		frappe.db.set_value("HR Loan", loan, "disbursement_journal_entry", je_name)
		frappe.msgprint(
			_("Loan disbursed. Journal Entry {0} created.").format(
				f'<a href="/app/journal-entry/{je_name}">{je_name}</a>'
			),
			title=_("GL Entry Created"), indicator="green"
		)

	return doc.name


@frappe.whitelist()
def cancel_loan(loan):
	if not ("HR Manager" in frappe.get_roles() or "System Manager" in frappe.get_roles()):
		frappe.throw(_("Only HR Manager can cancel"), frappe.PermissionError)

	doc = frappe.get_doc("HR Loan", loan)
	if doc.status not in ("Sanctioned", "Disbursed"):
		frappe.throw(_("Only Sanctioned or Disbursed loans can be cancelled"))

	# Cancel the disbursement JE
	if doc.disbursement_journal_entry:
		cancel_journal_entry(doc.disbursement_journal_entry)

	doc.status = "Cancelled"
	doc.save()
	return doc.status
