// Copyright (c) 2026, Your Company and contributors
// For license information, please see license.txt

frappe.ui.form.on("HR Loan", {
	refresh(frm) {
		frm.trigger("set_indicator");
		frm.trigger("add_buttons");
	},

	set_indicator(frm) {
		const colors = { Sanctioned:"orange", Disbursed:"blue", Closed:"green", Cancelled:"red" };
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "grey");
	},

	add_buttons(frm) {
		if (frm.is_new()) return;
		const can_manage = frappe.user.has_role("HR Manager") || frappe.user.has_role("System Manager");

		// ── Sanctioned ─────────────────────────────────────────────────────
		if (frm.doc.status === "Sanctioned" && can_manage) {
			frm.add_custom_button(__("Disburse Loan"), () => {
				frappe.prompt([{
					fieldname: "disbursement_date",
					label: __("Disbursement Date"),
					fieldtype: "Date",
					default: frappe.datetime.get_today(),
					reqd: 1,
				}], (values) => {
					frappe.call({
						method: "loan_management.hr_loan_management.doctype.hr_loan.hr_loan.disburse",
						args: { loan: frm.doc.name, disbursement_date: values.disbursement_date },
						freeze: true, freeze_message: __("Disbursing & creating GL entry..."),
						callback: () => frm.reload_doc(),
					});
				}, __("Disburse Loan"), __("Disburse"));
			}).addClass("btn-primary");

			frm.add_custom_button(__("Cancel Loan"), () => {
				frappe.confirm(__("Cancel this loan?"), () => {
					frappe.call({
						method: "loan_management.hr_loan_management.doctype.hr_loan.hr_loan.cancel_loan",
						args: { loan: frm.doc.name },
						freeze: true, callback: () => frm.reload_doc(),
					});
				});
			});
		}

		// ── Disbursed ───────────────────────────────────────────────────────
		if (frm.doc.status === "Disbursed") {
			frm.dashboard.add_indicator(
				__("Balance: {0}", [format_currency(frm.doc.balance_amount)]),
				frm.doc.balance_amount > 0 ? "orange" : "green"
			);

			if (can_manage) {
				frm.add_custom_button(__("Cancel Loan"), () => {
					frappe.confirm(__("Cancel this disbursed loan? This will also cancel the GL entry."), () => {
						frappe.call({
							method: "loan_management.hr_loan_management.doctype.hr_loan.hr_loan.cancel_loan",
							args: { loan: frm.doc.name },
							freeze: true, callback: () => frm.reload_doc(),
						});
					});
				});

				frm.add_custom_button(__("Reschedule Remaining"), () => {
					const unpaid = (frm.doc.repayment_schedule || []).filter(r => !r.is_paid);
					if (!unpaid.length) { frappe.msgprint(__("No unpaid installments")); return; }
					frappe.confirm(
						__("Redistribute remaining balance ({0}) across {1} unpaid row(s)?",
							[format_currency(frm.doc.balance_amount), unpaid.length]),
						() => {
							frm.save().then(() => {
								frappe.call({
									method: "loan_management.hr_loan_management.doctype.hr_loan.hr_loan.reschedule",
									args: { loan: frm.doc.name },
									freeze: true, freeze_message: __("Rescheduling..."),
									callback: () => {
										frappe.show_alert({ message: __("Schedule updated"), indicator: "green" });
										frm.reload_doc();
									},
								});
							});
						}
					);
				});
			}
		}

		// ── View Ledger (for all statuses after disbursement) ───────────────
		if (["Disbursed", "Closed", "Cancelled"].includes(frm.doc.status)) {

			// Button 1: Disbursement Journal Entry
			if (frm.doc.disbursement_journal_entry) {
				frm.add_custom_button(__("Disbursement JE"), () => {
					frappe.set_route("Form", "Journal Entry", frm.doc.disbursement_journal_entry);
				}, __("View Ledger"));
			}

			// Button 2: All GL Entries for this loan
			frm.add_custom_button(__("GL Entries"), () => {
				frappe.route_options = {
					"voucher_no": frm.doc.disbursement_journal_entry || "",
					"account":    frm.doc.loan_account || "",
				};
				// Open General Ledger report filtered by this loan's reference
				frappe.set_route("query-report", "General Ledger", {
					company:         frm.doc.company,
					from_date:       frm.doc.disbursement_date || frappe.datetime.get_today(),
					to_date:         frappe.datetime.get_today(),
					account:         frm.doc.loan_account,
					party_type:      "Employee",
					party:           [frm.doc.employee],
				});
			}, __("View Ledger"));

			// Button 3: All Journal Entries referencing this loan
			frm.add_custom_button(__("All Journal Entries"), () => {
				frappe.set_route("List", "Journal Entry", {
					"accounts.reference_type": "HR Loan",
					"accounts.reference_name": frm.doc.name,
				});
			}, __("View Ledger"));
		}
	},
});

