from flask import Flask, render_template, request, redirect, url_for, session, flash
# app.py - Main Flask application file for Gym Membership Calculator
import os
import re
from datetime import datetime, timedelta
# We use uuid4 to generate unique membership IDs for users when they subscribe.
from uuid import uuid4
from models import db, MembershipPlan, DiscountRule, Member
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file


DISCOUNTABLE_ADDONS = {"Swimming Pool", "Classes"}


def selected_addons_from_member(member):
    selected_addons = []
    if member.has_classes:
        selected_addons.append('Classes')
    if member.has_swimming_pool:
        selected_addons.append('Swimming Pool')
    if member.has_massage:
        selected_addons.append('Massage')
    if member.has_physiotherapy:
        selected_addons.append('Physiotherapy')
    return selected_addons


def assign_member_addons(member, selected_addons):
    selected_addons = selected_addons or []
    member.has_classes = 'Classes' in selected_addons
    member.has_swimming_pool = 'Swimming Pool' in selected_addons
    member.has_massage = 'Massage' in selected_addons
    member.has_physiotherapy = 'Physiotherapy' in selected_addons


# app initialization
app = Flask(__name__)

# In production, set SECRET_KEY in environment.
# Dev fallback is randomized per process start so old browser sessions are invalidated
# when the server restarts (prevents appearing "already logged in" from stale cookies).
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or os.urandom(32).hex()

# --- Database setup ---
# Pull the values using os.environ.get
user = os.environ.get('DB_USERNAME')
password = os.environ.get('DB_PASSWORD')
host = os.environ.get('DB_HOST')
database = os.environ.get('DB_NAME')

app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{user}:{password}@{host}/{database}'

# This turns off extra tracking that is not needed and avoids warnings.
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# This connects the db object from models.py to this Flask app.
db.init_app(app)


# This function generates a unique membership ID for a subscribed user. It creates a candidate ID using a UUID, checks if it already exists in the database, and if not, returns it.
# This ensures that every member gets a unique membership ID.
def generate_membership_id():
    """Generate a unique membership ID for a subscribed user."""
    # We loop until we find a unique ID that doesn't exist in the database.
    while True:
        # We use uuid4 to generate a random UUID, take the first 10 characters of its hex representation, convert to uppercase, and prefix with "G4U-". This creates a membership ID like "G4U-1A2B3C4D5E".
        candidate = f"G4U-{uuid4().hex[:10].upper()}"
        # Check if this candidate ID already exists in the database. If it does, we loop again to generate a new one. If it doesn't exist, we return it as the new membership ID.
        exists = Member.query.filter_by(membership_id=candidate).first()
        if not exists:
            return candidate


# This function prepares the member's subscription data for display in the account page.
def get_member_subscription_data(member):
    addons = selected_addons_from_member(member)
    # We extract the subscription dates from the member object.
    starts_at = member.subscription_starts_at
    ends_at = member.subscription_ends_at
    next_billing_at = member.next_billing_at 
    # Calculate remaining days until subscription ends, if ends_at is set. We add 1 day if there are any remaining seconds to count partial days as a full day for user-friendly display.
    remaining_days = 0

    if ends_at:
        # Get the time difference between now and the membership end date.
        delta = ends_at - datetime.utcnow()
        # Using the max function we ensure that we never return a negative number of remaining days, which could happen if the subscription has already expired. Instead, we return 0 in that case.
        # If there are extra hours/minutes/seconds beyond whole days, add 1 day so partial day counts as a full day for display.
        remaining_days = max(0, delta.days + (1 if delta.seconds > 0 else 0))

    membership_plan = member.membership_plan if member.membership_plan else None
    # Finally, we return a dictionary containing all the relevant member and subscription information that the account.html template will use to display the user's subscription details and status.
    return {
        'member_name': member.name,
        'member_email': member.email,
        'age': member.age,
        'is_student': bool(member.is_student),
        'membership_id': member.membership_id or 'Pending',
        'gym_type': membership_plan.plan_type if membership_plan else 'No Gym Access',
        'addons': addons,
        'addon_count': len(addons),
        'has_classes': member.has_classes,
        'has_swimming_pool': member.has_swimming_pool,
        'has_massage': member.has_massage,
        'has_physiotherapy': member.has_physiotherapy,
        'subscription_status': member.subscription_status or 'inactive',
        'starts_at': starts_at.isoformat() if starts_at else None,
        'ends_at': ends_at.isoformat() if ends_at else None,
        'next_billing_at': next_billing_at.isoformat() if next_billing_at else None,
        'starts_at_label': starts_at.strftime('%Y-%m-%d') if starts_at else 'Not started',
        'ends_at_label': ends_at.strftime('%Y-%m-%d') if ends_at else 'Not set',
        'next_billing_label': next_billing_at.strftime('%Y-%m-%d') if next_billing_at else 'Not set',
        'remaining_days': remaining_days
    }


