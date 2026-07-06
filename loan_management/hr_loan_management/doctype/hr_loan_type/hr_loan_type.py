# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from frappe.model.document import Document


class HRLoanType(Document):
	def validate(self):
		if flt(self.max_loan_amount) <= 0:
			frappe.throw(_("Maximum Loan Amount must be greater than 0"))
		if flt(self.rate_of_interest) < 0:
			frappe.throw(_("Rate of Interest cannot be negative"))
