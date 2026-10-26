import frappe


def execute():
	"""
	disburse() used to add the Gratuity loan amount to Consumed Gratuity a second time
	(create_loan had already added it). Undo that only where the value is exactly double
	the employee's active Gratuity loans, so manual edits / repayments are left untouched.
	"""
	frappe.db.sql(
		"""
		UPDATE `tabEmployee` e
		JOIN (
			SELECT employee, SUM(loan_amount) AS total
			FROM `tabHR Loan`
			WHERE loan_source = 'Gratuity' AND status = 'Disbursed'
			GROUP BY employee
		) l ON l.employee = e.name
		SET e.custom_consumed_gratuity_amount = l.total
		WHERE l.total > 0
			AND ROUND(e.custom_consumed_gratuity_amount, 2) = ROUND(2 * l.total, 2)
		"""
	)