def sync_subscription_status(member):
    """Mark subscriptions inactive when the paid cycle has ended."""
    if (
        member.subscription_status == 'active'
        and member.subscription_ends_at
        and datetime.utcnow() >= member.subscription_ends_at
    ):
        member.subscription_status = 'inactive'
        member.next_billing_at = None
        return True
    return False


def auto_renew_subscription(member):
    """Auto-renew only for members who have completed at least one paid cycle."""
    if (
        member.subscription_status == 'inactive'
        and member.subscription_starts_at
        and member.subscription_ends_at
        and datetime.utcnow() >= member.subscription_ends_at
    ):
        starts_at = datetime.utcnow()
        ends_at = starts_at + timedelta(days=30)
        member.subscription_status = 'active'
        member.subscription_starts_at = starts_at
        member.subscription_ends_at = ends_at
        member.next_billing_at = ends_at
        return True
    return False


# This creates database tables (Member, MembershipPlan, DiscountRule) if they don't exist yet.
with app.app_context():
    db.create_all()

    # Check if data already exists
    if MembershipPlan.query.first() is None:
        # Add uGym plans
        ugym_plans = [
            # NOTE: joining fee uses price_no_gym intentionally — it is the same regardless of whether a gym plan is selected.
            MembershipPlan(gym_name='uGym', plan_type='Joining Fee', price_no_gym=10, price_with_gym=10),
            MembershipPlan(gym_name='uGym', plan_type='Gym: Super-off peak', price_no_gym=16, price_with_gym=16),
            MembershipPlan(gym_name='uGym', plan_type='Gym: Off-peak', price_no_gym=21, price_with_gym=21),
            MembershipPlan(gym_name='uGym', plan_type='Gym: Anytime', price_no_gym=30, price_with_gym=30),
            MembershipPlan(gym_name='uGym', plan_type='Swimming Pool', price_no_gym=25, price_with_gym=15),
            MembershipPlan(gym_name='uGym', plan_type='Classes', price_no_gym=20, price_with_gym=10),
            MembershipPlan(gym_name='uGym', plan_type='Massage', price_no_gym=30, price_with_gym=25),
            MembershipPlan(gym_name='uGym', plan_type='Physiotherapy', price_no_gym=25, price_with_gym=20),
        ]

        # Add Power Zone plans
        power_zone_plans = [
            MembershipPlan(gym_name='Power Zone', plan_type='Joining Fee', price_no_gym=30, price_with_gym=30),
            MembershipPlan(gym_name='Power Zone', plan_type='Gym: Super-off peak', price_no_gym=13, price_with_gym=13),
            MembershipPlan(gym_name='Power Zone', plan_type='Gym: Off-peak', price_no_gym=19, price_with_gym=19),
            MembershipPlan(gym_name='Power Zone', plan_type='Gym: Anytime', price_no_gym=24, price_with_gym=24),
            MembershipPlan(gym_name='Power Zone', plan_type='Swimming Pool', price_no_gym=20, price_with_gym=12.5),
            MembershipPlan(gym_name='Power Zone', plan_type='Classes', price_no_gym=20, price_with_gym=0),
            MembershipPlan(gym_name='Power Zone', plan_type='Massage', price_no_gym=30, price_with_gym=25),
            MembershipPlan(gym_name='Power Zone', plan_type='Physiotherapy', price_no_gym=30, price_with_gym=25),
        ]

        db.session.add_all(ugym_plans + power_zone_plans)
        db.session.commit()
        print("✓ Database initialized with membership plans")

    if DiscountRule.query.first() is None:
        discount_rules = [
            DiscountRule(gym_name='uGym', status='student', discount_rate=0.20),
            DiscountRule(gym_name='uGym', status='pensioner', discount_rate=0.15),
            DiscountRule(gym_name='uGym', status='young', discount_rate=0.20),
            DiscountRule(gym_name='uGym', status='regular', discount_rate=0.0),
            DiscountRule(gym_name='Power Zone', status='student', discount_rate=0.15),
            DiscountRule(gym_name='Power Zone', status='pensioner', discount_rate=0.20),
            DiscountRule(gym_name='Power Zone', status='young', discount_rate=0.15),
            DiscountRule(gym_name='Power Zone', status='regular', discount_rate=0.0),
        ]
        # We add all the discount rules to the database session and commit them, which saves them to the database.
        db.session.add_all(discount_rules)
        db.session.commit()
        print("✓ Database initialized with discount rules")


# =========== HELPER FUNCTIONS =================
# This function assigns the user a status based on his age and student flag, later used in discounts
def determine_status_from_age(age, is_student=False):
    """Map age/student flag to membership status for discounts."""
    if age >= 66:
        return 'pensioner'
    if is_student:
        return 'student'
    if 16 <= age <= 25:
        return 'young'
    return 'regular'


