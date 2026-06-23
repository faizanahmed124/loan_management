# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt
"""
Hooks into HRMS Salary Slip lifecycle to automatically:
1. Add the due EMI for any active employee HR Loan as a deduction row (on validate).
2. Mark the corresponding HR Loan Repayment Schedule row as paid, and close the
   HR Loan once fully repaid (on submit).
3. Reverse that marking if the Salary Slip is cancelled.
"""

import frappe
from frappe.utils import flt

LOAN_DEDUCTION_COMPONENT = "Loan EMI Deduction"


def add_loan_deductions(doc, method=None):
	"""Salary Slip validate hook: pull in any EMI due for this payroll period."""
	if not doc.employee:
		return

	due_amount, due_rows = _get_due_installments(doc.employee, doc.start_date, doc.end_date)

	if not due_amount:
		return

	if not frappe.db.exists("Salary Component", LOAN_DEDUCTION_COMPONENT):
		_create_loan_salary_component()

	existing_row = None
	for row in doc.deductions:
		if row.salary_component == LOAN_DEDUCTION_COMPONENT:
			existing_row = row
			break

	if existing_row:
		existing_row.amount = due_amount
	else:
		doc.append(
			"deductions",
			{
				"salary_component": LOAN_DEDUCTION_COMPONENT,
				"amount": due_amount,
			},
		)


def mark_loan_repayments_paid(doc, method=None):
	"""Salary Slip on_submit hook: settle the matched installment rows."""
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
	"""Salary Slip on_cancel hook: reverse the settlement if the slip is cancelled."""
	if not doc.employee:
		return

	loans = frappe.get_all(
		"HR Loan", filters={"employee": doc.employee, "status": ["in", ["Disbursed", "Closed"]]}, pluck="name"
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
	"""Find unpaid installments across the employee's active loans whose
	payment_date falls within this payroll period. Returns (total_amount, [(loan, row_name), ...])
	"""
	loans = frappe.get_all("HR Loan", filters={"employee": employee, "status": "Disbursed"}, pluck="name")

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
	component.description = "Auto-created by the HR Loan app for employee loan EMI deductions."
	component.insert(ignore_permissions=True)
