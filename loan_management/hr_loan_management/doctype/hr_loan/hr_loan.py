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

	def calculate_repayment_summary(self):
		"""Calculate EMI (reducing balance method) and totals."""
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
		self.total_payable_amount = flt(emi * n, 2)
		self.total_interest_payable = flt(self.total_payable_amount - principal, 2)

	def generate_repayment_schedule(self):
		"""Build the month-by-month amortization schedule starting the month after disbursement."""
		self.set("repayment_schedule", [])

		monthly_rate = flt(self.rate_of_interest) / 100 / 12
		balance = flt(self.loan_amount)
		n = cint(self.repayment_periods)
		emi = flt(self.monthly_repayment_amount)

		for i in range(1, n + 1):
			interest_amount = flt(balance * monthly_rate, 2)
			principal_amount = flt(emi - interest_amount, 2)

			if i == n:
				# Last installment absorbs any rounding difference so balance lands exactly on 0
				principal_amount = balance

			total_payment = flt(principal_amount + interest_amount, 2)
			balance = flt(balance - principal_amount, 2)
			payment_date = add_months(self.disbursement_date, i)

			self.append(
				"repayment_schedule",
				{
					"payment_date": payment_date,
					"principal_amount": principal_amount,
					"interest_amount": interest_amount,
					"total_payment": total_payment,
					"balance_loan_amount": balance,
				},
			)


@frappe.whitelist()
def disburse(loan, disbursement_date=None):
	"""Disburse a Sanctioned loan: lock in the disbursement date and build the repayment schedule."""
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
	"""Cancel a loan that has not yet been disbursed."""
	if not ("HR Manager" in frappe.get_roles() or "System Manager" in frappe.get_roles()):
		frappe.throw(_("Only HR Manager can cancel a loan"), frappe.PermissionError)

	doc = frappe.get_doc("HR Loan", loan)
	if doc.status != "Sanctioned":
		frappe.throw(_("Only Sanctioned (not yet disbursed) loans can be cancelled"))

	doc.status = "Cancelled"
	doc.save()
	return doc.status