# This function calculates the total price based on the selected plan, addons, and applicable discounts
def calculate_gym_cost(gym_name, gym_type, addons, age, is_student=False):

    applicable_statuses = []
    if age >= 66:
        applicable_statuses.append('pensioner')
    if is_student:
        applicable_statuses.append('student')
    if not applicable_statuses:
        applicable_statuses.append(determine_status_from_age(age, is_student))

    status = applicable_statuses[0]  # default; overridden below once best rule is found
    # We determine if the user has selected a gym plan (not 'none') to know if gym-related pricing rules apply.
    has_gym = gym_type != 'none'

    # The addons variable is expected to be a list of selected add-on names.
    # If it's not provided we default it to an empty list to avoid errors in later processing.
    addons = addons or []

    # gym_type now comes from the form already matching DB plan_type names.
    # If user selected "none", there is no gym plan row to fetch.
    gym_plan_name = None if gym_type == 'none' else gym_type

    # Build list of required plans to minimize database load.
    # Why: Instead of loading every row from membership_plans,
    # we fetch only the exact rows used in this calculation.
    needed_plans = ['Joining Fee']
    if gym_plan_name:
        needed_plans.append(gym_plan_name)
    if addons:
        needed_plans.extend(addons)

    # Query the DB for this gym and these selected plan names.
    # Example filter result rows: Joining Fee, Gym: Off-peak, Swimming Pool...
    plans = MembershipPlan.query.filter(
        MembershipPlan.gym_name == gym_name,
        MembershipPlan.plan_type.in_(needed_plans)
    ).all()

    # Convert list to dict for fast lookup by plan_type.
    # Example: plans_dict['Joining Fee'] gives that row directly.
    plans_dict = {plan.plan_type: plan for plan in plans}

    # if a gym plan was selected AND it's missing from the database, raise an error
    # instead of silently setting gym_cost to 0 (which would show a wrong price).
    if gym_plan_name and gym_plan_name not in plans_dict:
        raise ValueError(f"Plan '{gym_plan_name}' not found for gym '{gym_name}'")

    # Base prices:
    # joining_fee: always considered if row exists.
    #   NOTE: joining fee uses price_no_gym intentionally, it is the same
    #   regardless of whether a gym plan is selected.
    # gym_cost: only if a gym option was selected (not 'none').
    joining_fee = plans_dict['Joining Fee'].price_no_gym if 'Joining Fee' in plans_dict else 0
    gym_cost = plans_dict[gym_plan_name].price_no_gym if gym_plan_name else 0

    # Load discount rules for all applicable statuses, then pick the one with the highest rate.
    # This handles the case where a user is both a pensioner and a student.
    candidate_rules = DiscountRule.query.filter(
        DiscountRule.gym_name == gym_name,
        DiscountRule.status.in_(applicable_statuses)
    ).all()
    rule = max(candidate_rules, key=lambda r: r.discount_rate) if candidate_rules else None
    # lambda function is a small anonymous function that takes a rule and returns its discount_rate, 
    # used here to find the rule with the highest discount rate among the candidates.
    if rule:
        status = rule.status

    # Extract discount details:
    # - discount_rate is a decimal (0.20 = 20%)
    # - discountable_addons uses a shared application-level constant.
    discount_rate = rule.discount_rate if rule else 0
    discountable_addons = DISCOUNTABLE_ADDONS

    # Add-on cost accumulation in one pass.
    # We compute:
    # addon_cost: total add-on money before discount
    # addon_breakdown: list for display
    # discountable_amount: part of total where discount can apply
    addon_cost = 0
    discountable_amount = gym_cost
    addon_breakdown = []

    for addon in addons:
        if addon in plans_dict:
            plan = plans_dict[addon]
            cost = plan.price_with_gym if has_gym else plan.price_no_gym

            addon_cost += cost
            addon_breakdown.append((addon, cost))

            # Only some add-ons are eligible for discount,
            # based on the DISCOUNTABLE_ADDONS constant.
            if addon in discountable_addons:
                discountable_amount += cost

    # Final pricing formulas:
    # For monthly billing, joining fee is a one-time charge and should not be
    # included in the recurring subtotal/total. We therefore compute the
    # monthly subtotal (gym + addons) and the total after discount based on
    # the monthly subtotal. The joining fee remains available separately
    # for initial payment display.
    subtotal = gym_cost + addon_cost
    discount_amount = discountable_amount * discount_rate
    total_cost = subtotal - discount_amount

    return {
        'joining_fee': joining_fee,
        'gym_cost': gym_cost,
        'gym_type_name': gym_type if gym_type != 'none' else 'No Gym Access',
        'addon_cost': addon_cost,
        'addon_breakdown': addon_breakdown,
        'subtotal': subtotal,
        'discount_rate': discount_rate * 100,
        'status': status,
        'discount_amount': discount_amount,
        'total_cost': total_cost
    }


