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

		if (frm.doc.status === "Sanctioned" && can_manage) {
			frm.add_custom_button(__("Disburse Loan"), () => {
				frappe.prompt([{
					fieldname: "disbursement_date", label: __("Disbursement Date"),
					fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1,
				}], (values) => {
					frappe.call({
						method: "loan_management.hr_loan_management.doctype.hr_loan.hr_loan.disburse",
						args: { loan: frm.doc.name, disbursement_date: values.disbursement_date },
						freeze: true, freeze_message: __("Disbursing..."),
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

		if (frm.doc.status === "Disbursed") {
			frm.dashboard.add_indicator(
				__("Balance: {0}", [format_currency(frm.doc.balance_amount)]),
				frm.doc.balance_amount > 0 ? "orange" : "green"
			);

			if (can_manage) {
				frm.add_custom_button(__("Reschedule Remaining"), () => {
					frm.save().then(() => {
						frappe.call({
							method: "loan_management.hr_loan_management.doctype.hr_loan.hr_loan.reschedule",
							args: { loan: frm.doc.name },
							freeze: true, freeze_message: __("Rescheduling..."),
							callback: (r) => {
								frappe.show_alert({ message: __("Schedule updated"), indicator: "green" });
								frm.reload_doc();
							},
						});
					});
				});
			}
		}
	},
});

// ── Child table events ───────────────────────────────────────────────────────
frappe.ui.form.on("HR Loan Repayment Schedule", {
	total_payment(frm, cdt, cdn) {
		recalculate_from_row(frm, cdn);
	},
	payment_date(frm, cdt, cdn) {
		push_dates_from_row(frm, cdn);
	},
});

function recalculate_from_row(frm, changed_cdn) {
	const rows        = frm.doc.repayment_schedule || [];
	const idx         = rows.findIndex(r => r.name === changed_cdn);
	if (idx === -1) return;

	const total_loan  = flt(frm.doc.loan_amount);
	const paid_total  = rows.filter(r => r.is_paid).reduce((s, r) => s + flt(r.total_payment), 0);
	const max_allowed = flt(total_loan - paid_total);

	// Cap current row at max allowed
	let cur_payment = flt(rows[idx].total_payment);
	if (cur_payment > max_allowed) {
		cur_payment = max_allowed;
		frappe.model.set_value(cdt, changed_cdn, "total_payment", cur_payment);
		frappe.show_alert({ message: __("Amount capped at remaining balance: {0}", [format_currency(max_allowed)]), indicator: "orange" });
	}

	// Cumulative unpaid sum up to and including changed row
	let cumulative = 0;
	for (let i = 0; i <= idx; i++) {
		if (!rows[i].is_paid) cumulative += flt(rows[i].total_payment);
	}

	const remaining = flt(max_allowed - cumulative);

	// Update principal + balance of changed row
	frappe.model.set_value(cdt, changed_cdn, "principal_amount", cur_payment);
	frappe.model.set_value(cdt, changed_cdn, "balance_loan_amount", remaining < 0 ? 0 : remaining);

	// Handle rows AFTER the changed one
	const rows_after_unpaid = rows
		.map((r, i) => ({ r, i }))
		.filter(({ r, i }) => i > idx && !r.is_paid);

	if (remaining <= 0) {
		// Loan fully covered — delete all subsequent unpaid rows
		rows_after_unpaid.forEach(({ r }) => {
			frm.get_field("repayment_schedule").grid.get_row(r.name) &&
			frm.fields_dict.repayment_schedule.grid.grid_rows_by_docname[r.name] &&
			frm.fields_dict.repayment_schedule.grid.grid_rows_by_docname[r.name].remove();
		});
		frappe.show_alert({ message: __("Loan fully covered — extra rows removed"), indicator: "green" });
	} else if (rows_after_unpaid.length > 0) {
		// Push remaining to next unpaid row
		const next = rows_after_unpaid[0].r;
		frappe.model.set_value(next.doctype, next.name, "total_payment",    remaining);
		frappe.model.set_value(next.doctype, next.name, "principal_amount",  remaining);
		frappe.model.set_value(next.doctype, next.name, "balance_loan_amount", 0);

		// Auto-date: next row = current row date + 1 month
		if (rows[idx].payment_date) {
			frappe.model.set_value(next.doctype, next.name, "payment_date",
				frappe.datetime.add_months(rows[idx].payment_date, 1));
		}

		// Zero out any rows further down
		rows_after_unpaid.slice(1).forEach(({ r }) => {
			frappe.model.set_value(r.doctype, r.name, "total_payment", 0);
			frappe.model.set_value(r.doctype, r.name, "principal_amount", 0);
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
