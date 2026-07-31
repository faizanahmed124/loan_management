// Copyright (c) 2026, Your Company and contributors

frappe.ui.form.on("HR Full Final Settlement", {

	refresh(frm) {
		frm.trigger("set_indicator");
		frm.trigger("add_buttons");
	},

	set_indicator(frm) {
		const colors = { Draft:"grey", Verified:"orange", Paid:"green" };
		frm.page.set_indicator(frm.doc.status, colors[frm.doc.status] || "grey");
	},

	add_buttons(frm) {
		if (frm.is_new()) return;
		const can = frappe.user.has_role("HR Manager") || frappe.user.has_role("System Manager");

		// ── Fetch All Data button (always visible in Draft/Verified) ──────────
		if (frm.doc.employee && frm.doc.status !== "Paid") {
			frm.add_custom_button(__("Fetch Loans & Leave Balance"), () => {
				if (!frm.doc.last_working_day) {
					frappe.msgprint(__("Please set Last Working Day first"));
					return;
				}
				frappe.call({
					method: "loan_management.hr_fnf_management.doctype.hr_full_final_settlement.hr_full_final_settlement.fetch_employee_data",
					args: { settlement: frm.doc.name, employee: frm.doc.employee },
					freeze: true,
					freeze_message: __("Fetching loans & leave balance..."),
					callback: (r) => {
						if (r.message) {
							frm.reload_doc();
							const d = r.message;
							frappe.show_alert({
								message: __("Fetched: {0} loan(s) | Pending: Rs {1} | Leave Balance: {2} days",
									[d.loan_count, d.total_loan_pending, d.leave_balance]),
								indicator: "green"
							});
						}
					},
				});
			}).addClass("btn-primary");
		}

		// ── Verify ────────────────────────────────────────────────────────────
		if (frm.doc.status === "Draft" && can) {
			frm.add_custom_button(__("Verify Settlement"), () => {
				frappe.confirm(__("Mark this settlement as Verified?"), () => {
					frappe.call({
						method: "loan_management.hr_fnf_management.doctype.hr_full_final_settlement.hr_full_final_settlement.verify_settlement",
						args: { settlement: frm.doc.name },
						freeze: true, callback: () => frm.reload_doc(),
					});
				});
			});
		}

		// ── Mark Paid ─────────────────────────────────────────────────────────
		if (frm.doc.status === "Verified" && can) {
			frm.add_custom_button(__("Mark as Paid"), () => {
				frappe.confirm(
					__("Mark settlement of {0} as Paid? Net Payable: Rs {1}",
						[frm.doc.employee_name, (frm.doc.net_payable || 0).toLocaleString()]),
					() => {
						frappe.call({
							method: "loan_management.hr_fnf_management.doctype.hr_full_final_settlement.hr_full_final_settlement.mark_paid",
							args: { settlement: frm.doc.name },
							freeze: true, callback: () => frm.reload_doc(),
						});
					}
				);
			}).addClass("btn-success");
		}

		if (frm.doc.status === "Paid") {
			frm.dashboard.add_indicator(
				__("Net Paid: Rs {0}", [(frm.doc.net_payable || 0).toLocaleString()]), "green"
			);
		}
	},

	// ── Auto-fetch salary when employee is selected ───────────────────────────
	employee(frm) {
		if (frm.doc.employee) {
			// Fetch CTC and Basic from employee
			frappe.db.get_value("Employee", frm.doc.employee, ["ctc", "custom_basic_pay"], (r) => {
				if (r) {
					frm.set_value("gross_salary_calc", r.ctc || 0);
					frm.set_value("basic_pay", r.custom_basic_pay || 0);
				}
			});
		}
	},

	// ── Live calculations ─────────────────────────────────────────────────────

	gross_salary_calc(frm)      { frm.trigger("recalc_all"); },
	basic_pay(frm)              { frm.trigger("recalc_bonus"); },
	settlement_date(frm)        { frm.trigger("recalc_daily_rate"); },
	working_days(frm)           { frm.trigger("recalc_current_month"); },
	leave_encashed(frm)         { frm.trigger("recalc_leave"); },
	bonus_month(frm)            { frm.trigger("recalc_bonus"); },
	last_working_day(frm)       { frm.trigger("recalc_gratuity"); },
	date_of_joining(frm)        { frm.trigger("recalc_gratuity"); },
	overtime_amount(frm)        { frm.trigger("recalc_net"); },
	notice_pay(frm)             { frm.trigger("recalc_net"); },
	other_adjustment(frm)       { frm.trigger("recalc_net"); },
	gratuity_amount(frm)        { frm.trigger("recalc_net"); },
	loan_deduction_amount(frm)  { frm.trigger("recalc_net"); },
	advance_amount(frm)         { frm.trigger("recalc_net"); },

	recalc_all(frm) {
		frm.trigger("recalc_daily_rate");
		frm.trigger("recalc_leave");
	},

	recalc_daily_rate(frm) {
		const gross = flt(frm.doc.gross_salary_calc);
		if (!gross || !frm.doc.settlement_date) return;
		const d = frappe.datetime.str_to_obj(frm.doc.settlement_date);
		const days_in_month = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
		const daily = flt(gross / days_in_month, 2);
		frm.set_value("daily_rate", daily);
		frm.trigger("recalc_current_month");
	},

	recalc_current_month(frm) {
		const daily = flt(frm.doc.daily_rate);
		const days  = flt(frm.doc.working_days);
		if (daily && days) frm.set_value("current_month_salary", flt(daily * days, 2));
		frm.trigger("recalc_net");
	},

	recalc_leave(frm) {
		const gross = flt(frm.doc.gross_salary_calc);
		const days  = flt(frm.doc.leave_encashed);
		if (gross && days) {
			// Validate: cannot encash more than available balance
			if (flt(frm.doc.leave_balance) > 0 && days > flt(frm.doc.leave_balance)) {
				frappe.show_alert({
					message: __("Warning: Leave Encashed ({0}) exceeds Available Balance ({1})",
						[days, frm.doc.leave_balance]),
					indicator: "orange"
				});
			}
			frm.set_value("leave_amount", flt(days * gross / 30, 2));
		} else {
			frm.set_value("leave_amount", 0);
		}
		frm.trigger("recalc_net");
	},

	recalc_bonus(frm) {
		const basic = flt(frm.doc.basic_pay);
		const mo    = flt(frm.doc.bonus_month);
		if (basic && mo) frm.set_value("bonus_amount", flt(basic * mo, 2));
		frm.trigger("recalc_net");
	},

	recalc_gratuity(frm) {
		if (!frm.doc.date_of_joining || !frm.doc.last_working_day) return;
		const doj  = frappe.datetime.str_to_obj(frm.doc.date_of_joining);
		const lwd  = frappe.datetime.str_to_obj(frm.doc.last_working_day);
		if (lwd <= doj) return;
		const years = flt((lwd - doj) / (365.25 * 24 * 3600 * 1000), 2);
		frm.set_value("gratuity_years", years);
		const gross = flt(frm.doc.gross_salary_calc);
		if (gross && years) frm.set_value("gratuity_amount", flt(gross * 0.8 * years, 0));
		frm.trigger("recalc_net");
	},

	recalc_net(frm) {
		const net = flt(frm.doc.current_month_salary)
			+ flt(frm.doc.leave_amount)
			+ flt(frm.doc.overtime_amount)
			+ flt(frm.doc.bonus_amount)
			+ flt(frm.doc.gratuity_amount)
			+ flt(frm.doc.notice_pay)
			+ flt(frm.doc.other_adjustment)
			- flt(frm.doc.loan_deduction_amount)
			- flt(frm.doc.advance_amount);

		frm.set_value("net_payable", flt(net, 2));
	},
});

function flt(val, precision) {
	const v = parseFloat(val) || 0;
	return precision !== undefined ? parseFloat(v.toFixed(precision)) : v;
}
