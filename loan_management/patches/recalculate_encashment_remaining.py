import frappe


def execute():
	"""Fix Employees whose Encashment Remaining went stale (e.g. after loans were deleted)."""
	if not frappe.db.has_column("Employee", "custom_remaining_amount"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabEmployee`
		SET custom_remaining_amount =
			ROUND(GREATEST(IFNULL(custom_encashment_amount, 0) - IFNULL(custom_advance_amount, 0), 0), 2)
		"""
	)
