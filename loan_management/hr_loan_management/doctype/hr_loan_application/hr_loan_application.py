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
		"""Exactly one source must be selected."""
		selected = [self.from_salary, self.from_bonus, self.from_gratuity].count(1)
		if selected == 0:
			frappe.throw(_("Please select a Repayment Source: From Salary, From Bonus, or From Gratuity"))
		if selected > 1:
			frappe.throw(_("Only one Repayment Source can be selected at a time"))

	def validate_loan_amount(self):
		"""Validate loan amount against Loan Type limit and Gratuity balance."""
		if not self.monthly_installment_amount or flt(self.monthly_installment_amount) <= 0:
			frappe.throw(_("Monthly Installment Amount must be greater than 0"))

		if flt(self.monthly_installment_amount) > flt(self.loan_amount):
			frappe.throw(_("Monthly Installment Amount cannot be greater than Loan Amount"))

		max_amount = frappe.db.get_value("HR Loan Type", self.loan_type, "max_loan_amount")
		if max_amount and flt(self.loan_amount) > flt(max_amount):
			frappe.throw(
				_("Loan Amount cannot exceed {0} for Loan Type {1}").format(
					frappe.bold(max_amount), frappe.bold(self.loan_type)
				)
			)

		# Gratuity loan validation
		if self.from_gratuity:
			emp = frappe.db.get_value(
				"Employee", self.employee,
				["custom_gratuity_allow", "custom_total_gratuity", "custom_consumed_gratuity_amount"],
				as_dict=True
			)
			if not emp:
				frappe.throw(_("Employee not found"))

			# Check gratuity allowed on employee
			if not emp.custom_gratuity_allow:
				frappe.throw(
					_("Employee {0} is not allowed to take a Gratuity loan. "
					  "Enable 'Gratuity Allow' on the Employee record.").format(
						frappe.bold(self.employee)
					)
				)

			# Check available gratuity balance
			total     = flt(emp.custom_total_gratuity or 0)
			consumed  = flt(emp.custom_consumed_gratuity_amount or 0)
			available = flt(total - consumed, 2)

			if flt(self.loan_amount) > available:
				frappe.throw(
					_("Loan Amount {0} exceeds Available Gratuity Balance {1} "
					  "(Total Gratuity: {2} — Consumed: {3})").format(
						frappe.bold(self.loan_amount),
						frappe.bold(available),
						frappe.bold(total),
						frappe.bold(consumed),
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


def _update_consumed_gratuity(employee, amount):
	"""
	Add/subtract from custom_consumed_gratuity_amount on Employee.
	amount > 0 : add (on loan creation)
	amount < 0 : reverse (on cancellation)
	"""
	if not employee or not amount:
		return
	try:
		current = flt(
			frappe.db.get_value("Employee", employee, "custom_consumed_gratuity_amount") or 0
		)
		new_val = flt(current + amount, 2)
		if new_val < 0:
			new_val = 0
		frappe.db.set_value("Employee", employee, "custom_consumed_gratuity_amount", new_val)
		frappe.db.commit()
		frappe.msgprint(
			_("Consumed Gratuity updated to {0}").format(frappe.bold(new_val)),
			alert=True, indicator="blue"
		)
	except Exception as e:
		frappe.log_error(
			f"Gratuity update failed for {employee}: {e}",
			"Gratuity Update"
		)


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

	# Reverse gratuity consumed amount if loan was created from gratuity
	if doc.from_gratuity and doc.loan:
		_update_consumed_gratuity(doc.employee, -flt(doc.loan_amount))

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
	loan.employee                   = app.employee
	loan.loan_application           = app.name
	loan.company                    = app.company
	loan.loan_type                  = app.loan_type
	loan.loan_amount                = app.loan_amount
	loan.monthly_installment_amount = app.monthly_installment_amount
	loan.repayment_periods          = app.repayment_periods
	loan.rate_of_interest           = app.rate_of_interest
	loan.loan_source                = app.get_loan_source()
	loan.status                     = "Sanctioned"
	loan.insert()

	app.loan = loan.name
	app.save()

	# ── Gratuity: update consumed amount immediately on loan creation ─────────
	if app.from_gratuity:
		_update_consumed_gratuity(app.employee, flt(app.loan_amount))

	return loan.name