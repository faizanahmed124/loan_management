import math
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, cint


class HRLoanApplication(Document):
	def validate(self):
		self.validate_repayment_source()
		self.validate_loan_amount()
		self.calculate_repayment_periods()

	def validate_repayment_source(self):
		selected = [self.from_salary, self.from_bonus, self.from_gratuity].count(1)
		if selected == 0:
			frappe.throw(_("Please select a Repayment Source: From Salary, From Bonus, or From Gratuity"))
		if selected > 1:
			frappe.throw(_("Only one Repayment Source can be selected at a time"))

	def validate_loan_amount(self):
		if not self.monthly_installment_amount or flt(self.monthly_installment_amount) <= 0:
			frappe.throw(_("Monthly Installment Amount must be greater than 0"))
		if flt(self.monthly_installment_amount) > flt(self.loan_amount):
			frappe.throw(_("Monthly Installment Amount cannot be greater than Loan Amount"))
		max_amount = frappe.db.get_value("HR Loan Type", self.loan_type, "max_loan_amount")
		if max_amount and self.loan_amount > max_amount:
			frappe.throw(
				_("Loan Amount cannot exceed {0} for Loan Type {1}").format(
					frappe.bold(max_amount), frappe.bold(self.loan_type)
				)
			)

	def calculate_repayment_periods(self):
		if flt(self.loan_amount) > 0 and flt(self.monthly_installment_amount) > 0:
			self.repayment_periods = math.ceil(
				flt(self.loan_amount) / flt(self.monthly_installment_amount)
			)

	def on_trash(self):
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
		frappe.throw(_("Only HR Manager can approve or reject"), frappe.PermissionError)
	doc = frappe.get_doc("HR Loan Application", loan_application)
	if doc.status != "Open":
		frappe.throw(_("Only Open applications can be approved or rejected"))
	doc.status = status
	doc.approved_by = frappe.session.user
	doc.save()
	return doc.status


@frappe.whitelist()
def cancel_application(loan_application):
	if not ("HR Manager" in frappe.get_roles() or "System Manager" in frappe.get_roles()):
		frappe.throw(_("Only HR Manager can cancel"), frappe.PermissionError)
	doc = frappe.get_doc("HR Loan Application", loan_application)
	if doc.status == "Cancelled":
		frappe.throw(_("Already cancelled"))
	if doc.loan and frappe.db.get_value("HR Loan", doc.loan, "status") == "Disbursed":
		frappe.throw(_("Cannot cancel: Loan is already Disbursed. Cancel the Loan first."))
	if doc.loan and frappe.db.exists("HR Loan", doc.loan):
		frappe.db.set_value("HR Loan", doc.loan, "status", "Cancelled")
	doc.status = "Cancelled"
	doc.save()
	return doc.status


@frappe.whitelist()
def create_loan(loan_application):
	app = frappe.get_doc("HR Loan Application", loan_application)
	if app.status != "Approved":
		frappe.throw(_("Loan can only be created from an Approved application"))
	if app.loan:
		frappe.throw(_("Loan {0} already created").format(app.loan))
	loan = frappe.new_doc("HR Loan")
	loan.employee                  = app.employee
	loan.loan_application          = app.name
	loan.company                   = app.company
	loan.loan_type                 = app.loan_type
	loan.loan_amount               = app.loan_amount
	loan.monthly_installment_amount = app.monthly_installment_amount
	loan.repayment_periods         = app.repayment_periods
	loan.rate_of_interest          = app.rate_of_interest
	loan.loan_source               = app.get_loan_source()
	loan.status                    = "Sanctioned"
	loan.insert()
	app.loan = loan.name
	app.save()
	return loan.name
