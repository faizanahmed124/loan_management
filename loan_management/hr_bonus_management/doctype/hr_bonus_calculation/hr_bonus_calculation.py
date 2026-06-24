# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate
from dateutil.relativedelta import relativedelta


class HRBonusCalculation(Document):
	def validate(self):
		self.total_employees = len(self.employees)
		self.total_bonus_amount = flt(sum(flt(d.net_bonus) for d in self.employees), 2)


@frappe.whitelist()
def fetch_employees(bonus_calculation):
	"""Pull all Active employees of the selected Department into the child table."""
	doc = frappe.get_doc("HR Bonus Calculation", bonus_calculation)

	if not doc.department:
		frappe.throw(_("Please select a Department first"))

	employees = frappe.get_all(
		"Employee",
		filters={"department": doc.department, "status": "Active"},
		fields=["name as employee", "employee_name", "date_of_joining", "ctc"],
	)

	if not employees:
		frappe.msgprint(_("No active employees found in this Department"))

	doc.set("employees", [])
	for emp in employees:
		doc.append("employees", {
			"employee": emp.employee,
			"employee_name": emp.employee_name,
			"date_of_joining": emp.date_of_joining,
			"basic_salary": get_ctc_amount(emp.employee, emp.ctc),
		})

	doc.save()
	return doc.name


@frappe.whitelist()
def calculate_bonus(bonus_calculation):
	"""Calculate bonus for every row and deduct any active 'From Bonus' loans."""
	doc = frappe.get_doc("HR Bonus Calculation", bonus_calculation)

	if not doc.as_on_date:
		frappe.throw(_("Please set 'Calculate As On Date'"))

	if not doc.employees:
		frappe.throw(_("No employees in the table. Click 'Get Employees' first."))

	as_on = getdate(doc.as_on_date)
	min_months = cint(doc.minimum_months_required) or 3
	full_months = cint(doc.full_bonus_months) or 12
	pct = flt(doc.bonus_percentage) or 85

	for row in doc.employees:
		if not row.date_of_joining:
			row.duration_months = 0
			row.eligible = 0
			row.bonus_amount = 0
			row.loan_deduction = 0
			row.net_bonus = 0
			continue

		actual_months = get_month_diff(getdate(row.date_of_joining), as_on)
		capped_months = min(actual_months, full_months)
		row.duration_months = capped_months

		if actual_months < min_months:
			row.eligible = 0
			row.bonus_amount = 0
			row.loan_deduction = 0
			row.net_bonus = 0
		else:
			row.eligible = 1
			row.bonus_amount = flt(
				flt(row.basic_salary) * pct / 100 * (capped_months / full_months), 2
			)

			# Deduct any active "From Bonus" loans for this employee
			row.loan_deduction = flt(get_bonus_loan_balance(row.employee), 2)
			row.net_bonus = flt(max(row.bonus_amount - row.loan_deduction, 0), 2)

			# If loan is fully covered, mark it closed
			if row.loan_deduction > 0:
				settle_bonus_loans(row.employee, row.loan_deduction)

	doc.save()
	return doc.name


def get_bonus_loan_balance(employee):
	"""Sum the outstanding balance of all active 'From Bonus' loans for this employee."""
	loans = frappe.get_all(
		"HR Loan",
		filters={"employee": employee, "status": "Disbursed", "loan_source": "Bonus"},
		fields=["name", "balance_amount"],
	)
	return sum(flt(l.balance_amount) for l in loans)


def settle_bonus_loans(employee, bonus_amount_available):
	"""Mark Bonus-source loans as Closed when the bonus covers the outstanding balance."""
	loans = frappe.get_all(
		"HR Loan",
		filters={"employee": employee, "status": "Disbursed", "loan_source": "Bonus"},
		fields=["name", "balance_amount"],
		order_by="creation asc",
	)

	remaining = flt(bonus_amount_available)
	for loan_ref in loans:
		if remaining <= 0:
			break
		loan = frappe.get_doc("HR Loan", loan_ref.name)
		balance = flt(loan.balance_amount)

		if remaining >= balance:
			loan.total_amount_paid = flt(loan.total_amount_paid) + balance
			loan.balance_amount = 0
			loan.status = "Closed"
			remaining -= balance
		else:
			loan.total_amount_paid = flt(loan.total_amount_paid) + remaining
			loan.balance_amount = flt(balance - remaining)
			remaining = 0

		loan.save(ignore_permissions=True)


def get_month_diff(start_date, end_date):
	"""Whole completed months between two dates."""
	if end_date < start_date:
		return 0
	delta = relativedelta(end_date, start_date)
	return delta.years * 12 + delta.months


def get_ctc_amount(employee, ctc=None):
	"""Prefer Employee.ctc; fall back to latest Salary Structure Assignment base."""
	if ctc:
		return flt(ctc)
	assignment = frappe.get_all(
		"Salary Structure Assignment",
		filters={"employee": employee, "docstatus": 1},
		fields=["base"],
		order_by="from_date desc",
		limit=1,
	)
	return flt(assignment[0].base) if assignment else 0
