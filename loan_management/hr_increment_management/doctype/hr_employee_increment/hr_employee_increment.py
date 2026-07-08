# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


# Map display label → actual fieldname on Employee doctype
FIELD_MAP = {
	"CTC":           "ctc",
	"Basic Salary":  "custom_basic_salary",
}


class HREmployeeIncrement(Document):
	def validate(self):
		if flt(self.increment_value) <= 0:
			frappe.throw(_("Increment Value must be greater than 0"))
		self.total_employees        = len(self.employees)
		self.total_increment_amount = flt(sum(flt(r.increment_amount) for r in self.employees), 2)


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_employees(doc):
	"""Return list of dicts {employee, employee_name, department} based on selection."""
	if doc.apply_to_employees == "Specific Employee":
		if not doc.specific_employee:
			frappe.throw(_("Please select a Specific Employee"))
		emp = frappe.db.get_value(
			"Employee", doc.specific_employee,
			["name", "employee_name", "department", "status"],
			as_dict=True
		)
		if not emp:
			frappe.throw(_("Employee {0} not found").format(doc.specific_employee))
		if emp.status != "Active":
			frappe.throw(_("Employee {0} is not Active").format(doc.specific_employee))
		return [emp]

	filters = {"status": "Active"}
	if doc.apply_to_employees == "By Department":
		if not doc.department_filter:
			frappe.throw(_("Please select a Department"))
		filters["department"] = doc.department_filter

	return frappe.get_all(
		"Employee",
		filters=filters,
		fields=["name as employee", "employee_name", "department"],
	)


def _calculate_increment(current_value, increment_type, increment_value):
	"""Return (increment_amount, new_value)."""
	current = flt(current_value)
	if increment_type == "Percentage":
		inc = flt(current * flt(increment_value) / 100, 2)
	else:  # Amount
		inc = flt(increment_value, 2)
	return inc, flt(current + inc, 2)


# ── whitelisted API methods ───────────────────────────────────────────────────

@frappe.whitelist()
def preview_increment(increment_doc):
	"""
	Fetch employees + calculate new values.
	Shows preview without touching employee records.
	"""
	doc = frappe.get_doc("HR Employee Increment", increment_doc)

	if doc.status == "Applied":
		frappe.throw(_("This increment has already been applied. Cannot re-preview."))

	emp_field = FIELD_MAP.get(doc.apply_to_field)
	if not emp_field:
		frappe.throw(_("Invalid 'Apply To' field selection"))

	employees = _get_employees(doc)
	if not employees:
		frappe.throw(_("No active employees found for the selected criteria"))

	doc.set("employees", [])
	for emp in employees:
		current_value = flt(frappe.db.get_value("Employee", emp.get("employee") or emp.get("name"), emp_field) or 0)
		inc_amount, new_value = _calculate_increment(current_value, doc.increment_type, doc.increment_value)

		doc.append("employees", {
			"employee":         emp.get("employee") or emp.get("name"),
			"employee_name":    emp.get("employee_name"),
			"department":       emp.get("department"),
			"current_value":    current_value,
			"increment_amount": inc_amount,
			"new_value":        new_value,
			"applied":          0,
		})

	doc.status = "Previewed"
	doc.save()
	return doc.name


@frappe.whitelist()
def apply_increment(increment_doc):
	"""
	Apply the increment — update employee records with the new value.
	Can only be applied once (status moves to Applied).
	"""
	if not ("HR Manager" in frappe.get_roles() or "System Manager" in frappe.get_roles()):
		frappe.throw(_("Only HR Manager can apply increments"), frappe.PermissionError)

	doc = frappe.get_doc("HR Employee Increment", increment_doc)

	if doc.status == "Applied":
		frappe.throw(_("This increment has already been applied"))

	if not doc.employees:
		frappe.throw(_("No employees in the preview list. Click 'Preview Increment' first."))

	emp_field = FIELD_MAP.get(doc.apply_to_field)
	if not emp_field:
		frappe.throw(_("Invalid 'Apply To' field selection"))

	applied_count = 0
	errors = []

	for row in doc.employees:
		if row.applied:
			continue
		try:
			frappe.db.set_value("Employee", row.employee, emp_field, flt(row.new_value, 2))
			row.applied = 1
			applied_count += 1
		except Exception as e:
			errors.append(f"{row.employee}: {str(e)}")

	doc.status = "Applied"
	doc.save()

	if errors:
		frappe.msgprint(
			_("Increment applied to {0} employee(s). Errors: {1}").format(applied_count, "<br>".join(errors)),
			title=_("Partially Applied"), indicator="orange"
		)
	else:
		frappe.msgprint(
			_("{0} employee(s) updated successfully on {1}.").format(applied_count, doc.apply_to_field),
			title=_("Increment Applied"), indicator="green"
		)

	return doc.name


@frappe.whitelist()
def rollback_increment(increment_doc):
	"""
	Rollback: restore current_value back to employee records.
	Only works if the increment has been Applied.
	"""
	if not ("HR Manager" in frappe.get_roles() or "System Manager" in frappe.get_roles()):
		frappe.throw(_("Only HR Manager can rollback increments"), frappe.PermissionError)

	doc = frappe.get_doc("HR Employee Increment", increment_doc)

	if doc.status != "Applied":
		frappe.throw(_("Only Applied increments can be rolled back"))

	emp_field = FIELD_MAP.get(doc.apply_to_field)
	rolled_back = 0

	for row in doc.employees:
		if not row.applied:
			continue
		try:
			frappe.db.set_value("Employee", row.employee, emp_field, flt(row.current_value, 2))
			row.applied = 0
			rolled_back += 1
		except Exception:
			pass

	doc.status = "Previewed"
	doc.save()

	frappe.msgprint(
		_("{0} employee(s) rolled back to previous {1} values.").format(rolled_back, doc.apply_to_field),
		title=_("Rollback Complete"), indicator="blue"
	)
	return doc.name
