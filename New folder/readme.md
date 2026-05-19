# Gym 4 U Membership Platform

A Flask web application that lets users compare membership pricing across two gyms (uGym and Power Zone), choose a plan, create an account, complete payment simulation, and manage/renew subscriptions.

This README documents the full project structure, backend workflow, and pricing/business logic in detail.

Recent UI work in this version includes:

- A ClassPass-inspired homepage refresh with a light blue and charcoal palette.
- A redesigned member dashboard with clearer subscription cards, countdown, and BMI panel.
- Page-specific styling for Join Now, Login, and Manage Memberships.
- A reusable delete-account confirmation modal in the global layout.

## 1) Project Overview

The platform supports two main journeys:

1. New member checkout flow.
2. Existing member account management flow.

At a high level:

1. User compares plans in the calculator.
2. User selects one gym.
3. User enters identity and password.
4. User completes payment validation.
5. Membership is activated and visible in account dashboard.

For existing users:

1. User logs in.
2. User can renew membership (only when remaining days is 0).
3. User can update gym/access/add-ons (also only when remaining days is 0), then must pay again to activate updates.

## 2) Tech Stack

- Backend framework: Flask
- Database ORM: Flask-SQLAlchemy (SQLAlchemy)
- Database: MySQL
- Database administration tool: MySQL Workbench
- Auth: session-based login with Werkzeug password hashing
- Frontend: Jinja templates + CSS + small inline JavaScript helpers

Additional runtime dependencies used by the current code:

- PyMySQL for MySQL connectivity
- python-dotenv for loading environment variables from .env

## 3) Repository Structure

Top-level files and folders:

- app.py
- models.py
- readme.md
- templates/
- static/
- instance/
- __pycache__/

Detailed breakdown:

### app.py

Main Flask application file:

- App configuration and database initialization.
- Database bootstrap (seed membership plans and discount rules on first run).
- Core helper functions:
	- generate_membership_id()
	- determine_status_from_age()
	- calculate_gym_cost()
	- get_member_subscription_data()
	- sync_subscription_status()
- Route definitions for full web flow:
	- /, /calculator, /select-gym, /member-details, /confirm-pay
	- /login, /logout, /account
	- /manage-addons, /renew-membership, /cancel-membership, /delete-account

### models.py

Defines SQLAlchemy models:

- Member: user account + subscription state.
- MembershipPlan: price matrix per gym and plan type.
- DiscountRule: discount percentages and discountable add-ons per user status.

Also contains password helpers:

- set_password(password)
- check_password(password)

### templates/

Jinja templates for all pages:

- base.html: common layout, nav, footer, account dropdown, and delete-account modal.
- index.html: home/marketing page with refreshed hero and section styling.
- calculator.html: Join Now flow form (age, student flag, access tier, add-ons).
- results.html: side-by-side gym pricing comparison and gym selection.
- member_details.html: identity + password step.
- confirm_pay.html: payment input and confirmation step.
- login.html: member login page.
- account.html: member dashboard with subscription summary, countdown, BMI health check, and account actions.
- manage_addons.html: post-expiry membership update flow.

### static/

- styles.css: global visual styles.
- Images used across home, calculator, and membership pages.

### instance/

Runtime instance data location used by Flask ecosystem patterns. In this documentation, the project database stack is MySQL and can be managed via MySQL Workbench.

## 4) Data Model and Storage

### 4.1 Member Table

The Member model stores identity, credentials, and subscription state:

- id (PK)
- name
- age
- is_student
- email (unique)
- password_hash
- membership_id (unique, generated after checkout)
- subscription_status (active/inactive)
- subscription_starts_at
- subscription_ends_at
- next_billing_at
- membership_plan_id (FK to membership_plans.id)
- has_classes
- has_swimming_pool
- has_massage
- has_physiotherapy

Important behavior:

- Passwords are hashed, never stored in plain text.
- Selected add-ons are persisted as boolean flags on the Member record.
- The active gym/access tier is resolved through the MembershipPlan relationship.

