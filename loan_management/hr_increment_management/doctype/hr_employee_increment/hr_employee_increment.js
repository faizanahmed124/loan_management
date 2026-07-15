// Copyright (c) 2026, Your Company and contributors

frappe.ui.form.on("HR Employee Increment", {

	refresh(frm) {
		frm.trigger("set_indicator");
		frm.trigger("update_value_label");
		frm.trigger("add_buttons");
	},

	increment_type(frm) { frm.trigger("update_value_label"); },
	apply_to_employees(frm) {
		frm.set_value("employees", []);
		frm.set_value("status", "Draft");
		frm.set_value("employment_type", "");  // ← yeh line add karein

	},

	update_value_label(frm) {
		const label = frm.doc.increment_type === "Percentage"
			? "Increment Value (%)"
			: "Increment Amount (Rs)";
		frm.set_df_property("increment_value", "label", label);
	},

	set_indicator(frm) {
		const colors = { Draft:"grey", Previewed:"orange", Applied:"green" };
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "grey");
	},

	add_buttons(frm) {
		if (frm.is_new()) return;
		const can_manage = frappe.user.has_role("HR Manager") || frappe.user.has_role("System Manager");

		// ── Preview ───────────────────────────────────────────────────
		if (frm.doc.status !== "Applied") {
			frm.add_custom_button(__("Preview Increment"), () => {
				if (!frm.doc.increment_value || frm.doc.increment_value <= 0) {
					frappe.msgprint(__("Please set Increment Value first"));
					return;
				}
				frappe.call({
					method: "loan_management.hr_increment_management.doctype.hr_employee_increment.hr_employee_increment.preview_increment",
					args: { increment_doc: frm.doc.name },
					freeze: true,
					freeze_message: __("Fetching employees and calculating..."),
					callback: () => {
						frm.reload_doc();
						frappe.show_alert({ message: __("Preview ready — review the table below"), indicator: "blue" });
					},
				});
			}).addClass("btn-primary");
		}

		// ── Apply ────────────────────────────────────────────────────
		if (frm.doc.status === "Previewed" && can_manage) {
			const emp_count = (frm.doc.employees || []).length;
			frm.add_custom_button(__("Apply Increment"), () => {
				frappe.confirm(
					__("Apply {0} {1} increment to {2} to {3} employee(s)? This will update employee records immediately.",
						[
							frm.doc.increment_value,
							frm.doc.increment_type === "Percentage" ? "%" : "Rs",
							frm.doc.apply_to_field,
							emp_count,
						]
					),
					() => {
						frappe.call({
							method: "loan_management.hr_increment_management.doctype.hr_employee_increment.hr_employee_increment.apply_increment",
							args: { increment_doc: frm.doc.name },
							freeze: true,
							freeze_message: __("Applying increment to employees..."),
							callback: () => frm.reload_doc(),
						});
					}
				);
			}).addClass("btn-success");
		}

		// ── Rollback ────────────────────────────────────────────────
		if (frm.doc.status === "Applied" && can_manage) {
			frm.add_custom_button(__("Rollback Increment"), () => {
				frappe.confirm(
					__("This will revert all {0} employees back to their previous {1} values. Continue?",
						[(frm.doc.employees || []).length, frm.doc.apply_to_field]),
					() => {
						frappe.call({
							method: "loan_management.hr_increment_management.doctype.hr_employee_increment.hr_employee_increment.rollback_increment",
							args: { increment_doc: frm.doc.name },
							freeze: true,
							freeze_message: __("Rolling back..."),
							callback: () => frm.reload_doc(),
						});
					}
				);
			});
		}

		// ── Applied badge ────────────────────────────────────────────
		if (frm.doc.status === "Applied") {
			frm.dashboard.add_indicator(
				__("Increment Applied on {0}", [frappe.format(frm.doc.effective_date, {fieldtype:"Date"})]),
				"green"
			);
		}
	},
});
