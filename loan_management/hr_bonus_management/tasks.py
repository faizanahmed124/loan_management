# Copyright (c) 2026, Your Company and contributors
#
# Daily scheduled task — auto-recalculate HR Bonus Calculation documents.
# Add to hooks.py:
#   scheduler_events = {
#       "daily": ["loan_management.hr_bonus_management.tasks.recalculate_bonus_daily"]
#   }

import frappe
from frappe.utils import flt, getdate, today
from dateutil.relativedelta import relativedelta


def recalculate_bonus_daily():
	"""
	Run every night.
	Updates the as_on_date and recalculates bonus for all Draft
	(docstatus = 0) HR Bonus Calculation documents.
	"""
	bonus_docs = frappe.get_all(
		"HR Bonus Calculation",
		filters={"docstatus": 0},
		pluck="name",
	)

	if not bonus_docs:
		return

	recalculated = 0
	for doc_name in bonus_docs:
		try:
			_recalculate_single(doc_name)
			recalculated += 1
		except Exception as e:
			frappe.log_error(
				f"Daily bonus recalc failed for {doc_name}: {e}",
				"Bonus Daily Recalc",
			)

	if recalculated:
		frappe.logger("bonus_recalc").info(
			f"Daily bonus recalculation complete — {recalculated} document(s) updated"
		)


def _recalculate_single(doc_name):
	doc = frappe.get_doc("HR Bonus Calculation", doc_name)

	# Move as_on_date to today so service months are always current
	doc.as_on_date = today()

	as_on      = getdate(today())
	min_months = int(doc.minimum_months_required or 3)
	full_months = int(doc.full_bonus_months or 12)
	pct        = flt(doc.bonus_percentage or 85)

	for row in doc.employees:
		if not row.date_of_joining:
			row.duration_months = 0
			row.eligible        = 0
			row.bonus_amount    = 0
			continue

		# Refresh basic salary from latest Salary Structure Assignment
		row.basic_salary = _get_basic_salary(row.employee)

		months = _month_diff(getdate(row.date_of_joining), as_on)
		row.duration_months = months

		if months < min_months:
			row.eligible     = 0
			row.bonus_amount = 0
		else:
			row.eligible      = 1
			capped            = min(months, full_months)
			row.bonus_amount  = flt(flt(row.basic_salary) * pct / 100 * (capped / full_months), 2)

	doc.total_employees   = len(doc.employees)
	doc.total_bonus_amount = flt(sum(flt(r.bonus_amount or 0) for r in doc.employees), 2)
	doc.save(ignore_permissions=True)


# ── Helpers (mirror of hr_bonus_calculation.py helpers) ───────────────────────

def _month_diff(start_date, end_date):
	"""Whole completed months between two dates."""
	if end_date < start_date:
		return 0
	delta = relativedelta(end_date, start_date)
	return delta.years * 12 + delta.months


def _get_basic_salary(employee):
	"""Latest submitted Salary Structure Assignment base."""
	result = frappe.get_all(
		"Salary Structure Assignment",
		filters={"employee": employee, "docstatus": 1},
		fields=["base"],
		order_by="from_date desc",
		limit=1,
	)
	return flt(result[0].base) if result else 0
