# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class HRLoanApplication(Document):
	def validate(self):
		self.validate_loan_amount()

	def validate_loan_amount(self):
		max_amount = frappe.db.get_value("HR Loan Type", self.loan_type, "max_loan_amount")
		if max_amount and self.loan_amount > max_amount:
			frappe.throw(
				_("Loan Amount cannot exceed the Maximum Loan Amount of {0} set for Loan Type {1}").format(
					frappe.bold(max_amount), frappe.bold(self.loan_type)
				)
			)

		if self.repayment_periods and self.repayment_periods <= 0:
			frappe.throw(_("Repayment Periods must be greater than 0"))


@frappe.whitelist()
def approve_or_reject(loan_application, status):
	"""Approve or reject an HR Loan Application. Restricted to HR Manager / System Manager."""
	if status not in ("Approved", "Rejected"):
		frappe.throw(_("Status must be Approved or Rejected"))

	if not ("HR Manager" in frappe.get_roles() or "System Manager" in frappe.get_roles()):
		frappe.throw(_("Only HR Manager can approve or reject Loan Applications"), frappe.PermissionError)

	doc = frappe.get_doc("HR Loan Application", loan_application)
	if doc.status != "Open":
		frappe.throw(_("Only Open applications can be approved or rejected"))

	doc.status = status
	doc.approved_by = frappe.session.user
	doc.save()
	return doc.status


@frappe.whitelist()
def create_loan(loan_application):
	"""Create an HR Loan record from an Approved HR Loan Application."""
	app = frappe.get_doc("HR Loan Application", loan_application)

	if app.status != "Approved":
		frappe.throw(_("Loan can only be created from an Approved Loan Application"))

	if app.loan:
		frappe.throw(_("Loan {0} has already been created for this application").format(app.loan))

	loan = frappe.new_doc("HR Loan")
	loan.employee = app.employee
	loan.loan_application = app.name
	loan.company = app.company
	loan.loan_type = app.loan_type
	loan.loan_amount = app.loan_amount
	loan.rate_of_interest = app.rate_of_interest
	loan.repayment_periods = app.repayment_periods
	loan.status = "Sanctioned"
	loan.insert()

	app.loan = loan.name
	app.save()

	return loan.name
