// Copyright (c) 2026, Your Company and contributors
// For license information, please see license.txt

frappe.ui.form.on("HR Bonus Calculation", {
	refresh(frm) {
		frm.trigger("add_buttons");
	},

	add_buttons(frm) {
		if (frm.is_new()) {
			frm.dashboard.set_headline(__("Save the document first, then use Get Employees / Calculate Bonus"));
			return;
		}

		frm.add_custom_button(__("Get Employees"), () => {
			if (!frm.doc.department) {
				frappe.msgprint(__("Please select a Department first"));
				return;
			}
			frappe.call({
				method: "loan_management.hr_bonus_management.doctype.hr_bonus_calculation.hr_bonus_calculation.fetch_employees",
				args: { bonus_calculation: frm.doc.name },
				freeze: true,
				freeze_message: __("Fetching employees..."),
				callback: () => frm.reload_doc(),
			});
		}).addClass("btn-primary");

		frm.add_custom_button(__("Calculate Bonus"), () => {
			if (!(frm.doc.employees && frm.doc.employees.length)) {
				frappe.msgprint(__("No employees in the table. Click 'Get Employees' first."));
				return;
			}
			frappe.call({
				method: "loan_management.hr_bonus_management.doctype.hr_bonus_calculation.hr_bonus_calculation.calculate_bonus",
				args: { bonus_calculation: frm.doc.name },
				freeze: true,
				freeze_message: __("Calculating bonus..."),
				callback: () => frm.reload_doc(),
			});
		});
	},
});