// ── Child table events ────────────────────────────────────────────────────────
frappe.ui.form.on("HR Loan Repayment Schedule", {
	total_payment(frm, cdt, cdn) { recalculate_from_row(frm, cdn); },
	payment_date(frm, cdt, cdn)  { push_dates_from_row(frm, cdn); },
});

function recalculate_from_row(frm, changed_cdn) {
	const rows       = frm.doc.repayment_schedule || [];
	const idx        = rows.findIndex(r => r.name === changed_cdn);
	if (idx === -1) return;

	const total_loan  = flt(frm.doc.loan_amount);
	const paid_total  = rows.filter(r => r.is_paid).reduce((s,r) => s + flt(r.total_payment), 0);
	const max_allowed = flt(total_loan - paid_total);

	let cur_payment   = flt(rows[idx].total_payment);
	if (cur_payment > max_allowed) {
		cur_payment = max_allowed;
		frappe.model.set_value(rows[idx].doctype, changed_cdn, "total_payment", cur_payment);
		frappe.show_alert({ message: __("Capped at remaining balance: {0}", [format_currency(max_allowed)]), indicator: "orange" });
	}

	let cumulative = 0;
	for (let i = 0; i <= idx; i++) {
		if (!rows[i].is_paid) cumulative += flt(rows[i].total_payment);
	}
	const remaining = flt(max_allowed - cumulative);

	frappe.model.set_value(rows[idx].doctype, changed_cdn, "principal_amount",    cur_payment);
	frappe.model.set_value(rows[idx].doctype, changed_cdn, "balance_loan_amount", remaining < 0 ? 0 : remaining);

	const rows_after = rows.map((r,i) => ({r,i})).filter(({r,i}) => i > idx && !r.is_paid);

	if (remaining <= 0) {
		rows_after.forEach(({r}) => {
			const grid_row = frm.fields_dict.repayment_schedule.grid.grid_rows_by_docname[r.name];
			if (grid_row) grid_row.remove();
		});
		frappe.show_alert({ message: __("Loan fully covered — extra rows removed"), indicator: "green" });
	} else if (rows_after.length > 0) {
		const next = rows_after[0].r;
		frappe.model.set_value(next.doctype, next.name, "total_payment",    remaining);
		frappe.model.set_value(next.doctype, next.name, "principal_amount",  remaining);
		frappe.model.set_value(next.doctype, next.name, "balance_loan_amount", 0);
		if (rows[idx].payment_date) {
			frappe.model.set_value(next.doctype, next.name, "payment_date",
				frappe.datetime.add_months(rows[idx].payment_date, 1));
		}
		rows_after.slice(1).forEach(({r}) => {
			frappe.model.set_value(r.doctype, r.name, "total_payment",    0);
			frappe.model.set_value(r.doctype, r.name, "principal_amount",  0);
			frappe.model.set_value(r.doctype, r.name, "balance_loan_amount", 0);
		});
	}
	frm.refresh_field("repayment_schedule");
}

function push_dates_from_row(frm, changed_cdn) {
	const rows = frm.doc.repayment_schedule || [];
	const idx  = rows.findIndex(r => r.name === changed_cdn);
	if (idx === -1) return;
	let prev_date = rows[idx].payment_date;
	for (let i = idx + 1; i < rows.length; i++) {
		if (rows[i].is_paid || !prev_date) continue;
		const next_date = frappe.datetime.add_months(prev_date, 1);
		frappe.model.set_value(rows[i].doctype, rows[i].name, "payment_date", next_date);
		prev_date = next_date;
	}
	frm.refresh_field("repayment_schedule");
}

function flt(val) { return parseFloat(val) || 0; }
