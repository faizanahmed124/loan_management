# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data    = get_data(filters)
	chart   = get_chart(data)
	summary = get_summary(data)
	return columns, data, None, chart, summary


def get_columns():
	return [
		{
			"label":     _("Loan ID"),
			"fieldname": "loan",
			"fieldtype": "Link",
			"options":   "HR Loan",
			"width":     160,
		},
		{
			"label":     _("Employee ID"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options":   "Employee",
			"width":     110,
		},
		{
			"label":     _("Employee Name"),
			"fieldname": "employee_name",
			"fieldtype": "Data",
			"width":     160,
		},
		{
			"label":     _("Department"),
			"fieldname": "department",
			"fieldtype": "Link",
			"options":   "Department",
			"width":     130,
		},
		{
			"label":     _("Loan Type"),
			"fieldname": "loan_type",
			"fieldtype": "Link",
			"options":   "HR Loan Type",
			"width":     120,
		},
		{
			"label":     _("Repayment Source"),
			"fieldname": "loan_source",
			"fieldtype": "Data",
			"width":     120,
		},
		{
			"label":     _("Disbursement Date"),
			"fieldname": "disbursement_date",
			"fieldtype": "Date",
			"width":     130,
		},
		{
			"label":     _("Loan Amount"),
			"fieldname": "loan_amount",
			"fieldtype": "Currency",
			"width":     130,
		},
		{
			"label":     _("Monthly Installment"),
			"fieldname": "monthly_installment_amount",
			"fieldtype": "Currency",
			"width":     140,
		},
		{
			"label":     _("Total Installments"),
			"fieldname": "repayment_periods",
			"fieldtype": "Int",
			"width":     120,
		},
		{
			"label":     _("Paid Installments"),
			"fieldname": "paid_installments",
			"fieldtype": "Int",
			"width":     120,
		},
		{
			"label":     _("Pending Installments"),
			"fieldname": "pending_installments",
			"fieldtype": "Int",
			"width":     130,
		},
		{
			"label":     _("Amount Paid"),
			"fieldname": "total_amount_paid",
			"fieldtype": "Currency",
			"width":     130,
		},
		{
			"label":     _("Balance Remaining"),
			"fieldname": "balance_amount",
			"fieldtype": "Currency",
			"width":     140,
		},
		{
			"label":     _("Status"),
			"fieldname": "status",
			"fieldtype": "Data",
			"width":     100,
		},
	]


def get_data(filters):
	conditions = get_conditions(filters)

	loans = frappe.db.sql(f"""
		SELECT
			l.name                    AS loan,
			l.employee                AS employee,
			l.employee_name           AS employee_name,
			e.department              AS department,
			l.loan_type               AS loan_type,
			l.loan_source             AS loan_source,
			l.disbursement_date       AS disbursement_date,
			l.loan_amount             AS loan_amount,
			l.monthly_installment_amount AS monthly_installment_amount,
			l.repayment_periods       AS repayment_periods,
			l.total_amount_paid       AS total_amount_paid,
			l.balance_amount          AS balance_amount,
			l.status                  AS status
		FROM
			`tabHR Loan` l
		LEFT JOIN
			`tabEmployee` e ON e.name = l.employee
		WHERE
			1=1 {conditions}
		ORDER BY
			l.disbursement_date DESC, l.employee ASC
	""", filters, as_dict=True)

	# Fetch installment counts from repayment schedule
	for row in loans:
		schedule = frappe.get_all(
			"HR Loan Repayment Schedule",
			filters={"parent": row.loan, "parenttype": "HR Loan"},
			fields=["is_paid"],
		)
		row.paid_installments    = sum(1 for s in schedule if s.is_paid)
		row.pending_installments = sum(1 for s in schedule if not s.is_paid)

		# Color coding for status
		if row.status == "Closed":
			row.balance_amount = 0

	return loans


def get_conditions(filters):
	conditions = ""

	if filters.get("company"):
		conditions += " AND l.company = %(company)s"

	if filters.get("employee"):
		conditions += " AND l.employee = %(employee)s"

	if filters.get("department"):
		conditions += " AND e.department = %(department)s"

	if filters.get("loan_type"):
		conditions += " AND l.loan_type = %(loan_type)s"

	if filters.get("loan_source"):
		conditions += " AND l.loan_source = %(loan_source)s"

	if filters.get("status"):
		conditions += " AND l.status = %(status)s"

	if filters.get("from_date"):
		conditions += " AND l.disbursement_date >= %(from_date)s"

	if filters.get("to_date"):
		conditions += " AND l.disbursement_date <= %(to_date)s"

	return conditions


def get_chart(data):
	if not data:
		return None

	# Top 10 employees by loan amount
	employee_loans = {}
	for row in data:
		if row.status not in ("Cancelled",):
			emp = row.employee_name or row.employee
			employee_loans[emp] = employee_loans.get(emp, 0) + flt(row.balance_amount)

	top10 = sorted(employee_loans.items(), key=lambda x: x[1], reverse=True)[:10]
	if not top10:
		return None

	return {
		"data": {
			"labels":   [x[0] for x in top10],
			"datasets": [{
				"name":   "Balance Remaining",
				"values": [x[1] for x in top10],
			}],
		},
		"type":        "bar",
		"title":       "Top 10 Employees by Outstanding Loan Balance",
		"colors":      ["#8B1A1A"],
		"barOptions":  {"stacked": 0},
	}


def get_summary(data):
	if not data:
		return None

	active_loans   = [r for r in data if r.status == "Disbursed"]
	closed_loans   = [r for r in data if r.status == "Closed"]
	sanctioned     = [r for r in data if r.status == "Sanctioned"]

	total_disbursed  = sum(flt(r.loan_amount)      for r in data if r.status != "Cancelled")
	total_paid       = sum(flt(r.total_amount_paid) for r in data if r.status != "Cancelled")
	total_balance    = sum(flt(r.balance_amount)    for r in active_loans)

	return [
		{
			"value":      len(active_loans),
			"label":      "Active Loans",
			"datatype":   "Int",
			"indicator":  "blue",
		},
		{
			"value":      total_disbursed,
			"label":      "Total Loan Amount",
			"datatype":   "Currency",
			"indicator":  "grey",
		},
		{
			"value":      total_paid,
			"label":      "Total Amount Recovered",
			"datatype":   "Currency",
			"indicator":  "green",
		},
		{
			"value":      total_balance,
			"label":      "Total Outstanding Balance",
			"datatype":   "Currency",
			"indicator":  "red",
		},
		{
			"value":      len(closed_loans),
			"label":      "Closed Loans",
			"datatype":   "Int",
			"indicator":  "green",
		},
	]
