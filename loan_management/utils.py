# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt
"""
Salary Slip lifecycle hooks:
- Salary / Gratuity loans  → monthly EMI auto-deducted from Salary Slip
- Bonus loans              → NOT deducted from Salary Slip (handled via HR Bonus Calculation)
"""

import frappe
from frappe.utils import flt

LOAN_DEDUCTION_COMPONENT = "Loan EMI Deduction"

# loan_source values that should trigger a salary deduction
SALARY_REPAYMENT_SOURCES = ("Salary", "Gratuity")


def add_loan_deductions(doc, method=None):
	"""Salary Slip validate hook: add EMI deduction for Salary/Gratuity loans."""
	if not doc.employee:
		return

	due_amount, due_rows = _get_due_installments(doc.employee, doc.start_date, doc.end_date)
	if not due_amount:
		return

	if not frappe.db.exists("Salary Component", LOAN_DEDUCTION_COMPONENT):
		_create_loan_salary_component()

	existing_row = next(
		(r for r in doc.deductions if r.salary_component == LOAN_DEDUCTION_COMPONENT), None
	)

	if existing_row:
		existing_row.amount = due_amount
	else:
		doc.append("deductions", {
			"salary_component": LOAN_DEDUCTION_COMPONENT,
			"amount": due_amount,
		})


def mark_loan_repayments_paid(doc, method=None):
	"""Salary Slip on_submit hook: settle matched installment rows."""
	if not doc.employee:
		return

	_, due_rows = _get_due_installments(doc.employee, doc.start_date, doc.end_date)

	for loan_name, row_name in due_rows:
		loan = frappe.get_doc("HR Loan", loan_name)
		for schedule_row in loan.repayment_schedule:
			if schedule_row.name == row_name:
				schedule_row.is_paid = 1
				schedule_row.paid_on = doc.end_date
				schedule_row.salary_slip = doc.name

		loan.total_amount_paid = flt(loan.total_amount_paid) + flt(
			next((r.total_payment for r in loan.repayment_schedule if r.name == row_name), 0)
		)

		if all(r.is_paid for r in loan.repayment_schedule):
			loan.status = "Closed"

		loan.save(ignore_permissions=True)


def unmark_loan_repayments_paid(doc, method=None):
	"""Salary Slip on_cancel hook: reverse the settlement."""
	if not doc.employee:
		return

	loans = frappe.get_all(
		"HR Loan",
		filters={
			"employee": doc.employee,
			"status": ["in", ["Disbursed", "Closed"]],
			"loan_source": ["in", list(SALARY_REPAYMENT_SOURCES)],
		},
		pluck="name",
	)

	for loan_name in loans:
		loan = frappe.get_doc("HR Loan", loan_name)
		changed = False
		for schedule_row in loan.repayment_schedule:
			if schedule_row.salary_slip == doc.name:
				loan.total_amount_paid = flt(loan.total_amount_paid) - flt(schedule_row.total_payment)
				schedule_row.is_paid = 0
				schedule_row.paid_on = None
				schedule_row.salary_slip = None
				changed = True

		if changed:
			if loan.status == "Closed":
				loan.status = "Disbursed"
			loan.save(ignore_permissions=True)


def _get_due_installments(employee, start_date, end_date):
	"""Return (total_amount, [(loan_name, row_name), ...]) for Salary/Gratuity loans only."""
	loans = frappe.get_all(
		"HR Loan",
		filters={
			"employee": employee,
			"status": "Disbursed",
			"loan_source": ["in", list(SALARY_REPAYMENT_SOURCES)],
		},
		pluck="name",
	)

	total = 0.0
	rows = []

	for loan_name in loans:
		schedule = frappe.get_all(
			"HR Loan Repayment Schedule",
			filters={
				"parent": loan_name,
				"parenttype": "HR Loan",
				"is_paid": 0,
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
	component.type = "Deduction"
	component.description = "Auto-created by HR Loan app for employee loan EMI deductions."
	component.insert(ignore_permissions=True)
