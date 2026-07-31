# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import calendar
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, money_in_words, today
from dateutil.relativedelta import relativedelta


class HRFullFinalSettlement(Document):
	def validate(self):
		self.calculate_daily_rate()
		self.calculate_current_month()
		self.calculate_leave_amount()
		self.calculate_bonus()
		self.calculate_gratuity()
		self.update_loan_totals()
		self.calculate_net_payable()

	# ── Calculations ──────────────────────────────────────────────────────────

	def calculate_daily_rate(self):
		if not self.settlement_date or not flt(self.gross_salary_calc):
			return
		d = getdate(self.settlement_date)
		days_in_month = calendar.monthrange(d.year, d.month)[1]
		self.daily_rate = flt(flt(self.gross_salary_calc) / days_in_month, 2)

	def calculate_current_month(self):
		if self.working_days and flt(self.daily_rate):
			self.current_month_salary = flt(flt(self.working_days) * flt(self.daily_rate), 2)

	def calculate_leave_amount(self):
		"""Leave Amount = Leave Days × (Gross / 30)"""
		if self.leave_encashed and flt(self.gross_salary_calc):
			self.leave_amount = flt(flt(self.leave_encashed) * flt(self.gross_salary_calc) / 30, 2)

	def calculate_bonus(self):
		"""Bonus = Basic Pay × Bonus Months"""
		if self.bonus_month and flt(self.basic_pay):
			self.bonus_amount = flt(flt(self.basic_pay) * flt(self.bonus_month), 2)

	def calculate_gratuity(self):
		"""
		Gratuity Years = Joining → Last Working Day
		Net Gratuity   = Total Gratuity (from Employee) − Consumed Gratuity
		"""
		if self.date_of_joining and self.last_working_day:
			doj = getdate(self.date_of_joining)
			lwd = getdate(self.last_working_day)
			if lwd > doj:
				delta = relativedelta(lwd, doj)
				self.gratuity_years = flt(delta.years + delta.months / 12, 2)

		total    = flt(self.employee_total_gratuity)
		consumed = flt(self.consumed_gratuity_amount)
		self.net_gratuity_payable = flt(total - consumed, 2)

	def update_loan_totals(self):
		self.total_loan_pending = flt(
			sum(flt(r.balance_amount) for r in self.loan_details), 2
		)
		# Default loan deduction to total pending if not manually overridden
		if not flt(self.loan_deduction_amount) and self.total_loan_pending:
			self.loan_deduction_amount = self.total_loan_pending

	def calculate_net_payable(self):
		net = (
			flt(self.current_month_salary)
			+ flt(self.leave_amount)
			+ flt(self.overtime_amount)
			+ flt(self.bonus_amount)
			+ flt(self.net_gratuity_payable)
			+ flt(self.notice_pay)
			+ flt(self.other_adjustment)
			- flt(self.loan_deduction_amount)
			- flt(self.advance_amount)
		)
		self.net_payable = flt(net, 2)
		if self.net_payable > 0:
			currency = (
				frappe.db.get_value("Company", self.get("company"), "default_currency")
				or "PKR"
			)
			self.net_payable_in_words = money_in_words(self.net_payable, currency)
		else:
			self.net_payable_in_words = ""


# ── Whitelisted API methods ───────────────────────────────────────────────────

