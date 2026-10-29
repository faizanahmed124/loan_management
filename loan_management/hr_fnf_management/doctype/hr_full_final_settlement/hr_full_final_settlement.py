# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import date_diff, flt, get_first_day, get_last_day, getdate, money_in_words, today
from dateutil.relativedelta import relativedelta


class HRFullFinalSettlement(Document):
	def validate(self):
		# Working days / overtime are filled automatically when the employee or the
		# last working day changes (or on a new document); afterwards they stay editable.
		if (
			self.is_new()
			or self.has_value_changed("employee")
			or self.has_value_changed("last_working_day")
			or not self.working_days
		):
			self.set_working_days()
			self.calculate_overtime()
			self.set_gratuity()
		elif self.has_value_changed("gratuity_years") and self._gratuity_allowed():
			self.calculate_gratuity_amount()
		self.enforce_overtime_eligibility()
		self.calculate_daily_rate()
		self.calculate_current_month()
		self.calculate_leave_amount()
		self.calculate_bonus()
		self.update_loan_totals()
		self.calculate_net_payable()

	def on_update(self):
		self.update_employee_status()

	# ── Resignation → Employee status ─────────────────────────────────────────

	def update_employee_status(self):
		"""Employee status becomes Left when a resignation date is entered, or once the
		settlement is Verified / Paid. Ignored if the employee is already Left (or
		otherwise not Active)."""
		if not self.employee:
			return
		if not (self.resignation_date or self.status in ("Verified", "Paid")):
			return
		status = frappe.db.get_value("Employee", self.employee, "status")
		if status != "Active":
			return

		values = {"status": "Left"}
		# Employee validation requires a relieving date for Left employees
		if not frappe.db.get_value("Employee", self.employee, "relieving_date"):
			values["relieving_date"] = self.last_working_day or self.resignation_date or today()
		frappe.db.set_value("Employee", self.employee, values)
		frappe.get_doc("Employee", self.employee).add_comment(
			"Info",
			_("Status set to Left from {0} (settlement {1})").format(self.name, self.status),
		)
		frappe.msgprint(
			_("Employee {0} status changed to Left").format(self.employee),
			indicator="orange",
			alert=True,
		)

	# ── Calculations ──────────────────────────────────────────────────────────

	def _salary_period(self):
		"""Final month: 1st of the Last Working Day's month (or joining date if later) → LWD."""
		if not self.last_working_day:
			return None, None
		lwd = getdate(self.last_working_day)
		start = get_first_day(lwd)
		if self.date_of_joining and getdate(self.date_of_joining) > start:
			start = getdate(self.date_of_joining)
		if start > lwd:
			return None, None
		return start, lwd

	@frappe.whitelist()
	def recalculate(self):
		"""Button / live-form entry point: refresh working days, overtime and all amounts."""
		self.set_working_days()
		self.calculate_overtime()
		self.set_gratuity()
		self.calculate_daily_rate()
		self.calculate_current_month()
		self.calculate_leave_amount()
		self.calculate_bonus()
		self.calculate_net_payable()

	def set_working_days(self):
		"""Every attendance day from the 1st of the Last Working Day's month (or joining)
		to the Last Working Day counts except Absent. Half Day counts 0.5."""
		start, end = self._salary_period()
		if not (self.employee and start):
			return
		self.working_days = flt(
			frappe.db.sql(
				"""
				SELECT COALESCE(SUM(CASE
					WHEN status = 'Absent' THEN 0
					WHEN status = 'Half Day' THEN 0.5
					ELSE 1 END), 0)
				FROM `tabAttendance`
				WHERE employee = %s AND attendance_date BETWEEN %s AND %s AND docstatus = 1
				""",
				(self.employee, start, end),
			)[0][0]
		)

	def calculate_daily_rate(self):
		"""Daily rate = CTC / total days of the Last Working Day's month (30/31/28/29)."""
		month_ref = self.last_working_day or self.settlement_date
		if not month_ref or not flt(self.gross_salary_calc):
			return
		days_in_month = get_last_day(getdate(month_ref)).day
		self.daily_rate = flt(flt(self.gross_salary_calc) / days_in_month, 2)

	def calculate_overtime(self):
		"""Overtime / less-duty-hours for the final month, same formula as the Salary Slip
		(overtime_in_salary.salary_slip.calculate_overtime)."""
		self.overtime_hours = 0
		self.overtime_amount = 0
		self.less_duty_hours = 0
		self.less_duty_hours_amount = 0

		start, end = self._salary_period()
		if not (self.employee and start):
			return
		emp = frappe.db.get_value(
			"Employee", self.employee, ["employment_type", "custom_allow_overtime"], as_dict=True
		)
		if not emp:
			return
		emp_type = (emp.employment_type or "").upper().strip()
		base_salary = flt(
			frappe.db.get_value(
				"Salary Structure Assignment",
				{"employee": self.employee, "docstatus": 1, "from_date": ["<=", start]},
				"base",
				order_by="from_date DESC",
			)
		)
		if not base_salary:
			return
		month_days = get_last_day(end).day

		def attendance_sum(column):
			return flt(
				frappe.db.sql(
					f"""SELECT COALESCE(SUM({column}), 0) FROM `tabAttendance`
					WHERE employee = %s AND attendance_date BETWEEN %s AND %s
					AND docstatus = 1 AND status != 'Half Day'""",
					(self.employee, start, end),
				)[0][0]
			)

		if not emp.custom_allow_overtime:
			frappe.msgprint(
				_("Overtime is not applicable for employee {0} ({1})").format(
					self.employee, self.employee_name or ""
				),
				indicator="orange",
				alert=True,
			)
		overtime = attendance_sum("custom_overtime") if emp.custom_allow_overtime else 0
		ldh = 0
		if emp_type == "PERMANENT":
			ldh = attendance_sum("custom_less_duty_hour")
			# overtime offsets less duty hours
			if overtime > ldh:
				overtime, ldh = round(overtime - ldh, 2), 0
			elif ldh > overtime:
				overtime, ldh = 0, round(ldh - overtime, 2)
			else:
				overtime = ldh = 0
			if ldh:
				self.less_duty_hours_amount = flt((base_salary / month_days) / 8 * ldh, 2)
		self.less_duty_hours = ldh
		self.overtime_hours = overtime
		if not overtime:
			return

		if emp_type == "PERMANENT":
			per_day = round(base_salary * 0.85) / month_days
			rate = flt((per_day / 8) * 1.5, 2)
		elif emp_type == "DAILY WAGES":
			rate = flt((base_salary / 8) * 1.5, 2)
		else:
			return
		self.overtime_amount = round(rate * overtime)

	def calculate_current_month(self):
		self.current_month_salary = flt(flt(self.working_days) * flt(self.daily_rate), 2)

	def calculate_leave_amount(self):
		"""Leave Amount = Leave Days × (Gross / 30)"""
		if self.leave_encashed and flt(self.gross_salary_calc):
			self.leave_amount = flt(flt(self.leave_encashed) * flt(self.gross_salary_calc) / 30, 2)

	def calculate_bonus(self):
		"""Bonus = Basic Pay / 12 × Bonus Month (entered manually)"""
		if self.bonus_month and flt(self.basic_pay):
			self.bonus_amount = flt(flt(self.basic_pay) / 12 * flt(self.bonus_month), 2)
		else:
			self.bonus_amount = 0

	def _gratuity_allowed(self):
		return bool(
			self.employee and frappe.db.get_value("Employee", self.employee, "custom_gratuity_allow")
		)

	@frappe.whitelist()
	def recalculate_gratuity_if_allowed(self):
		if self._gratuity_allowed():
			self.recalculate_gratuity()

	def enforce_overtime_eligibility(self):
		"""Overtime fields are locked (and zero) unless 'Allow Overtime' is ticked on the Employee."""
		if self.employee and not frappe.db.get_value("Employee", self.employee, "custom_allow_overtime"):
			self.overtime_hours = 0
			self.overtime_amount = 0

	def set_gratuity(self):
		"""Gratuity counts only if 'Gratuity Allow' is ticked on the Employee.
		Years = Final Confirmation Date (else Joining) → Last Working Day,
		same basis as Employee's Total Gratuity. Not allowed → 0 (fields stay editable)."""
		self.gratuity_years = 0
		self.employee_total_gratuity = 0
		self.net_gratuity_payable = 0
		if not self.employee:
			return
		emp = frappe.db.get_value(
			"Employee",
			self.employee,
			["custom_gratuity_allow", "custom_consumed_gratuity_amount", "final_confirmation_date"],
			as_dict=True,
		)
		if not emp:
			return
		self.consumed_gratuity_amount = flt(emp.custom_consumed_gratuity_amount)

		if not emp.custom_gratuity_allow:
			frappe.msgprint(
				_("Gratuity is not applicable for employee {0} ({1}); enter it manually if required").format(
					self.employee, self.employee_name or ""
				),
				indicator="orange",
				alert=True,
			)
			return

		start = emp.final_confirmation_date or self.date_of_joining
		if start and self.last_working_day:
			start, lwd = getdate(start), getdate(self.last_working_day)
			months = (lwd.year - start.year) * 12 + (lwd.month - start.month)
			if lwd.day < start.day:
				months -= 1
			months = max(months, 0)
			self.gratuity_years = flt(months // 12 + (months % 12) / 12, 2)
		self.calculate_gratuity_amount()

	def calculate_gratuity_amount(self):
		"""Total Gratuity = CTC × 80% × rounded years (6+ extra months round up; under
		2 years nothing), Net = Total − Consumed. Same rule as the Employee record."""
		years = flt(self.gratuity_years)
		full = int(years)
		extra_months = round((years - full) * 12)
		rounded_years = full + 1 if extra_months >= 6 else full
		ctc = flt(self.gross_salary_calc) or flt(
			frappe.db.get_value("Employee", self.employee, "ctc")
		)
		total = flt(ctc * 0.8 * rounded_years, 2) if years >= 2 else 0
		self.employee_total_gratuity = total
		self.net_gratuity_payable = flt(total - flt(self.consumed_gratuity_amount), 2)

	@frappe.whitelist()
	def recalculate_gratuity(self):
		"""Called when Gratuity Years is edited: amount follows the new period."""
		self.calculate_gratuity_amount()
		self.calculate_net_payable()

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
			- flt(self.less_duty_hours_amount)
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
		doc.set_gratuity()

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