### 4.2 MembershipPlan Table

Pricing matrix for each gym and plan:

- gym_name (uGym / Power Zone)
- plan_type (Joining Fee, Gym tiers, add-ons)
- price_no_gym
- price_with_gym

Constraints/indexing:

- UniqueConstraint(gym_name, plan_type)
- Index(gym_name, plan_type)

### 4.3 DiscountRule Table

Discount policy per gym and status:

- gym_name
- status (student/pensioner/young/regular)
- discount_rate (example: 0.20)

Constraints/indexing:

- UniqueConstraint(gym_name, status)
- Index(gym_name, status)

Important behavior:

- Discount rates are stored as decimals in the database (for example 0.20).
- The UI displays discounts as percentages where relevant (for example 20%).
- If no discount applies, discount text is omitted from the templates instead of showing 0%.

## 5) Startup and Seed Logic

On startup inside app context:

1. db.create_all() creates missing tables.
2. If no MembershipPlan rows exist, all gym plans/add-ons are seeded.
3. If no DiscountRule rows exist, discount policies are seeded.

This means first run auto-initializes core business data without a separate migration script.

## 6) Business Logic (Core Rules)

### 6.1 Status Classification

determine_status_from_age(age, is_student):

- age >= 66 -> pensioner
- is_student true -> student
- age 16..25 -> young
- otherwise -> regular

This status drives discount selection.

### 6.2 Price Calculation

calculate_gym_cost(gym_name, gym_type, addons, age, is_student) computes:

1. Membership status.
2. Required plan rows only (optimized DB fetch).
3. Gym + status discount rule.
4. Subtotal, discount amount, final total.

Key logic:

- Joining fee uses price_no_gym by design (same regardless of gym access selection).
- Gym plan cost applies only when gym_type is not none.
- Add-on cost uses:
	- price_with_gym if member selected gym access
	- price_no_gym if member selected no gym access
- Discount applies to:
	- base gym cost
	- plus only add-ons listed in discountable_addons for that gym/status

Pricing equations:

- subtotal = joining_fee + gym_cost + addon_cost
- discount_amount = discountable_amount * discount_rate
- total_cost = subtotal - discount_amount

### 6.3 Subscription State Synchronization

sync_subscription_status(member):

- If member is active and now >= subscription_ends_at, status is switched to inactive and next_billing_at is cleared.

This function is called on account and membership management routes to keep status accurate over time.

## 7) Route Map and Workflow

### Public / Entry Routes

- GET / -> Home page.
- GET|POST /calculator -> Collect user options and compute comparison.

### New Membership Checkout Flow

1. POST /calculator
	 - Validates age, gym type, and minimum selection requirement.
	 - Computes cost for both gyms.
	 - Stores pending_membership in session.
	 - Renders results page.

2. POST /select-gym
	 - Validates selected gym.
	 - Saves selected_gym into pending_membership.
	 - Redirects to /member-details.

3. GET|POST /member-details
	 - Requires pending_membership in session.
	 - Validates name, email format, password rules, duplicate email behavior.
	 - Creates Member record if needed.
	 - Stores pending_member in session.
	 - Redirects to /confirm-pay.

4. GET|POST /confirm-pay
	 - Handles three payment contexts:
		 - New checkout
		 - Renew membership
		 - Manage membership updates
	 - Validates payment fields (card number, CVV, expiry format and date, postcode length).
	 - On success, activates/updates subscription dates and status.
	 - Clears pending session states.
	 - Redirects to /account.

### Existing Member Auth / Account

- GET|POST /login -> authenticates via email/password.
- GET|POST /logout -> clears session.
- GET /account -> dashboard with subscription details and countdown metrics.

### Membership Lifecycle Management

- POST /renew-membership
	- Allowed only for logged-in members.
	- Requires current cycle to be fully ended (remaining_days == 0).
	- Sets pending_renew_membership in session.
	- Redirects to /confirm-pay for payment.

