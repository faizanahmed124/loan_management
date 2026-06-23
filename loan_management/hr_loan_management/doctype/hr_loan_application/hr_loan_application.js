// Copyright (c) 2026, Your Company and contributors
// For license information, please see license.txt

frappe.ui.form.on("HR Loan Application", {
	refresh(frm) {
		frm.trigger("set_indicator");
		frm.trigger("add_buttons");
	},

	set_indicator(frm) {
		const colors = { Open: "orange", Approved: "green", Rejected: "red" };
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "grey");
	},

	add_buttons(frm) {
		if (frm.is_new()) return;

		const can_approve = frappe.user.has_role("HR Manager") || frappe.user.has_role("System Manager");

		if (frm.doc.status === "Open" && can_approve) {
			frm.add_custom_button(__("Approve"), () => {
				frm.events.call_approve(frm, "Approved");
			}, __("Status"));

			frm.add_custom_button(__("Reject"), () => {
				frm.events.call_approve(frm, "Rejected");
			}, __("Status"));
		}

		if (frm.doc.status === "Approved" && !frm.doc.loan) {
			frm.add_custom_button(__("Create Loan"), () => {
				frappe.call({
					method: "loan_management.hr_loan_management.doctype.hr_loan_application.hr_loan_application.create_loan",
					args: { loan_application: frm.doc.name },
					freeze: true,
					freeze_message: __("Creating Loan..."),
					callback: (r) => {
						if (r.message) {
							frappe.set_route("Form", "HR Loan", r.message);
						}
					},
				});
			}).addClass("btn-primary");
		}

		if (frm.doc.loan) {
			frm.add_custom_button(__("View Loan"), () => {
				frappe.set_route("Form", "HR Loan", frm.doc.loan);
			});
		}
	},

	call_approve(frm, status) {
		frappe.confirm(__("Are you sure you want to mark this application as {0}?", [status]), () => {
			frappe.call({
				method: "loan_management.hr_loan_management.doctype.hr_loan_application.hr_loan_application.approve_or_reject",
				args: { loan_application: frm.doc.name, status: status },
				freeze: true,
				callback: () => frm.reload_doc(),
			});
		});
	},
});
