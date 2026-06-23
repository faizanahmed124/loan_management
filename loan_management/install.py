# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe


def after_install():
	create_loan_salary_component()


def create_loan_salary_component():
	if frappe.db.exists("Salary Component", "Loan EMI Deduction"):
		return

	component = frappe.new_doc("Salary Component")
	component.salary_component = "Loan EMI Deduction"
	component.type = "Deduction"
	component.description = "Auto-created by the HR Loan app for employee loan EMI deductions."
	component.insert(ignore_permissions=True)
	frappe.db.commit()