# ==================== ROUTES ====================
@app.route('/')
# Visiting / runs home() and renders index.html
def home():
    """Landing page - Hero section """
    return render_template('index.html')


# this route handles the confirmation and payment step
# after the user has entered their details. It validates the payment information and simulates a successful payment, then creates or updates the member record and subscription in the database.
@app.route('/confirm-pay', methods=['GET', 'POST'])
def confirm_pay():
    pending_manage_membership = session.get('pending_manage_membership')
    pending_renew_membership = session.get('pending_renew_membership')
    pending_membership = session.get('pending_membership')
    pending_member = session.get('pending_member')

    if pending_manage_membership:
        gym_type_raw = pending_manage_membership['gym_type']
        confirm_pay_context = {
            'member_name': pending_manage_membership['member_name'],
            'member_email': pending_manage_membership['member_email'],
            'age': pending_manage_membership['age'],
            'is_student': pending_manage_membership['is_student'],
            'selected_gym': pending_manage_membership.get('selected_gym', 'Not selected'),
            'gym_type': gym_type_raw if gym_type_raw != 'none' else 'No Gym Access',
            'gym_type_raw': gym_type_raw,
            'addons': pending_manage_membership.get('addons', [])
        }
    elif pending_renew_membership:
        gym_type_raw = pending_renew_membership['gym_type']
        confirm_pay_context = {
            'member_name': pending_renew_membership['member_name'],
            'member_email': pending_renew_membership['member_email'],
            'age': pending_renew_membership['age'],
            'is_student': pending_renew_membership['is_student'],
            'selected_gym': pending_renew_membership.get('selected_gym', 'Not selected'),
            'gym_type': gym_type_raw if gym_type_raw != 'none' else 'No Gym Access',
            'gym_type_raw': gym_type_raw,
            'addons': pending_renew_membership.get('addons', [])
        }
    else:
        if not pending_membership:
            return redirect(url_for('calculate'))

        if not pending_member:
            return redirect(url_for('member_details'))

        gym_type_raw = pending_membership['gym_type']
        confirm_pay_context = {
            'member_name': pending_member['full_name'],
            'member_email': pending_member['email'],
            'age': pending_membership['age'],
            'is_student': pending_membership['is_student'],
            'selected_gym': pending_membership.get('selected_gym', 'Not selected'),
            'gym_type': gym_type_raw if gym_type_raw != 'none' else 'No Gym Access',
            'gym_type_raw': gym_type_raw,
            'addons': pending_membership.get('addons', [])
        }

    # Compute pricing breakdown for the confirmation page.
    try:
        sel_gym = confirm_pay_context.get('selected_gym')
        gym_type_for_calc = confirm_pay_context.get('gym_type_raw', 'none')
        addons = confirm_pay_context.get('addons', [])
        age = confirm_pay_context.get('age') or 0
        is_student = bool(confirm_pay_context.get('is_student'))

        if sel_gym in {'uGym', 'Power Zone'}:
            price_info = calculate_gym_cost(sel_gym, gym_type_for_calc, addons, age, is_student)
            joining_fee = price_info.get('joining_fee', 0)
            monthly_total = price_info.get('total_cost', 0)
            # Renewals should not include joining fee
            include_joining = not bool(pending_renew_membership)
            initial_total = monthly_total + (joining_fee if include_joining else 0)
        else:
            joining_fee = 0
            monthly_total = 0
            initial_total = 0

        confirm_pay_context.update({
            'joining_fee': joining_fee,
            'monthly_total': monthly_total,
            'initial_total': initial_total,
            'initial_charge': initial_total > 0
        })
    except Exception:
        # If pricing calculation fails for any reason, default to zero values
        confirm_pay_context.update({
            'joining_fee': 0,
            'monthly_total': 0,
            'initial_total': 0,
            'initial_charge': False
        })

    # In a real application, you would integrate with a payment gateway here.
    # For this assignment, we will just validate the input and simulate a successful payment.
    if request.method == 'POST':
        cardholder_name = (request.form.get('cardholder_name') or '').strip()
        card_number_raw = (request.form.get('card_number') or '').strip()
        expiry_raw = (request.form.get('expiry') or '').strip()
        cvv_raw = (request.form.get('cvv') or '').strip()
        billing_postcode = (request.form.get('billing_postcode') or '').strip()
        # if the user leaves any of the fields empty, show an error message and do not proceed
        if not all([cardholder_name, card_number_raw, expiry_raw, cvv_raw, billing_postcode]):
            confirm_pay_context['pay_error'] = 'Please complete all payment fields.'
            return render_template('confirm_pay.html', **confirm_pay_context)
        # the card number may contain spaces, but we remove them for validation.
        card_number = re.sub(r'\s+', '', card_number_raw)
        # Cardholder must look like a real name and only include common name punctuation.
        if not re.fullmatch(r"[A-Za-z][A-Za-z\s'\-]{1,25}", cardholder_name):
            confirm_pay_context['pay_error'] = "Cardholder name must be 2-26 characters and contain letters only."
            return render_template('confirm_pay.html', **confirm_pay_context)
        # if the card number is not exactly 16 digits, show an error message and do not proceed
        if not card_number.isdigit() or len(card_number) != 16:
            confirm_pay_context['pay_error'] = 'Card number must contain exactly 16 digits.'
            return render_template('confirm_pay.html', **confirm_pay_context)
        # CVV must be 3 or 4 digits, depending on the card type. For simplicity, we allow both lengths here.
        if not cvv_raw.isdigit() or len(cvv_raw) not in (3, 4):
            confirm_pay_context['pay_error'] = 'CVV must contain 3 or 4 digits.'
            return render_template('confirm_pay.html', **confirm_pay_context)
        # Normalize postcode and validate against UK-style format.
        normalized_postcode = re.sub(r'\s+', '', billing_postcode).upper()
        uk_postcode_pattern = r'^(GIR0AA|[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2})$'
        if not re.fullmatch(uk_postcode_pattern, normalized_postcode):
            confirm_pay_context['pay_error'] = 'Please enter a valid UK billing postcode (for example SW1A 1AA).'
            return render_template('confirm_pay.html', **confirm_pay_context)
        billing_postcode = f"{normalized_postcode[:-3]} {normalized_postcode[-3:]}"
        # Expiry date must be in MM / YY format and represent a valid future date.
        expiry_match = re.fullmatch(r'(0[1-9]|1[0-2])\s*/\s*(\d{2})', expiry_raw)
        if not expiry_match:
            confirm_pay_context['pay_error'] = 'Expiry must be in MM / YY format.'
            return render_template('confirm_pay.html', **confirm_pay_context)
        # Extract month and year from expiry date
        exp_month = int(expiry_match.group(1))
        exp_year = 2000 + int(expiry_match.group(2))

        # Treat expiry as valid through the end of the entered month.
        # this section is to check if the card is expired based on the current date and the expiry month/year provided by the user. The logic is as follows:
        if exp_month == 12:
            # if month is 12: next month is 1 of the next year (2027-01-01)
            next_month_start = datetime(exp_year + 1, 1, 1)
        else:
            # otherwise, next month is same year, month + 1 (2026-06-01 for 05/26)
            next_month_start = datetime(exp_year, exp_month + 1, 1)
        # if the current date is on or after the first day of the month following the expiry month, the card is expired.
        if datetime.utcnow() >= next_month_start:
            confirm_pay_context['pay_error'] = 'Card expiry date must be later than today.'
            return render_template('confirm_pay.html', **confirm_pay_context)
        # If we reach this point, all payment fields are valid. In a real app, you would now process the payment through a gateway API.
        # For this assignment, we will assume the payment is successful and proceed to create/update the member record and subscription.
        starts_at = datetime.utcnow()
        ends_at = starts_at + timedelta(days=30)

           # this section is for handling the case where an existing member is updating their membership options (e.g. changing gym access or add-ons).
           # We look for pending_manage_membership in the session, and if it exists, we update that member's record with the new selections and reset their subscription period to start now and end in 30 days. After updating, we clear the pending_manage_membership from the session and redirect to the account page with a success message.
        if pending_manage_membership:
            member = db.session.get(Member, pending_manage_membership['member_id'])
            if not member:
                session.pop('pending_manage_membership', None)
                session.clear()
                return redirect(url_for('login'))

            plan = MembershipPlan.query.filter_by(
                gym_name=pending_manage_membership['selected_gym'],
                plan_type=pending_manage_membership['gym_type']
            ).first()
            member.membership_plan_id = plan.id if plan else None
            assign_member_addons(member, pending_manage_membership.get('addons', []))
            member.subscription_status = 'active'
            member.subscription_starts_at = starts_at
            member.subscription_ends_at = ends_at
            member.next_billing_at = ends_at
            db.session.commit()

            session.pop('pending_manage_membership', None)
            flash('Payment successful. Your updated membership is now active.', 'success')
            return redirect(url_for('account'))

        if pending_renew_membership:
            member = db.session.get(Member, pending_renew_membership['member_id'])
            if not member:
                session.pop('pending_renew_membership', None)
                session.clear()
                return redirect(url_for('login'))

            member.subscription_status = 'active'
            member.subscription_starts_at = starts_at
            member.subscription_ends_at = ends_at
            member.next_billing_at = ends_at
            db.session.commit()

            session.pop('pending_renew_membership', None)
            flash('Payment successful. Your membership has been renewed.', 'success')
            return redirect(url_for('account'))

        member = Member.query.filter_by(email=pending_member['email']).first()
        if not member:
            return redirect(url_for('member_details'))
        # If the member doesn't have a membership_id yet, generate one.
        if not member.membership_id:
            member.membership_id = generate_membership_id()

        member.subscription_status = 'active'
        member.subscription_starts_at = starts_at
        member.subscription_ends_at = ends_at
        member.next_billing_at = ends_at
        db.session.commit()
        # The member is now paid and active. Keep them logged in and clear pending checkout data.
        session['user_id'] = member.id
        session.pop('pending_membership', None)
        session.pop('pending_member', None)
        session.pop('pending_manage_membership', None)
        session.pop('pending_renew_membership', None)
        return redirect(url_for('account'))

    return render_template('confirm_pay.html', **confirm_pay_context)

