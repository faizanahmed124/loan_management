# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

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

	def calculate_repayment_summary(self):
		n = cint(self.repayment_periods)
		principal = flt(self.loan_amount)
		if not n or not principal:
			return
		monthly_rate = flt(self.rate_of_interest) / 100 / 12
		if monthly_rate:
			emi = (principal * monthly_rate * (1 + monthly_rate) ** n) / (((1 + monthly_rate) ** n) - 1)
		else:
			emi = principal / n
		emi = flt(emi, 2)
		self.monthly_repayment_amount = emi
		self.total_payable_amount     = flt(emi * n, 2)
		self.total_interest_payable   = flt(self.total_payable_amount - principal, 2)

	def generate_repayment_schedule(self):
		self.set("repayment_schedule", [])
		monthly_rate = flt(self.rate_of_interest) / 100 / 12
		balance      = flt(self.loan_amount)
		n            = cint(self.repayment_periods)
		emi          = flt(self.monthly_repayment_amount)
		for i in range(1, n + 1):
			interest_amount  = flt(balance * monthly_rate, 2)
			principal_amount = flt(emi - interest_amount, 2)
			if i == n:
				principal_amount = balance
			total_payment = flt(principal_amount + interest_amount, 2)
			balance       = flt(balance - principal_amount, 2)
			self.append("repayment_schedule", {
				"payment_date":       add_months(self.disbursement_date, i),
				"principal_amount":   principal_amount,
				"interest_amount":    interest_amount,
				"total_payment":      total_payment,
				"balance_loan_amount": balance,
			})


@frappe.whitelist()
def reschedule(loan):
	"""
	Smart reschedule:
	1. Keep all paid rows untouched.
	2. Look at unpaid rows as entered by the user.
	3. Remove rows where total_payment is 0 (redundant after manual edit).
	4. Recalculate running balance across remaining unpaid rows.
	5. If unpaid rows already sum to outstanding balance — close cleanly.
	"""
	doc = frappe.get_doc("HR Loan", loan)

	paid_rows   = [r for r in doc.repayment_schedule if r.is_paid]
	unpaid_rows = [r for r in doc.repayment_schedule if not r.is_paid]

	if not unpaid_rows:
		frappe.throw(_("No unpaid installments left to reschedule"))

	# Remove rows with 0 or no amount (user deleted the content)
	unpaid_rows = [r for r in unpaid_rows if flt(r.total_payment) > 0]

	paid_amount       = flt(sum(flt(r.total_payment) for r in paid_rows), 2)
	remaining_balance = flt(flt(doc.loan_amount) - paid_amount, 2)

	if remaining_balance <= 0:
		frappe.throw(_("No outstanding balance remaining"))

	# Cap sum of unpaid rows at remaining balance
	unpaid_sum = flt(sum(flt(r.total_payment) for r in unpaid_rows), 2)

	if unpaid_sum > remaining_balance:
		# Trim excess from the last row
		excess = flt(unpaid_sum - remaining_balance, 2)
		unpaid_rows[-1].total_payment = flt(flt(unpaid_rows[-1].total_payment) - excess, 2)
		if unpaid_rows[-1].total_payment <= 0:
			unpaid_rows = unpaid_rows[:-1]

	# Recalculate running balance
	running_balance = remaining_balance
	for i, row in enumerate(unpaid_rows):
		row.principal_amount    = flt(row.total_payment, 2)
		row.interest_amount     = 0
		running_balance         = flt(running_balance - row.total_payment, 2)
		row.balance_loan_amount = flt(running_balance if running_balance > 0 else 0, 2)

	# If unpaid rows don't cover full balance, add a final catch-all row
	if running_balance > 0.01 and unpaid_rows:
		last_date = getdate(unpaid_rows[-1].payment_date)
		next_date = add_months(last_date, 1)
		unpaid_rows_list = list(unpaid_rows)
		# Append new row to document
		new_row = doc.append("repayment_schedule", {
			"payment_date":       next_date,
			"principal_amount":   running_balance,
			"interest_amount":    0,
			"total_payment":      running_balance,
			"balance_loan_amount": 0,
		})
		running_balance = 0

	# Rebuild schedule: paid rows first, then cleaned unpaid rows
	doc.set("repayment_schedule", [])
	for r in paid_rows:
		doc.append("repayment_schedule", {
			"payment_date":       r.payment_date,
			"principal_amount":   r.principal_amount,
			"interest_amount":    r.interest_amount,
			"total_payment":      r.total_payment,
			"balance_loan_amount": r.balance_loan_amount,
			"is_paid":            r.is_paid,
			"paid_on":            r.paid_on,
			"salary_slip":        r.salary_slip,
		})
	for r in unpaid_rows:
		if flt(r.total_payment) > 0:
			doc.append("repayment_schedule", {
				"payment_date":       r.payment_date,
				"principal_amount":   r.principal_amount,
				"interest_amount":    r.interest_amount,
				"total_payment":      r.total_payment,
				"balance_loan_amount": r.balance_loan_amount,
			})

	# Update summary
	unpaid_total = flt(sum(flt(r.total_payment) for r in unpaid_rows if flt(r.total_payment) > 0), 2)
	doc.balance_amount           = flt(remaining_balance, 2)
	doc.total_interest_payable   = 0
	doc.monthly_repayment_amount = flt(unpaid_rows[0].total_payment, 2) if unpaid_rows else 0

	doc.save()
	return doc.name


@frappe.whitelist()
def disburse(loan, disbursement_date=None):
	if not ("HR Manager" in frappe.get_roles() or "System Manager" in frappe.get_roles()):
		frappe.throw(_("Only HR Manager can disburse a loan"), frappe.PermissionError)
	doc = frappe.get_doc("HR Loan", loan)
	if doc.status != "Sanctioned":
		frappe.throw(_("Only Sanctioned loans can be disbursed"))
	doc.disbursement_date = getdate(disbursement_date or today())
	doc.generate_repayment_schedule()
	doc.status = "Disbursed"
	doc.save()
	return doc.name


@frappe.whitelist()
def cancel_loan(loan):
	if not ("HR Manager" in frappe.get_roles() or "System Manager" in frappe.get_roles()):
		frappe.throw(_("Only HR Manager can cancel a loan"), frappe.PermissionError)
	doc = frappe.get_doc("HR Loan", loan)
	if doc.status not in ("Sanctioned", "Disbursed"):
		frappe.throw(_("Only Sanctioned or Disbursed loans can be cancelled"))
	doc.status = "Cancelled"
	doc.save()
	return doc.status
