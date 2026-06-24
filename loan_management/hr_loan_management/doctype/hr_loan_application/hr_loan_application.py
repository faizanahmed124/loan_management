# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class HRLoanApplication(Document):
	def validate(self):
		self.validate_repayment_source()
		self.validate_loan_amount()

	def validate_repayment_source(self):
		selected = [self.from_salary, self.from_bonus, self.from_gratuity].count(1)
		if selected == 0:
			frappe.throw(_("Please select a Repayment Source: From Salary, From Bonus, or From Gratuity"))
		if selected > 1:
			frappe.throw(_("Only one Repayment Source can be selected at a time"))

	def validate_loan_amount(self):
		max_amount = frappe.db.get_value("HR Loan Type", self.loan_type, "max_loan_amount")
		if max_amount and self.loan_amount > max_amount:
			frappe.throw(
				_("Loan Amount cannot exceed the Maximum Loan Amount of {0} for Loan Type {1}").format(
					frappe.bold(max_amount), frappe.bold(self.loan_type)
				)
			)
		if self.repayment_periods and self.repayment_periods <= 0:
			frappe.throw(_("Repayment Periods must be greater than 0"))

	def on_trash(self):
		# Clear the back-link on HR Loan before deleting this application
		if self.loan and frappe.db.exists("HR Loan", self.loan):
			frappe.db.set_value("HR Loan", self.loan, "loan_application", None)

	def get_loan_source(self):
		if self.from_bonus:
			return "Bonus"
		if self.from_gratuity:
			return "Gratuity"
		return "Salary"


@frappe.whitelist()
def approve_or_reject(loan_application, status):
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
def cancel_application(loan_application):
	"""Cancel a Loan Application (sets status to Cancelled so it can be deleted)."""
	if not ("HR Manager" in frappe.get_roles() or "System Manager" in frappe.get_roles()):
		frappe.throw(_("Only HR Manager can cancel a Loan Application"), frappe.PermissionError)
	doc = frappe.get_doc("HR Loan Application", loan_application)
	if doc.status in ("Cancelled",):
		frappe.throw(_("Application is already cancelled"))
	if doc.loan and frappe.db.get_value("HR Loan", doc.loan, "status") == "Disbursed":
		frappe.throw(_("Cannot cancel: the linked Loan is already Disbursed. Cancel the Loan first."))
	# Also cancel the linked sanctioned loan if any
	if doc.loan and frappe.db.exists("HR Loan", doc.loan):
		frappe.db.set_value("HR Loan", doc.loan, "status", "Cancelled")
	doc.status = "Cancelled"
	doc.save()
	return doc.status


@frappe.whitelist()
def create_loan(loan_application):
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
	loan.loan_source = app.get_loan_source()
	loan.status = "Sanctioned"
	loan.insert()
	app.loan = loan.name
	app.save()
	return loan.name