@frappe.whitelist()
def fetch_employee_data(settlement, employee):
	"""
	Auto-fetch on button click:
	1. Salary: CTC → gross, custom_basic_pay → basic
	2. Loans: all Disbursed/Closed HR Loans with paid/pending
	3. Leave Balance: from Leave Ledger Entry
	4. Gratuity: custom_total_gratuity, custom_consumed_gratuity_amount
	"""
	doc = frappe.get_doc("HR Full Final Settlement", settlement)

	# ── 1. Salary + Gratuity fields from Employee ─────────────────────────────
	emp = frappe.db.get_value(
		"Employee",
		employee,
		[
			"ctc",
			"custom_basic_pay",
			"custom_total_gratuity",
			"custom_consumed_gratuity_amount",
			"date_of_joining",
		],
		as_dict=True,
	)
	if emp:
		doc.gross_salary_calc          = flt(emp.ctc)
		doc.basic_pay                  = flt(emp.custom_basic_pay)
		doc.employee_total_gratuity    = flt(emp.custom_total_gratuity)
		doc.consumed_gratuity_amount   = flt(emp.custom_consumed_gratuity_amount)
		doc.net_gratuity_payable       = flt(emp.custom_total_gratuity) - flt(
			emp.custom_consumed_gratuity_amount
		)

	# ── 2. Loans ──────────────────────────────────────────────────────────────
	loans = frappe.get_all(
		"HR Loan",
		filters={"employee": employee, "status": ["in", ["Disbursed", "Closed"]]},
		fields=[
			"name", "loan_type", "loan_amount",
			"total_amount_paid", "balance_amount",
			"disbursement_date", "status",
		],
		order_by="creation asc",
	)

	doc.set("loan_details", [])
	for loan in loans:
		doc.append("loan_details", {
			"loan":              loan.name,
			"loan_type":         loan.loan_type,
			"loan_amount":       flt(loan.loan_amount),
			"total_amount_paid": flt(loan.total_amount_paid),
			"balance_amount":    flt(loan.balance_amount),
			"disbursement_date": loan.disbursement_date,
			"status":            loan.status,
		})

	doc.total_loan_pending    = flt(sum(flt(l.balance_amount) for l in doc.loan_details), 2)
	doc.loan_deduction_amount = doc.total_loan_pending

	# ── 3. Leave Balance ──────────────────────────────────────────────────────
	doc.leave_balance = _get_leave_balance(employee, doc.last_working_day or today())

	doc.save()

	return {
		"gross_salary_calc":        doc.gross_salary_calc,
		"basic_pay":                doc.basic_pay,
		"employee_total_gratuity":  doc.employee_total_gratuity,
		"consumed_gratuity_amount": doc.consumed_gratuity_amount,
		"net_gratuity_payable":     doc.net_gratuity_payable,
		"leave_balance":            doc.leave_balance,
		"total_loan_pending":       doc.total_loan_pending,
		"loan_count":               len(doc.loan_details),
	}


def _get_leave_balance(employee, as_on_date):
	"""Total available leave balance from Leave Ledger Entry."""
	try:
		result = frappe.db.sql(
			"""
			SELECT COALESCE(SUM(leaves), 0)
			FROM `tabLeave Ledger Entry`
			WHERE employee = %s
			  AND docstatus = 1
			  AND transaction_date <= %s
			  AND (expiry_date IS NULL OR expiry_date >= %s)
			""",
			(employee, as_on_date, as_on_date),
		)
		balance = flt(result[0][0]) if result else 0
		if balance:
			return flt(balance, 2)
	except Exception:
		pass

	# Fallback: Leave Allocation
	try:
		allocs = frappe.get_all(
			"Leave Allocation",
			filters={"employee": employee, "docstatus": 1},
			fields=["total_leaves_allocated", "carry_forwarded_leaves_count"],
		)
		return flt(
			sum(
				flt(a.total_leaves_allocated) + flt(a.carry_forwarded_leaves_count)
				for a in allocs
			),
			2,
		)
	except Exception:
		return 0


@frappe.whitelist()
def verify_settlement(settlement):
	if not ("HR Manager" in frappe.get_roles() or "System Manager" in frappe.get_roles()):
		frappe.throw(_("Only HR Manager can verify"), frappe.PermissionError)
	doc = frappe.get_doc("HR Full Final Settlement", settlement)
	if doc.status != "Draft":
		frappe.throw(_("Only Draft settlements can be verified"))
	doc.status = "Verified"
	doc.save()
	return doc.status


@frappe.whitelist()
def mark_paid(settlement):
	if not ("HR Manager" in frappe.get_roles() or "System Manager" in frappe.get_roles()):
		frappe.throw(_("Only HR Manager can mark Paid"), frappe.PermissionError)
	doc = frappe.get_doc("HR Full Final Settlement", settlement)
	if doc.status == "Paid":
		frappe.throw(_("Already marked as Paid"))
	doc.status = "Paid"
	doc.save()
	return doc.status