# The account page shows the user's subscription details and allows them to manage add-ons.
@app.route('/account', methods=['GET'])
def account():
    # Check if user is logged in by looking for user_id in session. If not found, redirect to login page.
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    # Load the member from the database using the user_id from session. If no member is found (e.g. user was deleted), clear session and redirect to login.
    member = db.session.get(Member, user_id)
    if not member:
        session.clear()
        return redirect(url_for('login'))

    changed = False
    if sync_subscription_status(member):
        changed = True
    if auto_renew_subscription(member):
        changed = True

    if changed:
        db.session.commit()

    return render_template('account.html', **get_member_subscription_data(member))


@app.route('/cancel-membership', methods=['POST'])
def cancel_membership():
    """Clear membership/subscription details so the dashboard shows no active plan."""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    member = db.session.get(Member, user_id)
    if not member:
        session.clear()
        return redirect(url_for('login'))

    member.membership_plan_id = None
    member.has_classes = False
    member.has_swimming_pool = False
    member.has_massage = False
    member.has_physiotherapy = False
    member.subscription_status = 'inactive'
    member.subscription_starts_at = None
    member.subscription_ends_at = None
    member.next_billing_at = None
    db.session.commit()

    flash('Membership cancelled. Your dashboard has been cleared.', 'success')
    return redirect(url_for('account'))


