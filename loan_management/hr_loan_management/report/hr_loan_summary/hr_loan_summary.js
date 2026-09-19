// Copyright (c) 2026, Your Company and contributors
// For license information, please see license.txt

frappe.query_reports["HR Loan Summary"] = {
	filters: [
		{
			fieldname:  "company",
			label:      __("Company"),
			fieldtype:  "Link",
			options:    "Company",
			default:    frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "employee",
			label:     __("Employee"),
			fieldtype: "Link",
			options:   "Employee",
		},
		{
			fieldname: "department",
			label:     __("Department"),
			fieldtype: "Link",
			options:   "Department",
		},
		{
			fieldname: "loan_type",
			label:     __("Loan Type"),
			fieldtype: "Link",
			options:   "HR Loan Type",
		},
		{
			fieldname: "loan_source",
			label:     __("Repayment Source"),
			fieldtype: "Select",
			options:   "\nSalary\nBonus\nGratuity",
		},
		{
			fieldname: "status",
			label:     __("Status"),
			fieldtype: "Select",
			options:   "\nSanctioned\nDisbursed\nClosed\nCancelled",
		},
		{
			fieldname:  "from_date",
			label:      __("Disbursement From"),
			fieldtype:  "Date",
		},
		{
			fieldname: "to_date",
			label:     __("Disbursement To"),
			fieldtype: "Date",
			default:   frappe.datetime.get_today(),
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (column.fieldname === "status") {
			const colors = {
				"Disbursed":  "blue",
				"Closed":     "green",
				"Sanctioned": "orange",
				"Cancelled":  "red",
			};
			const color = colors[data.status] || "grey";
			value = `<span class="badge" style="background:${colorMap(color)};color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;">${data.status}</span>`;
		}

		if (column.fieldname === "balance_amount" && data.balance_amount > 0) {
			value = `<span style="color:#8B1A1A;font-weight:600;">${value}</span>`;
		}

		if (column.fieldname === "balance_amount" && data.status === "Closed") {
			value = `<span style="color:#27ae60;font-weight:600;">Cleared</span>`;
		}

		if (column.fieldname === "pending_installments" && data.pending_installments > 0) {
			value = `<span style="color:#e67e22;font-weight:600;">${data.pending_installments}</span>`;
		}

		return value;
	},

	onload(report) {
		report.page.add_inner_button(__("Export to Excel"), () => {
			report.export_report("xlsx");
		});
	},
};

function colorMap(name) {
	return {
		blue:   "#1a6ebd",
		green:  "#27ae60",
		orange: "#e67e22",
		red:    "#8B1A1A",
		grey:   "#888",
	}[name] || "#888";
}
