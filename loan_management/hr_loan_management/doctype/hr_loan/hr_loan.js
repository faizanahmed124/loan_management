// Copyright (c) 2026, Your Company and contributors

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
		const can = frappe.user.has_role("HR Manager") || frappe.user.has_role("System Manager");

		if (frm.doc.status === "Sanctioned" && can) {
			frm.add_custom_button(__("Disburse Loan"), () => {
				frappe.prompt([{ fieldname:"disbursement_date", label:__("Disbursement Date"), fieldtype:"Date", default:frappe.datetime.get_today(), reqd:1 }],
				(v) => {
					frappe.call({
						method: "loan_management.hr_loan_management.doctype.hr_loan.hr_loan.disburse",
						args: { loan: frm.doc.name, disbursement_date: v.disbursement_date },
						freeze: true, freeze_message: __("Disbursing & creating GL entry..."),
						callback: () => frm.reload_doc(),
					});
				}, __("Disburse Loan"), __("Disburse"));
			}).addClass("btn-primary");

			frm.add_custom_button(__("Cancel Loan"), () => {
				frappe.confirm(__("Cancel this loan?"), () => {
					frappe.call({ method:"loan_management.hr_loan_management.doctype.hr_loan.hr_loan.cancel_loan", args:{loan:frm.doc.name}, freeze:true, callback:()=>frm.reload_doc() });
				});
			});
		}

		if (frm.doc.status === "Disbursed") {
			frm.dashboard.add_indicator(__("Balance: {0}",[format_currency(frm.doc.balance_amount)]), frm.doc.balance_amount > 0 ? "orange" : "green");

			if (can) {
				frm.add_custom_button(__("Cancel Loan"), () => {
					frappe.confirm(__("Cancel this disbursed loan? GL entry will also be cancelled."), () => {
						frappe.call({ method:"loan_management.hr_loan_management.doctype.hr_loan.hr_loan.cancel_loan", args:{loan:frm.doc.name}, freeze:true, callback:()=>frm.reload_doc() });
					});
				});
			}
		}

		if (["Disbursed","Closed","Cancelled"].includes(frm.doc.status)) {
			if (frm.doc.disbursement_journal_entry) {
				frm.add_custom_button(__("Disbursement JE"), () => frappe.set_route("Form","Journal Entry",frm.doc.disbursement_journal_entry), __("View Ledger"));
			}
			frm.add_custom_button(__("GL Entries"), () => {
				frappe.set_route("query-report","General Ledger",{ company:frm.doc.company, from_date:frm.doc.disbursement_date||frappe.datetime.get_today(), to_date:frappe.datetime.get_today(), account:frm.doc.loan_account, party_type:"Employee", party:[frm.doc.employee] });
			}, __("View Ledger"));
			frm.add_custom_button(__("All Journal Entries"), () => {
				frappe.set_route("List","Journal Entry",{"accounts.reference_type":"HR Loan","accounts.reference_name":frm.doc.name});
			}, __("View Ledger"));
		}
	},
});

// ── Child table: auto-recalculate when amount or date changes ────────────────

let _recalc_timer = null;

frappe.ui.form.on("HR Loan Repayment Schedule", {
	total_payment(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.is_paid) return;

		// Debounce 800ms so user can finish typing
		clearTimeout(_recalc_timer);
		_recalc_timer = setTimeout(() => {
			const new_amount = flt(row.total_payment);
			if (new_amount < 0) return;

			frappe.show_alert({ message: __("Recalculating schedule..."), indicator: "blue" });

			frappe.call({
				method: "loan_management.hr_loan_management.doctype.hr_loan.hr_loan.recalculate_schedule_from_row",
				args: {
					loan:       frm.doc.name,
					row_name:   cdn,
					new_amount: new_amount,
				},
				freeze: false,
				callback: (r) => {
					if (r.message) {
						frm.reload_doc();
						frappe.show_alert({ message: __("Schedule updated automatically"), indicator: "green" });
					}
				},
				error: (r) => {
					frappe.show_alert({ message: __("Recalculation failed — save manually and retry"), indicator: "red" });
				}
			});
		}, 800);
	},

	payment_date(frm, cdt, cdn) {
		push_dates_from_row(frm, cdn);
	},
});

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