@app.route('/manage-addons', methods=['GET', 'POST'])
def manage_addons():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    member = db.session.get(Member, user_id) 
    # this section loads the member from the database using the user_id stored in the session. 
    # If no member is found (which could happen if the user was deleted), it clears the session and redirects to the login page to prevent errors from trying to access a non-existent member.

    if not member:
        session.clear()
        return redirect(url_for('login'))

    if sync_subscription_status(member):
        db.session.commit()

    subscription_data = get_member_subscription_data(member)
    if subscription_data['remaining_days'] > 0:
        flash('You can update your membership only when your remaining days reach 0.', 'error')
        return redirect(url_for('account'))

    current_gym_name = member.membership_plan.gym_name if member.membership_plan else 'uGym'
    current_gym_type = member.membership_plan.plan_type if member.membership_plan else 'none'
    current_addons = selected_addons_from_member(member)

    valid_gyms = ['uGym', 'Power Zone']
    valid_gym_types = ['none', 'Gym: Super-off peak', 'Gym: Off-peak', 'Gym: Anytime']
    addon_plan_types = ['Swimming Pool', 'Classes', 'Massage', 'Physiotherapy']

    if request.method == 'POST':
        new_gym_name = (request.form.get('gym_name') or '').strip()
        new_gym_type = (request.form.get('gym_type') or '').strip()
        new_addons = request.form.getlist('addons')

        if new_gym_name not in valid_gyms:
            flash('Please select a valid gym.', 'error')
            return redirect(url_for('manage_addons'))

        if new_gym_type not in valid_gym_types:
            flash('Please select a valid gym access type.', 'error')
            return redirect(url_for('manage_addons'))

        if new_gym_type == 'none' and not new_addons:
            flash('Please select at least one add-on or a gym access type.', 'error')
            return redirect(url_for('manage_addons'))

        available_addon_names = {
            p.plan_type for p in MembershipPlan.query.filter(
                MembershipPlan.gym_name == new_gym_name,
                MembershipPlan.plan_type.in_(addon_plan_types)
            ).all()
        }
        new_addons = [addon for addon in new_addons if addon in available_addon_names]

        session['pending_manage_membership'] = {
            'member_id': member.id,
            'member_name': member.name,
            'member_email': member.email,
            'age': member.age,
            'is_student': bool(member.is_student),
            'selected_gym': new_gym_name,
            'gym_type': new_gym_type,
            'addons': new_addons
        }
        session.pop('pending_renew_membership', None)

        flash('Please complete payment to activate your updated membership.', 'success')
        return redirect(url_for('confirm_pay'))

    status = determine_status_from_age(member.age, member.is_student)

    def get_gym_display_data(gym_name):
        addon_plans = MembershipPlan.query.filter(
            MembershipPlan.gym_name == gym_name,
            MembershipPlan.plan_type.in_(addon_plan_types)
        ).all()

        gym_plans = MembershipPlan.query.filter(
            MembershipPlan.gym_name == gym_name,
            MembershipPlan.plan_type.in_(valid_gym_types[1:])
        ).all()

        rule = DiscountRule.query.filter_by(gym_name=gym_name, status=status).first()
        discount_rate = rule.discount_rate * 100 if rule else 0
        discountable = DISCOUNTABLE_ADDONS

        return {
            'addon_plans': addon_plans,
            'gym_plans': gym_plans,
            'discount_rate': discount_rate,
            'discountable_addons': discountable
        }

    return render_template(
        'manage_addons.html',
        current_gym_name=current_gym_name,
        current_gym_type=current_gym_type,
        current_addons=current_addons,
        valid_gyms=valid_gyms,
        valid_gym_types=valid_gym_types,
        ugym=get_gym_display_data('uGym'),
        power_zone=get_gym_display_data('Power Zone'),
        status=status,
        member_age=member.age,
        is_student=bool(member.is_student)
    )


