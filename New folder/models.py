"""
Database models for the Gym Management System.
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# Initialize the SQLAlchemy object
db = SQLAlchemy()

class Member(db.Model):
    """
    Model representing a gym member.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    is_student = db.Column(db.Boolean, nullable=False, default=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    membership_id = db.Column(db.String(32), unique=True, nullable=True)
    subscription_status = db.Column(db.String(32), nullable=False, default='inactive')
    subscription_starts_at = db.Column(db.DateTime, nullable=True)
    subscription_ends_at = db.Column(db.DateTime, nullable=True)
    next_billing_at = db.Column(db.DateTime, nullable=True)
    membership_plan_id = db.Column(db.Integer, db.ForeignKey('membership_plans.id'), nullable=True)
    membership_plan = db.relationship('MembershipPlan', backref='members')
    has_classes = db.Column(db.Boolean, default=False, nullable=False)
    has_swimming_pool = db.Column(db.Boolean, default=False, nullable=False)
    has_massage = db.Column(db.Boolean, default=False, nullable=False)
    has_physiotherapy = db.Column(db.Boolean, default=False, nullable=False)
    #join_date = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        """Hashes the password and stores it."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Checks if the provided password matches the hash."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<Member {self.name}>'
    
class MembershipPlan(db.Model):
    """Stores all available membership options for both gyms"""
    __tablename__ = 'membership_plans'

    id = db.Column(db.Integer, primary_key=True)
    # String lengths can often be optimized. If gym names are short, 32 is plenty.
    gym_name = db.Column(db.String(32), nullable=False)  
    plan_type = db.Column(db.String(128), nullable=False)
    
    # Using Numeric (precision of 10 digits, 2 decimal places) instead of Float
    price_no_gym = db.Column(db.Numeric(10, 2), nullable=True) 
    price_with_gym = db.Column(db.Numeric(10, 2), nullable=True) 

    __table_args__ = (
        # Ensures no duplicate plans exist for the same gym
        db.UniqueConstraint('gym_name', 'plan_type', name='uq_gym_plan_type'),
        # Speeds up our specific lookup queries
        db.Index('idx_gym_plan', 'gym_name', 'plan_type')
    )

    def __repr__(self):
        return f'<MembershipPlan {self.gym_name} - {self.plan_type}>'


class DiscountRule(db.Model):
    """Stores discount rates per gym/status."""
    __tablename__ = 'discount_rules'

    id = db.Column(db.Integer, primary_key=True)
    gym_name = db.Column(db.String(32), nullable=False)
    status = db.Column(db.String(32), nullable=False) 
    
    # Numeric for discount rates (e.g., 0.15 for 15%)
    discount_rate = db.Column(db.Numeric(4, 3), nullable=False, default=0.0)

    __table_args__ = (
        # Ensures only one discount rule exists per status per gym
        db.UniqueConstraint('gym_name', 'status', name='uq_gym_status'),
        # Speeds up rule fetching
        db.Index('idx_gym_status', 'gym_name', 'status')
    )

    def __repr__(self):
        return f'<DiscountRule {self.gym_name} - {self.status}>'