// Copyright (c) 2026, Your Company and contributors
// For license information, please see license.txt

frappe.ui.form.on("HR Loan", {
	refresh(frm) {
		frm.trigger("set_indicator");
		frm.trigger("add_buttons");
	},

	set_indicator(frm) {
		const colors = {
			Sanctioned: "orange",
			Disbursed: "blue",
			Closed: "green",
			Cancelled: "red",
		};
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "grey");
	},

	add_buttons(frm) {
		if (frm.is_new()) return;

		const can_manage = frappe.user.has_role("HR Manager") || frappe.user.has_role("System Manager");
		if (!can_manage) return;

		if (frm.doc.status === "Sanctioned") {
			frm.add_custom_button(__("Disburse Loan"), () => {
				frappe.prompt(
					[
						{
							fieldname: "disbursement_date",
							label: __("Disbursement Date"),
							fieldtype: "Date",
							default: frappe.datetime.get_today(),
							reqd: 1,
						},
					],
					(values) => {
						frappe.call({
							method: "loan_management.hr_loan_management.doctype.hr_loan.hr_loan.disburse",
							args: { loan: frm.doc.name, disbursement_date: values.disbursement_date },
							freeze: true,
							freeze_message: __("Disbursing and generating repayment schedule..."),
							callback: () => frm.reload_doc(),
						});
					},
					__("Disburse Loan"),
					__("Disburse")
				);
			}).addClass("btn-primary");

			frm.add_custom_button(__("Cancel Loan"), () => {
				frappe.confirm(__("Cancel this loan before disbursement?"), () => {
					frappe.call({
						method: "loan_management.hr_loan_management.doctype.hr_loan.hr_loan.cancel_loan",
						args: { loan: frm.doc.name },
						freeze: true,
						callback: () => frm.reload_doc(),
					});
				});
			});
		}

		if (frm.doc.status === "Disbursed") {
			frm.dashboard.add_indicator(
				__("Balance: {0}", [format_currency(frm.doc.balance_amount, frm.doc.currency)]),
				frm.doc.balance_amount > 0 ? "orange" : "green"
			);
		}
	},
});