# The login route allows users to log in with their email and password. It validates the credentials and sets the user_id in session if successful.
@app.route('/login', methods=['GET', 'POST'])
def login():

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password') or ''
        # We look up the member by email. If no member is found or the password check fails, we render the login page again with an error message and pre-fill the email field for convenience.
        member = Member.query.filter_by(email=email).first()

        if not member or not member.check_password(password):
            return render_template(
                'login.html',
                error='Invalid email or password.',
                email=email
            )
        # If the login is successful, we store the user's ID in the session to keep them logged in across requests, and then redirect them to their account page.
        session['user_id'] = member.id
        return redirect(url_for('account'))

    return render_template('login.html')


# The logout route clears the session, effectively logging the user out, and redirects them to the home page.
# Accepts both GET and POST so it can be triggered from either a link or a form button.
@app.route('/logout', methods=['GET', 'POST'])
def logout():
    # Clearing the session removes all stored data, including the user_id, which logs the user out. After clearing the session, we redirect them to the home page.
    session.clear()
    return redirect(url_for('home'))


# Route to delete the current user's account and clear their session.
@app.route('/delete-account', methods=['POST'])
def delete_account():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    member = db.session.get(Member, user_id)
    if member:
        db.session.delete(member)
        db.session.commit()
    session.clear()
    return redirect(url_for('home'))


# This route handles the member details form where users enter their name, email, and password after selecting their gym and membership options.
# It validates the input and either creates a new member record or updates an existing one, then redirects to the payment confirmation page.
@app.route('/member-details', methods=['GET', 'POST'])
def member_details():
    # We expect that the user has already gone through the gym selection and membership option steps, which store their choices in the session under 'pending_membership'. If we don't find this data in the session, it means the user is trying to access this page out of order, so we redirect them back to the calculator page to start the process.
    pending_membership = session.get('pending_membership')

    if not pending_membership:
        return redirect(url_for('calculate'))
    # We also check if the user has selected a gym. If not, we redirect them back to the gym selection step to ensure they complete that part before entering their details.
    selected_gym = pending_membership.get('selected_gym')
    if not selected_gym:
        return redirect(url_for('calculate'))

    pending_member = session.get('pending_member', {})

    if request.method == 'POST':
        name = (request.form.get('full_name') or '').strip()
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''

        def render_form(error):
            return render_template(
                'member_details.html',
                error=error,
                full_name=name,
                email=email,
                age=pending_membership['age'],
                is_student=pending_membership['is_student'],
                selected_gym=selected_gym,
                gym_type=pending_membership['gym_type'] if pending_membership['gym_type'] != 'none' else 'No Gym Access',
                addons=pending_membership.get('addons', [])
            )

        full_name_pattern = r"^[A-Za-z][A-Za-z\s'\-]{2,59}$"
        if not re.fullmatch(full_name_pattern, name):
            return render_form("Full name can contain letters only and must include a first name and surname.")

        name_parts = [part for part in name.split() if part]
        if len(name_parts) < 2:
            return render_form('Please enter both your first name and surname.')

        email_pattern = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        if not re.match(email_pattern, email):
            return render_form('Please enter a valid email address.')

        if len(password) < 8:
            return render_form('Password must be at least 8 characters.')

        if password != confirm_password:
            return render_form('Passwords do not match.')

        current_email = pending_member.get('email')
        existing_member = Member.query.filter_by(email=email).first()
        if existing_member and email != current_email:
            return render_form('This email is already registered. Please use a different email.')

        if not existing_member:
            plan = MembershipPlan.query.filter_by(
                gym_name=selected_gym,
                plan_type=pending_membership['gym_type']
            ).first()
            member = Member(
                name=name,
                age=pending_membership['age'],
                is_student=pending_membership['is_student'],
                email=email,
                membership_plan_id=plan.id if plan else None,
                membership_id=generate_membership_id()
            )
            assign_member_addons(member, pending_membership.get('addons', []))
            member.set_password(password)
            db.session.add(member)
            db.session.commit()

        session['pending_member'] = {
            'full_name': name,
            'email': email
        }
        return redirect(url_for('confirm_pay'))

    return render_template(
        'member_details.html',
        full_name=pending_member.get('full_name', ''),
        email=pending_member.get('email', ''),
        age=pending_membership['age'],
        is_student=pending_membership['is_student'],
        selected_gym=selected_gym,
        # We display the gym type in a user-friendly way. If the gym_type is 'none', we show 'No Gym Access' instead of 'none'.
        gym_type=pending_membership['gym_type'] if pending_membership['gym_type'] != 'none' else 'No Gym Access',
        addons=pending_membership.get('addons', [])
    )


