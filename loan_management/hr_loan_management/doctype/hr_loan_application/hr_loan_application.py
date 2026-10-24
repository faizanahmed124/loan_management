# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import math
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, cint

# Loan sources that are settled in one single payment (no monthly schedule)
LUMP_SUM_SOURCES = ("Bonus", "Encashment")


class HRLoanApplication(Document):
	def validate(self):
		self.validate_repayment_source()
		self.validate_loan_amount()
		self.calculate_repayment_periods()

	def validate_repayment_source(self):
		"""Exactly one source must be selected."""
		selected = [
			cint(self.from_salary),
			cint(self.from_bonus),
			cint(self.from_gratuity),
			cint(self.get("from_encashment") or 0),
		].count(1)
		if selected == 0:
			frappe.throw(
				_("Please select a Repayment Source: From Salary, From Bonus, From Gratuity, or From Leave Encashment")
			)
		if selected > 1:
			frappe.throw(_("Only one Repayment Source can be selected at a time"))

	def validate_loan_amount(self):
		"""Validate loan amount against Loan Type limit, Gratuity balance, and Encashment balance."""
		if not flt(self.monthly_installment_amount) > 0:
			# For Bonus / Encashment, installment = full amount (auto-set); for others, user enters it
			source = self.get_loan_source()
			if source not in LUMP_SUM_SOURCES:
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

		# ── Gratuity validation ───────────────────────────────────────────────
		if self.from_gratuity:
			emp = frappe.db.get_value(
				"Employee", self.employee,
				["custom_gratuity_allow", "custom_total_gratuity", "custom_consumed_gratuity_amount"],
				as_dict=True,
			)
			if not emp:
				frappe.throw(_("Employee not found"))

			if not emp.custom_gratuity_allow:
				frappe.throw(
					_("Employee {0} is not allowed to take a Gratuity loan. "
					  "Enable 'Gratuity Allow' on the Employee record.").format(
						frappe.bold(self.employee)
					)
				)

			total     = flt(emp.custom_total_gratuity or 0)
			consumed  = flt(emp.custom_consumed_gratuity_amount or 0)
			available = flt(total - consumed, 2)

			if flt(self.loan_amount) > available:
				frappe.throw(
					_("Loan Amount {0} exceeds Available Gratuity Balance {1} "
					  "(Total: {2} — Consumed: {3})").format(
						frappe.bold(self.loan_amount),
						frappe.bold(available),
						frappe.bold(total),
						frappe.bold(consumed),
					)
				)

		# ── Leave Encashment validation ────────────────────────────────────────
		if self.get("from_encashment"):
			emp = frappe.db.get_value(
				"Employee", self.employee,
				["custom_advance_amount", "custom_remaining_amount"],
				as_dict=True,
			)
			if not emp:
				frappe.throw(_("Employee not found"))

			remaining = flt(emp.custom_remaining_amount or 0)
			if flt(self.loan_amount) > remaining:
				frappe.throw(
					_("Loan Amount {0} exceeds Available Leave Encashment Balance {1}").format(
						frappe.bold(self.loan_amount),
						frappe.bold(remaining),
					)
				)

	def calculate_repayment_periods(self):
		"""
		Bonus and Encashment loans are settled in one lump sum → repayment_periods = 1.
		Salary / Gratuity loans use monthly EMI as entered.
		"""
		source = self.get_loan_source()

		if source in LUMP_SUM_SOURCES:
			# Single-payment: entire amount is due at once
			self.repayment_periods          = 1
			self.monthly_installment_amount = flt(self.loan_amount, 2)
		elif flt(self.loan_amount) > 0 and flt(self.monthly_installment_amount) > 0:
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
		if self.get("from_encashment"):
			return "Encashment"
		return "Salary"


# ── Gratuity consumed-amount helper ──────────────────────────────────────────

def _update_consumed_gratuity(employee, amount):
	"""
	amount > 0 : increase consumed (on loan creation)
	amount < 0 : decrease consumed (on cancellation)
	"""
	if not employee or not amount:
		return
	try:
		current = flt(
			frappe.db.get_value("Employee", employee, "custom_consumed_gratuity_amount") or 0
		)
		new_val = flt(max(current + amount, 0), 2)
		frappe.db.set_value("Employee", employee, "custom_consumed_gratuity_amount", new_val)
		frappe.db.commit()
		frappe.msgprint(
			_("Consumed Gratuity updated to {0}").format(frappe.bold(new_val)),
			alert=True, indicator="blue",
		)
	except Exception as e:
		frappe.log_error(f"Gratuity update failed for {employee}: {e}", "Gratuity Update")


# ── Leave Encashment advance-amount helper ────────────────────────────────────

