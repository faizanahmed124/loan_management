# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, today
from dateutil.relativedelta import relativedelta


class HRBonusCalculation(Document):
	def validate(self):
		self.total_employees   = len(self.employees)
		self.total_bonus_amount = flt(sum(flt(d.bonus_amount) for d in self.employees), 2)


@frappe.whitelist()
def fetch_employees(bonus_calculation):
	"""Pull all Active employees of the selected Department into the child table."""
	doc = frappe.get_doc("HR Bonus Calculation", bonus_calculation)

	if not doc.department:
		frappe.throw(_("Please select a Department first"))

	employees = frappe.get_all(
		"Employee",
		filters={"department": doc.department, "status": "Active"},
		fields=["name as employee", "employee_name", "date_of_joining"],
	)

	if not employees:
		frappe.msgprint(_("No active employees found in this Department"))

	doc.set("employees", [])
	for emp in employees:
		doc.append("employees", {
			"employee":        emp.employee,
			"employee_name":   emp.employee_name,
			"date_of_joining": emp.date_of_joining,
			"basic_salary":    get_basic_salary(emp.employee),
		})

	doc.save()
	return doc.name


@frappe.whitelist()
def calculate_bonus(bonus_calculation):
	"""Calculate service duration (in whole months) and bonus amount for every row."""
	doc = frappe.get_doc("HR Bonus Calculation", bonus_calculation)

	if not doc.as_on_date:
		frappe.throw(_("Please set 'Calculate As On Date'"))

	if not doc.employees:
		frappe.throw(_("No employees in the table. Click 'Get Employees' first."))

	as_on       = getdate(doc.as_on_date)
	min_months  = cint(doc.minimum_months_required) or 3
	full_months = cint(doc.full_bonus_months) or 12
	pct         = flt(doc.bonus_percentage) or 85

	for row in doc.employees:
		if not row.date_of_joining:
			row.duration_months = 0
			row.eligible        = 0
			row.bonus_amount    = 0
			continue

		months = get_month_diff(getdate(row.date_of_joining), as_on)
		row.duration_months = months

		if months < min_months:
			row.eligible     = 0
			row.bonus_amount = 0
		else:
			row.eligible      = 1
			capped            = min(months, full_months)
			row.bonus_amount  = flt(flt(row.basic_salary) * pct / 100 * (capped / full_months), 2)

	doc.total_employees    = len(doc.employees)
	doc.total_bonus_amount = flt(sum(flt(r.bonus_amount or 0) for r in doc.employees), 2)
	doc.save()
	return doc.name


@frappe.whitelist()
def recalculate_now(bonus_calculation):
	"""
	Manual trigger: same as daily auto-recalc but sets as_on_date = today.
	Called from the 'Recalculate Now' button on the form.
	"""
	doc = frappe.get_doc("HR Bonus Calculation", bonus_calculation)
	if doc.docstatus != 0:
		frappe.throw(_("Only Draft documents can be recalculated"))

	# Update date to today, then run calculate_bonus
	doc.as_on_date = today()
	doc.save()

	return calculate_bonus(bonus_calculation)


def get_month_diff(start_date, end_date):
	"""Whole number of completed months between two dates."""
	if end_date < start_date:
		return 0
	delta = relativedelta(end_date, start_date)
	return delta.years * 12 + delta.months


def get_basic_salary(employee):
	"""Fetch base from the employee's latest submitted Salary Structure Assignment."""
	assignment = frappe.get_all(
		"Salary Structure Assignment",
		filters={"employee": employee, "docstatus": 1},
		fields=["base"],
		order_by="from_date desc",
		limit=1,
	)
	return flt(assignment[0].base) if assignment else 0