# This route handles the gym selection step after the user has entered their age, student status, and membership options.
@app.route('/select-gym', methods=['POST'])
def select_gym():
    # We expect that the user has already entered their age, student status, and membership options, which are stored in the session under 'pending_membership'. If we don't find this data in the session, it means the user is trying to access this page out of order, so we redirect them back to the calculator page to start the process.
    pending_membership = session.get('pending_membership')
    if not pending_membership:
        return redirect(url_for('calculate'))
    # We check if the user has selected a gym. If not, we calculate the costs for both gyms and render the results page again with an error message.
    selected_gym = request.form.get('selected_gym')
    if selected_gym not in {'uGym', 'Power Zone'}:
        ugym_result = calculate_gym_cost(
            'uGym',
            pending_membership['gym_type'],
            pending_membership.get('addons', []),
            pending_membership['age'],
            pending_membership['is_student']
        )
        power_result = calculate_gym_cost(
            'Power Zone',
            pending_membership['gym_type'],
            pending_membership.get('addons', []),
            pending_membership['age'],
            pending_membership['is_student']
        )
        better_gym = 'uGym' if ugym_result['total_cost'] <= power_result['total_cost'] else 'Power Zone'

        return render_template(
            'results.html',
            gym_type=pending_membership['gym_type'] if pending_membership['gym_type'] != 'none' else 'No Gym Access',
            addons=pending_membership.get('addons', []),
            ugym_result=ugym_result,
            power_result=power_result,
            better_gym=better_gym,
            error='Please choose which gym you want before continuing.'
        )
    # If the selected gym is valid, we save it in the session and redirect to member details.
    pending_membership['selected_gym'] = selected_gym
    session['pending_membership'] = pending_membership
    return redirect(url_for('member_details'))


# Visiting /calculator runs calculate() which renders calculator.html with the form
@app.route('/calculator', methods=['GET', 'POST'])
def calculate():
    if request.method == 'POST':
        age = (request.form.get('age') or '').strip()
        is_student = bool(request.form.get('is_student'))
        gym_type = request.form.get('gym_type')
        addons = request.form.getlist('addons')
        action = request.form.get('action', 'compare')

        try:
            age = int(age)
        except ValueError:
            return render_template(
                'calculator.html',
                error='Please enter a valid age.'
            )
        # We enforce the minimum age requirement of 16 years.
        if age < 16:
            flash('Sorry, you must be at least 16 years old to join our gyms.', 'error')
            return redirect(url_for('calculate'))
        # We validate the gym access option selected by the user.
        if gym_type not in {'Gym: Super-off peak', 'Gym: Off-peak', 'Gym: Anytime', 'none'}:
            return render_template(
                'calculator.html',
                error='Please choose a valid gym access option.'
            )
        # We check if the user has selected at least one gym access option or add-on service.
        if gym_type == 'none' and not addons:
            return render_template(
                'calculator.html',
                error='Please select at least one add-on service or choose a gym membership.'
            )

        ugym_result = calculate_gym_cost('uGym', gym_type, addons, age, is_student)
        power_result = calculate_gym_cost('Power Zone', gym_type, addons, age, is_student)
        better_gym = 'uGym' if ugym_result['total_cost'] <= power_result['total_cost'] else 'Power Zone'

        session['pending_membership'] = {
            'age': age,
            'is_student': is_student,
            'gym_type': gym_type,
            'addons': addons,
            'selected_gym': None
        }
        session.pop('pending_member', None)

        if action == 'compare':
            return render_template(
                'results.html',
                gym_type=gym_type if gym_type != 'none' else 'No Gym Access',
                addons=addons,
                ugym_result=ugym_result,
                power_result=power_result,
                better_gym=better_gym
            )

    return render_template('calculator.html')


# ==================== MAIN ====================

if __name__ == '__main__':
    app.run(debug=True, port=5000)
