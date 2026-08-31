# Copyright (c) 2026, Your Company and contributors
import math
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, flt, getdate, today


class HRLoan(Document):
	def validate(self):
		self.calculate_repayment_summary()
		self.balance_amount = flt(self.total_payable_amount) - flt(self.total_amount_paid)

	def on_trash(self):
		if self.loan_application and frappe.db.exists("HR Loan Application", self.loan_application):
			frappe.db.set_value("HR Loan Application", self.loan_application, "loan", None)
		if self.disbursement_journal_entry:
			cancel_journal_entry(self.disbursement_journal_entry)

	def calculate_repayment_summary(self):
		loan = flt(self.loan_amount)
		inst = flt(self.monthly_installment_amount)
		if not loan or not inst:
			return
		self.repayment_periods        = math.ceil(loan / inst)
		self.monthly_repayment_amount = inst
		self.total_payable_amount     = flt(loan, 2)
		self.total_interest_payable   = 0

	def generate_repayment_schedule(self):
		self.set("repayment_schedule", [])
		loan    = flt(self.loan_amount)
		inst    = flt(self.monthly_installment_amount)
		if not loan or not inst:
			return
		balance = loan
		month   = 0
		while balance > 0.009:
			month        += 1
			payment       = flt(min(inst, balance), 2)
			balance       = flt(balance - payment, 2)
			if balance < 0: balance = 0
			self.append("repayment_schedule", {
				"payment_date":        add_months(self.disbursement_date, month),
				"principal_amount":    payment,
				"interest_amount":     0,
				"total_payment":       payment,
				"balance_loan_amount": balance,
			})


def make_disbursement_journal_entry(loan_doc):
	if not loan_doc.loan_account or not loan_doc.payment_account:
		frappe.msgprint(
			_("Loan Account or Disbursement Account not set — skipping GL entry."),
			alert=True, indicator="orange"
		)
		return None

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company      = loan_doc.company
	je.posting_date = loan_doc.disbursement_date
	je.user_remark  = (
		f"Loan disbursed to {loan_doc.employee_name} "
		f"({loan_doc.employee}) — {loan_doc.name}"
	)
	je.cheque_no   = loan_doc.name
	je.cheque_date = loan_doc.disbursement_date

	# Debit: Loan Account (employee receivable)
	je.append("accounts", {
		"account":                    loan_doc.loan_account,
		"debit_in_account_currency":  flt(loan_doc.loan_amount, 2),
		"credit_in_account_currency": 0,
		"party_type":                 "Employee",
		"party":                      loan_doc.employee,
		"user_remark":                f"Loan disbursement — {loan_doc.name}",
	})

	# Credit: Bank / Cash Account
	je.append("accounts", {
		"account":                    loan_doc.payment_account,
		"credit_in_account_currency": flt(loan_doc.loan_amount, 2),
		"debit_in_account_currency":  0,
		"user_remark":                f"Loan disbursement — {loan_doc.name}",
	})

	je.insert(ignore_permissions=True)
	je.submit()
	return je.name


def make_repayment_journal_entry(loan_name, amount, posting_date, salary_slip_name=None):
	loan = frappe.get_doc("HR Loan", loan_name)
	if not loan.loan_account or not loan.payment_account:
		return None

	remark = f"Loan repayment — {loan_name}"
	if salary_slip_name:
		remark += f" via {salary_slip_name}"

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company      = loan.company
	je.posting_date = posting_date
	je.user_remark  = remark
	je.cheque_no    = salary_slip_name or loan_name
	je.cheque_date  = posting_date

	# Debit: Bank / Cash Account (money received back)
	je.append("accounts", {
		"account":                    loan.payment_account,
		"debit_in_account_currency":  flt(amount, 2),
		"credit_in_account_currency": 0,
		"user_remark":                remark,
	})

	# Credit: Loan Account (reducing outstanding)
	je.append("accounts", {
		"account":                    loan.loan_account,
		"credit_in_account_currency": flt(amount, 2),
		"debit_in_account_currency":  0,
		"party_type":                 "Employee",
		"party":                      loan.employee,
		"user_remark":                remark,
	})

	je.insert(ignore_permissions=True)
	je.submit()
	return je.name


def cancel_journal_entry(je_name):
	if not je_name or not frappe.db.exists("Journal Entry", je_name):
		return
	try:
		je = frappe.get_doc("Journal Entry", je_name)
		if je.docstatus == 1:
			je.cancel()
	except Exception:
		pass


