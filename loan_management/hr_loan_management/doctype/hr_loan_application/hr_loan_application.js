// Copyright (c) 2026, Your Company and contributors
// For license information, please see license.txt

frappe.ui.form.on("HR Loan Application", {
	refresh(frm) {
		frm.trigger("set_indicator");
		frm.trigger("add_buttons");
		frm.trigger("toggle_installment_field");
	},

	set_indicator(frm) {
		const colors = { Open: "orange", Approved: "green", Rejected: "red", Cancelled: "red" };
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "grey");
	},

	// ── Radio-group behaviour for repayment source ──────────────────────────

	from_salary(frm)      { frm.events._radio_source(frm, "from_salary"); },
	from_bonus(frm)       { frm.events._radio_source(frm, "from_bonus"); },
	from_gratuity(frm)    { frm.events._radio_source(frm, "from_gratuity"); },
	from_encashment(frm)  { frm.events._radio_source(frm, "from_encashment"); },

	_radio_source(frm, checked_field) {
		const all_sources = ["from_salary", "from_bonus", "from_gratuity", "from_encashment"];
		if (frm.doc[checked_field]) {
			all_sources.forEach(f => {
				if (f !== checked_field) frm.set_value(f, 0);
			});
		}
		frm.trigger("toggle_installment_field");
	},

	toggle_installment_field(frm) {
		// Bonus and Encashment → installment = full loan amount (auto-set); hide the field
		const lump_sum = frm.doc.from_bonus || frm.doc.from_encashment;
		frm.set_df_property("monthly_installment_amount", "hidden", lump_sum ? 1 : 0);
		frm.set_df_property("monthly_installment_amount", "reqd",   lump_sum ? 0 : 1);
		if (lump_sum && frm.doc.loan_amount) {
			frm.set_value("monthly_installment_amount", frm.doc.loan_amount);
		}
	},

	loan_amount(frm) {
		frm.trigger("toggle_installment_field");
	},

	// ── Gratuity popup before saving ────────────────────────────────────────

	validate(frm) {
		if (frm.doc.from_gratuity && !frm._gratuity_popup_done) {
			// Cancel the current save and show the dialog
			frappe.validated = false;

			frappe.confirm(
				__("Do you want to also deduct one installment from <b>Bonus</b> and one from <b>Leave Encashment</b> in addition to the Gratuity loan?"),
				// Yes
				() => {
					frm._gratuity_popup_done = true;
					frm.set_value("also_deduct_from_bonus_encashment", 1).then(() => frm.save());
				},
				// No
				() => {
					frm._gratuity_popup_done = true;
					frm.set_value("also_deduct_from_bonus_encashment", 0).then(() => frm.save());
				}
			);
		}
	},

	// ── Action buttons ───────────────────────────────────────────────────────

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

		if (frm.doc.status === "Open" && can_approve) {
			frm.add_custom_button(__("Cancel Application"), () => {
				frappe.confirm(__("Cancel this application?"), () => {
					frappe.call({
						method: "loan_management.hr_loan_management.doctype.hr_loan_application.hr_loan_application.cancel_application",
						args: { loan_application: frm.doc.name },
						freeze: true,
						callback: () => frm.reload_doc(),
					});
				});
			});
		}
	},

	call_approve(frm, status) {
		frappe.confirm(__("Mark this application as {0}?", [status]), () => {
			frappe.call({
				method: "loan_management.hr_loan_management.doctype.hr_loan_application.hr_loan_application.approve_or_reject",
				args: { loan_application: frm.doc.name, status: status },
				freeze: true,
				callback: () => frm.reload_doc(),
			});
		});
	},
});
