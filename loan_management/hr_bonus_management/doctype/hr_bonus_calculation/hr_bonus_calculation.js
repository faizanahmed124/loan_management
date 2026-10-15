// Copyright (c) 2026, Your Company and contributors
// For license information, please see license.txt

frappe.ui.form.on("HR Bonus Calculation", {
	refresh(frm) {
		frm.trigger("add_buttons");
	},

	add_buttons(frm) {
		if (frm.is_new()) return;

		if (frm.doc.docstatus === 0) {
			// ── Get / refresh employees ────────────────────────────────────────
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
			});

			// ── Calculate Bonus (uses as_on_date set on form) ─────────────────
			frm.add_custom_button(__("Calculate Bonus"), () => {
				if (!frm.doc.as_on_date) {
					frappe.msgprint(__("Please set the 'Calculate As On Date' first"));
					return;
				}
				frappe.call({
					method: "loan_management.hr_bonus_management.doctype.hr_bonus_calculation.hr_bonus_calculation.calculate_bonus",
					args: { bonus_calculation: frm.doc.name },
					freeze: true,
					freeze_message: __("Calculating bonus..."),
					callback: (r) => {
						frm.reload_doc();
						frappe.show_alert({ message: __("Bonus calculated"), indicator: "green" });
					},
				});
			}).addClass("btn-primary");

			// ── Recalculate Now (sets as_on_date = today) ─────────────────────
			frm.add_custom_button(__("Recalculate Now (Today)"), () => {
				frappe.confirm(
					__("This will set <b>As On Date = Today</b> and recalculate all employee bonuses. Continue?"),
					() => {
						frappe.call({
							method: "loan_management.hr_bonus_management.doctype.hr_bonus_calculation.hr_bonus_calculation.recalculate_now",
							args: { bonus_calculation: frm.doc.name },
							freeze: true,
							freeze_message: __("Recalculating..."),
							callback: () => {
								frm.reload_doc();
								frappe.show_alert({ message: __("Bonus recalculated with today's date"), indicator: "green" });
							},
						});
					}
				);
			});
		}
	},
});
