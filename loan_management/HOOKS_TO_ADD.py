# =============================================================================
# ADD THESE LINES to the hooks.py that `bench new-app loan_management` generated
# for you at: apps/loan_management/loan_management/hooks.py
#
# Do NOT replace the whole file — it already has app_name, app_title, app_publisher
# etc. filled in correctly from your prompts. Just paste the blocks below into it
# (anywhere at the top level of the file).
# =============================================================================

# -----------------------------------------------------------------------------
# 1. Required apps - tells bench this app depends on HRMS being installed first
# -----------------------------------------------------------------------------
required_apps = ["hrms"]

# -----------------------------------------------------------------------------
# 2. Runs once, right after `bench --site [sitename] install-app loan_management`
#    Creates the "Loan Repayment" Salary Component used for payroll deductions.
# -----------------------------------------------------------------------------
after_install = "loan_management.loan_management.install.after_install"

# -----------------------------------------------------------------------------
# 3. Document event hooks - this is what wires Loans into Payroll automatically
# -----------------------------------------------------------------------------
doc_events = {
	"Salary Slip": {
		"validate": "loan_management.loan_management.utils.add_loan_deductions",
		"on_submit": "loan_management.loan_management.utils.mark_loan_repayments_paid",
		"on_cancel": "loan_management.loan_management.utils.unmark_loan_repayments_paid",
	}
}