@frappe.whitelist()
def recalculate_schedule_from_row(loan, row_name, new_amount):
	"""
	Server-side: when user edits a row's amount:
	  1. Update that row
	  2. Delete all unpaid rows after it
	  3. Regenerate rows from remaining balance using monthly_installment_amount
	"""
	doc          = frappe.get_doc("HR Loan", loan)
	new_amount   = flt(new_amount)
	monthly_inst = flt(doc.monthly_installment_amount)
	total_loan   = flt(doc.loan_amount)

	target_idx = next(
		(i for i, r in enumerate(doc.repayment_schedule) if r.name == row_name), None
	)
	if target_idx is None:
		frappe.throw(_("Row not found in repayment schedule"))

	paid_total  = flt(sum(flt(r.total_payment) for r in doc.repayment_schedule if r.is_paid), 2)
	prev_unpaid = flt(sum(
		flt(r.total_payment)
		for i, r in enumerate(doc.repayment_schedule)
		if not r.is_paid and i < target_idx
	), 2)
	max_allowed = flt(total_loan - paid_total - prev_unpaid, 2)

	if new_amount > max_allowed: new_amount = max_allowed
	if new_amount < 0:           new_amount = 0

	target_row = doc.repayment_schedule[target_idx]
	target_row.total_payment       = flt(new_amount, 2)
	target_row.principal_amount    = flt(new_amount, 2)
	target_row.interest_amount     = 0
	remaining = flt(max_allowed - new_amount, 2)
	target_row.balance_loan_amount = flt(remaining if remaining > 0 else 0, 2)

	kept_rows = []
	for i, row in enumerate(doc.repayment_schedule):
		if i <= target_idx:
			kept_rows.append({
				"payment_date":        row.payment_date,
				"principal_amount":    row.principal_amount,
				"interest_amount":     row.interest_amount,
				"total_payment":       row.total_payment,
				"balance_loan_amount": row.balance_loan_amount,
				"is_paid":             row.is_paid,
				"paid_on":             row.paid_on,
				"salary_slip":         row.salary_slip,
			})

	new_rows = []
	if remaining > 0.009 and monthly_inst > 0:
		balance   = remaining
		last_date = getdate(target_row.payment_date)
		while balance > 0.009:
			payment   = flt(min(monthly_inst, balance), 2)
			last_date = add_months(last_date, 1)
			balance   = flt(balance - payment, 2)
			if balance < 0: balance = 0
			new_rows.append({
				"payment_date":        last_date,
				"principal_amount":    payment,
				"interest_amount":     0,
				"total_payment":       payment,
				"balance_loan_amount": flt(balance, 2),
			})

	doc.set("repayment_schedule", [])
	for r in kept_rows + new_rows:
		doc.append("repayment_schedule", r)

	doc.balance_amount = flt(remaining, 2)
	doc.save()
	return doc.name


@frappe.whitelist()
def reschedule(loan):
	doc         = frappe.get_doc("HR Loan", loan)
	paid_rows   = [r for r in doc.repayment_schedule if r.is_paid]
	unpaid_rows = [r for r in doc.repayment_schedule if not r.is_paid and flt(r.total_payment) > 0]

	if not unpaid_rows:
		frappe.throw(_("No unpaid installments left"))

	paid_amount       = flt(sum(flt(r.total_payment) for r in paid_rows), 2)
	remaining_balance = flt(flt(doc.loan_amount) - paid_amount, 2)

	if remaining_balance <= 0:
		frappe.throw(_("No outstanding balance remaining"))

	running = remaining_balance
	for row in unpaid_rows:
		row.principal_amount    = flt(row.total_payment, 2)
		row.interest_amount     = 0
		running                 = flt(running - row.total_payment, 2)
		row.balance_loan_amount = flt(running if running > 0 else 0, 2)

	doc.set("repayment_schedule", [])
	for r in paid_rows:
		doc.append("repayment_schedule", {
			"payment_date":        r.payment_date,
			"principal_amount":    r.principal_amount,
			"interest_amount":     r.interest_amount,
			"total_payment":       r.total_payment,
			"balance_loan_amount": r.balance_loan_amount,
			"is_paid":             r.is_paid,
			"paid_on":             r.paid_on,
			"salary_slip":         r.salary_slip,
		})
	for r in unpaid_rows:
		if flt(r.total_payment) > 0:
			doc.append("repayment_schedule", {
				"payment_date":        r.payment_date,
				"principal_amount":    r.principal_amount,
				"interest_amount":     r.interest_amount,
				"total_payment":       r.total_payment,
				"balance_loan_amount": r.balance_loan_amount,
			})

	doc.balance_amount = flt(remaining_balance, 2)
	doc.save()
	return doc.name


@frappe.whitelist()
def disburse(loan, disbursement_date=None):
	if not ("HR Manager" in frappe.get_roles() or "System Manager" in frappe.get_roles()):
		frappe.throw(_("Only HR Manager can disburse"), frappe.PermissionError)

	doc = frappe.get_doc("HR Loan", loan)
	if doc.status != "Sanctioned":
		frappe.throw(_("Only Sanctioned loans can be disbursed"))

	doc.disbursement_date = getdate(disbursement_date or today())
	doc.generate_repayment_schedule()
	doc.status = "Disbursed"
	doc.save()

	je_name = make_disbursement_journal_entry(doc)
	if je_name:
		frappe.db.set_value("HR Loan", loan, "disbursement_journal_entry", je_name)
		frappe.msgprint(
			_("Loan disbursed. Journal Entry {0} created.").format(
				f'<a href="/app/journal-entry/{je_name}">{je_name}</a>'
			),
			title=_("GL Entry Created"),
			indicator="green",
		)
	return doc.name


@frappe.whitelist()
def cancel_loan(loan):
	if not ("HR Manager" in frappe.get_roles() or "System Manager" in frappe.get_roles()):
		frappe.throw(_("Only HR Manager can cancel"), frappe.PermissionError)

	doc = frappe.get_doc("HR Loan", loan)
	if doc.status not in ("Sanctioned", "Disbursed"):
		frappe.throw(_("Only Sanctioned or Disbursed loans can be cancelled"))

	if doc.disbursement_journal_entry:
		cancel_journal_entry(doc.disbursement_journal_entry)

	doc.status = "Cancelled"
	doc.save()
	return doc.status