- GET|POST /manage-addons
	- Allowed only for logged-in members.
	- Also requires remaining_days == 0.
	- Lets member change gym/access/add-ons.
	- Saves pending_manage_membership in session.
	- Redirects to /confirm-pay.

- POST /cancel-membership
	- Allowed only for logged-in members.
	- Clears current gym plan, add-ons, and billing dates.
	- Returns the user to an inactive dashboard state.

- POST /delete-account
	- Allowed only for logged-in members.
	- Deletes the current member record and clears the session.
	- Triggered from the shared delete-account modal in the UI.

Important architectural rule:

- Membership activation does not happen directly in /manage-addons or /renew-membership.
- Activation happens only in /confirm-pay after payment validation succeeds.

## 8) Session State Design

The app uses Flask session storage to carry multi-step checkout data.

Primary keys:

- user_id: authenticated member ID.
- pending_membership: calculator selections before profile/payment completion.
- pending_member: name/email entered at member details step.
- pending_manage_membership: staged membership changes awaiting payment.
- pending_renew_membership: staged renewal awaiting payment.

Why this matters:

- Enables clean, step-based UX.
- Prevents partial activation before payment step.
- Supports three payment entry points through one unified confirmation route.

## 9) Validation and Security Notes

### Input Validation

Server-side validation exists for:

- Age and membership form consistency.
- Selected gym/access values.
- Name/email/password rules.
- Payment field format and expiry.

Some templates also include client-side JavaScript validation for better UX, but backend validation remains authoritative.

### Password Security

- Passwords are hashed with Werkzeug utilities.
- Login verifies using hash comparison.

### Session Security

- App uses SECRET_KEY from environment when available.
- In development, the fallback secret key is randomized on each server start.
- This intentionally invalidates stale browser sessions between restarts so old login cookies do not persist unexpectedly.
- In production, a stable SECRET_KEY must be provided through environment variables.

## 10) Frontend Workflow by Template

Page responsibilities:

- index.html: awareness and CTA into calculator flow, using the refreshed marketing layout.
- calculator.html: Join Now selection inputs and submission.
- results.html: pricing comparison and gym decision.
- member_details.html: account details capture.
- confirm_pay.html: payment completion and final activation trigger.
- login.html: returning member access.
- account.html: status visibility, cycle metrics, BMI health check, account deletion trigger, and lifecycle actions.
- manage_addons.html: post-cycle membership reconfiguration with page-specific styling and payment handoff.

Shared frontend behavior in base.html:

- Fixed navigation with guest/member-aware options.
- Account dropdown for logged-in members.
- Shared footer.
- Delete-account confirmation modal with close button, warning icon, cancel action, and destructive confirm action.

## 11) How to Run Locally

### Prerequisites

- Python 3.10+ recommended.
- Virtual environment (already present in this workspace as .venv).

### Install dependencies

If needed:

1. Activate virtual environment.
2. Install Flask, Flask-SQLAlchemy, PyMySQL, and python-dotenv.

Example commands on Windows PowerShell:

1. .\.venv\Scripts\Activate.ps1
2. pip install flask flask-sqlalchemy pymysql python-dotenv

### Start app

Run:

1. python app.py

Then open:

- http://127.0.0.1:5000

## 12) Typical End-to-End Scenario

Example new user journey:

1. Visit home page.
2. Go to calculator and choose age/access/add-ons.
3. Compare prices and select either uGym or Power Zone.
4. Enter full name, email, password.
5. Enter payment details and submit.
6. Membership ID is ensured, subscription marked active for 30 days.
7. User lands on account page with remaining days and cycle indicators.

After cycle ends:

1. User can renew via /renew-membership (payment required).
2. Or update gym/add-ons via /manage-addons (payment required).

## 13) Notes for Future Improvements

Potential enhancements:

- Add migrations (Flask-Migrate) instead of startup-only seeding checks.
- Move payment simulation to real provider integration.
- Add automated tests for helper pricing logic and route workflows.
- Add CSRF protection and production-grade session/cookie hardening.