def _update_encashment_advance(employee, amount):
	"""
	amount > 0 : increase advance taken (on loan creation / disburse)
	amount < 0 : decrease advance (on cancellation)
	Recalculates custom_remaining_amount as encashment_amount − advance.
	"""
	if not employee or not amount:
		return
	try:
		emp_fields = frappe.db.get_value(
			"Employee", employee,
			["custom_advance_amount", "custom_encashment_amount"],
			as_dict=True,
		)
		if not emp_fields:
			return
		new_advance  = flt(max(flt(emp_fields.custom_advance_amount or 0) + amount, 0), 2)
		encashment   = flt(emp_fields.custom_encashment_amount or 0)
		new_remaining = flt(max(encashment - new_advance, 0), 2)

		frappe.db.set_value("Employee", employee, {
			"custom_advance_amount":   new_advance,
			"custom_remaining_amount": new_remaining,
		})
		frappe.db.commit()
		frappe.msgprint(
			_("Leave Encashment — Advance: {0} | Remaining: {1}").format(
				frappe.bold(new_advance), frappe.bold(new_remaining)
			),
			alert=True, indicator="blue",
		)
	except Exception as e:
		frappe.log_error(f"Encashment update failed for {employee}: {e}", "Encashment Update")


# ── Whitelisted API ───────────────────────────────────────────────────────────

@frappe.whitelist()
def approve_or_reject(loan_application, status):
	if status not in ("Approved", "Rejected"):
		frappe.throw(_("Status must be Approved or Rejected"))
	if not ("HR Manager" in frappe.get_roles() or "System Manager" in frappe.get_roles()):
		frappe.throw(_("Only HR Manager can approve or reject"), frappe.PermissionError)
	doc = frappe.get_doc("HR Loan Application", loan_application)
	if doc.status != "Open":
		frappe.throw(_("Only Open applications can be approved or rejected"))
	doc.status      = status
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
	# If the Loan was already cancelled, cancel_loan has reversed the balances — don't do it twice
	loan_active = bool(doc.loan) and frappe.db.get_value("HR Loan", doc.loan, "status") not in (None, "Cancelled")
	if loan_active:
		frappe.db.set_value("HR Loan", doc.loan, "status", "Cancelled")

	# ── Reverse gratuity consumed on cancellation ─────────────────────────────
	if doc.from_gratuity and loan_active:
		_update_consumed_gratuity(doc.employee, -flt(doc.loan_amount))
		if cint(doc.get("also_deduct_from_bonus_encashment")):
			installment = flt(doc.get("monthly_installment_amount") or doc.loan_amount)
			_update_encashment_advance(doc.employee, -installment)

	# ── Reverse encashment advance on cancellation ────────────────────────────
	if doc.get("from_encashment") and loan_active:
		_update_encashment_advance(doc.employee, -flt(doc.loan_amount))

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

	loan_source = app.get_loan_source()

	loan = frappe.new_doc("HR Loan")
	loan.employee                         = app.employee
	loan.loan_application                 = app.name
	loan.company                          = app.company
	loan.loan_type                        = app.loan_type
	loan.loan_amount                      = flt(app.loan_amount)
	loan.monthly_installment_amount       = flt(app.monthly_installment_amount)
	loan.repayment_periods                = cint(app.repayment_periods)
	loan.rate_of_interest                 = app.rate_of_interest
	loan.loan_source                      = loan_source
	loan.also_deduct_from_bonus_encashment = cint(app.get("also_deduct_from_bonus_encashment") or 0)
	loan.status                           = "Sanctioned"
	loan.insert()

	app.loan = loan.name
	app.save()

	# ── Gratuity: update consumed amount immediately ──────────────────────────
	if app.from_gratuity:
		_update_consumed_gratuity(app.employee, flt(app.loan_amount))

		# Extra deductions from Bonus + Encashment if user opted in
		if cint(app.get("also_deduct_from_bonus_encashment")):
			inst = flt(app.monthly_installment_amount)
			# Deduct one installment from encashment immediately
			_update_encashment_advance(app.employee, inst)
			# Note: Bonus deduction is stored on the loan (also_deduct_from_bonus_encashment flag)
			# and will be processed when HR Bonus Calculation is finalized.
			frappe.msgprint(
				_("One installment ({0}) deducted from Leave Encashment. "
				  "Bonus deduction will be applied when Bonus is processed.").format(
					frappe.bold(inst)
				),
				title=_("Extra Deductions Applied"),
				indicator="blue",
			)

	# ── Encashment: update advance amount ────────────────────────────────────
	if app.get("from_encashment"):
		_update_encashment_advance(app.employee, flt(app.loan_amount))

	return loan.name
