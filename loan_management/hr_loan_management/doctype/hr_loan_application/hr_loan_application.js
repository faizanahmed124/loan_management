frappe.ui.form.on("HR Loan Application", {
	refresh(frm) {
		frm.trigger("set_indicator");
		frm.trigger("add_buttons");
	},

	loan_amount(frm)                 { frm.trigger("calc_periods"); },
	monthly_installment_amount(frm)  { frm.trigger("calc_periods"); },

	calc_periods(frm) {
		const loan = flt(frm.doc.loan_amount);
		const inst = flt(frm.doc.monthly_installment_amount);
		if (loan > 0 && inst > 0) {
			const months = Math.ceil(loan / inst);
			frm.set_value("repayment_periods", months);
			const full   = Math.floor(loan / inst);
			const last   = flt(loan - (full * inst));
			if (last > 0) {
				frm.set_df_property("repayment_periods", "description",
					`${full} month(s) × Rs ${inst.toLocaleString()} + 1 last month × Rs ${last.toLocaleString()} = ${months} total`);
			} else {
				frm.set_df_property("repayment_periods", "description",
					`${months} month(s) × Rs ${inst.toLocaleString()}`);
			}
		}
	},

	from_salary(frm)   { if (frm.doc.from_salary)   { frm.set_value("from_bonus",0); frm.set_value("from_gratuity",0); } },
	from_bonus(frm)    { if (frm.doc.from_bonus)     { frm.set_value("from_salary",0); frm.set_value("from_gratuity",0); } },
	from_gratuity(frm) { if (frm.doc.from_gratuity)  { frm.set_value("from_salary",0); frm.set_value("from_bonus",0); } },

	set_indicator(frm) {
		const colors = { Open:"orange", Approved:"green", Rejected:"red", Cancelled:"grey" };
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "grey");
	},

	add_buttons(frm) {
		if (frm.is_new()) return;
		const can_manage = frappe.user.has_role("HR Manager") || frappe.user.has_role("System Manager");

		if (frm.doc.status === "Open" && can_manage) {
			frm.add_custom_button(__("Approve"), () => frm.events.call_approve(frm, "Approved"), __("Status"));
			frm.add_custom_button(__("Reject"),  () => frm.events.call_approve(frm, "Rejected"),  __("Status"));
		}

		if (frm.doc.status === "Approved" && !frm.doc.loan) {
			frm.add_custom_button(__("Create Loan"), () => {
				frappe.call({
					method: "loan_management.hr_loan_management.doctype.hr_loan_application.hr_loan_application.create_loan",
					args: { loan_application: frm.doc.name },
					freeze: true, freeze_message: __("Creating Loan..."),
					callback: (r) => { if (r.message) frappe.set_route("Form", "HR Loan", r.message); },
				});
			}).addClass("btn-primary");
		}

		if (frm.doc.loan) {
			frm.add_custom_button(__("View Loan"), () => frappe.set_route("Form", "HR Loan", frm.doc.loan));
		}

		if (!["Cancelled","Rejected"].includes(frm.doc.status) && can_manage) {
			frm.add_custom_button(__("Cancel Application"), () => {
				frappe.confirm(__("Cancel this application?"), () => {
					frappe.call({
						method: "loan_management.hr_loan_management.doctype.hr_loan_application.hr_loan_application.cancel_application",
						args: { loan_application: frm.doc.name },
						freeze: true, callback: () => frm.reload_doc(),
					});
				});
			});
		}

		if (frm.doc.status === "Cancelled" && can_manage) {
			frm.add_custom_button(__("Delete"), () => {
				frappe.confirm(__("Permanently delete this application?"), () => {
					frappe.call({
						method: "frappe.client.delete",
						args: { doctype: "HR Loan Application", name: frm.doc.name },
						callback: () => frappe.set_route("List", "HR Loan Application"),
					});
				});
			});
		}
	},

	call_approve(frm, status) {
		frappe.confirm(__("Mark as {0}?", [status]), () => {
			frappe.call({
				method: "loan_management.hr_loan_management.doctype.hr_loan_application.hr_loan_application.approve_or_reject",
				args: { loan_application: frm.doc.name, status: status },
				freeze: true, callback: () => frm.reload_doc(),
			});
		});
	},
});

function flt(val) { return parseFloat(val) || 0; }
