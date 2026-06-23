# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class HRLoanType(Document):
	def validate(self):
		if self.max_loan_amount and self.max_loan_amount <= 0:
			frappe.throw("Maximum Loan Amount must be greater than 0")

		if self.rate_of_interest and self.rate_of_interest < 0:
			frappe.throw("Rate of Interest cannot be negative")
