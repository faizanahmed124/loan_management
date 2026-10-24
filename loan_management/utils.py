# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt

LOAN_DEDUCTION_COMPONENT = "Loan EMI Deduction"
SALARY_REPAYMENT_SOURCES = ("Salary", "Gratuity")


def add_loan_deductions(doc, method=None):
	"""Salary Slip validate — add EMI deduction for Salary/Gratuity loans."""
	if not doc.employee:
		return
	due_amount, _ = _get_due_installments(doc.employee, doc.start_date, doc.end_date)
	if not due_amount:
		return
	if not frappe.db.exists("Salary Component", LOAN_DEDUCTION_COMPONENT):
		_create_loan_salary_component()
	existing = next((r for r in doc.deductions if r.salary_component == LOAN_DEDUCTION_COMPONENT), None)
	if existing:
		existing.amount = due_amount
	else:
		doc.append("deductions", {"salary_component": LOAN_DEDUCTION_COMPONENT, "amount": due_amount})


def mark_loan_repayments_paid(doc, method=None):
	"""Salary Slip on_submit — settle installment rows + create repayment GL entry."""
	if not doc.employee:
		return
	_, due_rows = _get_due_installments(doc.employee, doc.start_date, doc.end_date)

	for loan_name, row_name in due_rows:
		loan = frappe.get_doc("HR Loan", loan_name)

		paid_amount = 0
		for schedule_row in loan.repayment_schedule:
			if schedule_row.name == row_name:
				schedule_row.is_paid     = 1
				schedule_row.paid_on     = doc.end_date
				schedule_row.salary_slip = doc.name
				paid_amount = flt(schedule_row.total_payment)

		loan.total_amount_paid = flt(loan.total_amount_paid) + paid_amount
		if all(r.is_paid for r in loan.repayment_schedule):
			loan.status = "Closed"
		loan.save(ignore_permissions=True)

		# ── Gratuity: installment paid via salary → free that amount from consumed ──
		if paid_amount > 0 and loan.loan_source == "Gratuity":
			_reduce_consumed_gratuity(loan.employee, paid_amount)

		# Create repayment GL Journal Entry
		if paid_amount > 0:
			try:
				from loan_management.hr_loan_management.doctype.hr_loan.hr_loan import make_repayment_journal_entry
				make_repayment_journal_entry(
					loan_name        = loan_name,
					amount           = paid_amount,
					posting_date     = doc.end_date,
					salary_slip_name = doc.name,
				)
			except Exception as e:
				frappe.log_error(f"Repayment GL entry failed for {loan_name}: {e}", "HR Loan GL")


def unmark_loan_repayments_paid(doc, method=None):
	"""Salary Slip on_cancel — reverse settlement."""
	if not doc.employee:
		return
	loans = frappe.get_all(
		"HR Loan",
		filters={
			"employee":    doc.employee,
			"status":      ["in", ["Disbursed", "Closed"]],
			"loan_source": ["in", list(SALARY_REPAYMENT_SOURCES)],
		},
		pluck="name",
	)
	for loan_name in loans:
		loan    = frappe.get_doc("HR Loan", loan_name)
		changed = False
		reversed_amount = 0.0

		for schedule_row in loan.repayment_schedule:
			if schedule_row.salary_slip == doc.name:
				reversed_amount             += flt(schedule_row.total_payment)
				loan.total_amount_paid       = flt(loan.total_amount_paid) - flt(schedule_row.total_payment)
				schedule_row.is_paid         = 0
				schedule_row.paid_on         = None
				schedule_row.salary_slip     = None
				changed = True

		if changed:
			if loan.status == "Closed":
				loan.status = "Disbursed"
			loan.save(ignore_permissions=True)

			# ── Gratuity: salary slip cancelled → restore consumed gratuity ──────
			if reversed_amount > 0 and loan.loan_source == "Gratuity":
				_restore_consumed_gratuity(loan.employee, reversed_amount)

		# Cancel repayment JEs for this salary slip
		_cancel_repayment_jes(loan_name, doc.name)


# ── Gratuity helpers ──────────────────────────────────────────────────────────

def _reduce_consumed_gratuity(employee, amount):
	"""
	Salary installment paid → reduce consumed gratuity by that amount
	(the employee has repaid this portion, so it's freed from total gratuity).
	"""
	if not employee or not amount:
		return
	try:
		current  = flt(frappe.db.get_value("Employee", employee, "custom_consumed_gratuity_amount") or 0)
		new_val  = flt(current - amount, 2)
		if new_val < 0:
			new_val = 0
		frappe.db.set_value("Employee", employee, "custom_consumed_gratuity_amount", new_val)
		frappe.db.commit()
	except Exception as e:
		frappe.log_error(f"Gratuity reduce failed for {employee}: {e}", "Gratuity Update")


def _restore_consumed_gratuity(employee, amount):
	"""
	Salary slip cancelled → restore consumed gratuity
	(installment was reversed so gratuity becomes consumed again).
	"""
	if not employee or not amount:
		return
	try:
		current = flt(frappe.db.get_value("Employee", employee, "custom_consumed_gratuity_amount") or 0)
		new_val = flt(current + amount, 2)
		frappe.db.set_value("Employee", employee, "custom_consumed_gratuity_amount", new_val)
		frappe.db.commit()
	except Exception as e:
		frappe.log_error(f"Gratuity restore failed for {employee}: {e}", "Gratuity Update")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _cancel_repayment_jes(loan_name, salary_slip_name):
	"""Cancel any repayment JEs linked to a salary slip and loan."""
	jes = frappe.get_all(
		"Journal Entry",
		filters={"user_remark": ["like", f"%{loan_name}%"], "docstatus": 1},
		pluck="name",
	)
	for je_name in jes:
		try:
			je = frappe.get_doc("Journal Entry", je_name)
			if any(a.reference_name == loan_name for a in je.accounts):
				je.cancel()
		except Exception:
			pass


def _get_due_installments(employee, start_date, end_date):
	loans = frappe.get_all(
		"HR Loan",
		filters={
			"employee":    employee,
			"status":      "Disbursed",
			"loan_source": ["in", list(SALARY_REPAYMENT_SOURCES)],
		},
		pluck="name",
	)
	total = 0.0
	rows  = []
	for loan_name in loans:
		schedule = frappe.get_all(
			"HR Loan Repayment Schedule",
			filters={
				"parent":       loan_name,
				"parenttype":   "HR Loan",
				"is_paid":      0,
				"payment_date": ["between", [start_date, end_date]],
			},
			fields=["name", "total_payment"],
		)
		for row in schedule:
			total += flt(row.total_payment)
			rows.append((loan_name, row.name))
	return flt(total, 2), rows


def _create_loan_salary_component():
	component = frappe.new_doc("Salary Component")
	component.salary_component = LOAN_DEDUCTION_COMPONENT
	component.type             = "Deduction"
	component.description      = "Auto-created by HR Loan app for employee loan EMI deductions."
	component.insert(ignore_permissions=True)


def set_encashment_remaining(doc, method=None):
	"""Employee validate — keep Encashment Remaining = Leave Encashment − Advance Taken."""
	if not doc.meta.has_field("custom_remaining_amount"):
		return
	doc.custom_remaining_amount = flt(
		max(flt(doc.get("custom_encashment_amount")) - flt(doc.get("custom_advance_amount")), 0), 2
	)
