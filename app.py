from flask import Flask, render_template, request, redirect, url_for, Response, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from sqlalchemy import extract as db_extract
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
from collections import Counter
import calendar, csv, io, os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

database_url = os.environ.get('DATABASE_URL', 'sqlite:///expenses.db')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ===== MODELS =====

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expenses = db.relationship('Expense', backref='user', lazy=True, cascade='all, delete-orphan')
    budgets = db.relationship('Budget', backref='user', lazy=True, cascade='all, delete-orphan')

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    date = db.Column(db.Date, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    limit = db.Column(db.Float, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===== HELPERS =====

def get_insights(expenses):
    insights = []
    if len(expenses) < 2:
        return insights
    cat_totals = {}
    for e in expenses:
        cat_totals[e.category] = cat_totals.get(e.category, 0) + e.amount
    if cat_totals:
        top = max(cat_totals, key=cat_totals.get)
        insights.append(f"Most spending in {top} — ₹{cat_totals[top]:.2f}")
    weekend = sum(e.amount for e in expenses if e.date.weekday() >= 5)
    weekday = sum(e.amount for e in expenses if e.date.weekday() < 5)
    if weekend > 0 and weekday > 0:
        if weekend > weekday:
            insights.append(f"Weekend spending (₹{weekend:.2f}) exceeds weekday (₹{weekday:.2f})")
        else:
            insights.append(f"Weekday spending (₹{weekday:.2f}) exceeds weekend (₹{weekend:.2f})")
    avg = sum(e.amount for e in expenses) / len(expenses)
    insights.append(f"Average expense is ₹{avg:.2f}")
    big = max(expenses, key=lambda e: e.amount)
    insights.append(f"Biggest single spend: {big.name} at ₹{big.amount:.2f}")
    return insights

def get_recurring(expenses):
    counts = Counter(e.name.lower() for e in expenses)
    return {name for name, c in counts.items() if c > 1}

def get_streak(expenses):
    if not expenses:
        return 0
    today = date.today()
    streak = 0
    check = today
    expense_dates = {e.date for e in expenses}
    while check in expense_dates:
        streak += 1
        if check.day > 1:
            check = date(check.year, check.month, check.day - 1)
        elif check.month > 1:
            prev_month = check.month - 1
            prev_year = check.year
            last_day = calendar.monthrange(prev_year, prev_month)[1]
            check = date(prev_year, prev_month, last_day)
        else:
            check = date(check.year - 1, 12, 31)
    return streak

def get_personality(expenses):
    if not expenses:
        return {'icon': '👤', 'title': 'New here', 'desc': 'Add expenses to discover your spending personality'}
    cat_totals = {}
    for e in expenses:
        cat_totals[e.category] = cat_totals.get(e.category, 0) + e.amount
    top = max(cat_totals, key=cat_totals.get) if cat_totals else 'Other'
    personalities = {
        'Food': {'icon': '🍕', 'title': 'The Foodie', 'desc': 'You live to eat. Food is your biggest joy and expense.'},
        'Transport': {'icon': '🚗', 'title': 'The Commuter', 'desc': 'Always on the move. You spend big on getting around.'},
        'Shopping': {'icon': '🛍', 'title': 'The Impulse Buyer', 'desc': 'Retail therapy is real for you. You love a good purchase.'},
        'Health': {'icon': '💪', 'title': 'The Wellness Seeker', 'desc': 'You invest in your health. Respect.'},
        'Other': {'icon': '🎯', 'title': 'The Wildcard', 'desc': 'Unpredictable and diverse. You keep things interesting.'},
    }
    return personalities.get(top, personalities['Other'])

# ===== AUTH ROUTES =====

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        if User.query.filter_by(email=email).first():
            flash('Email already registered. Please log in.', 'error')
            return redirect(url_for('register'))
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return redirect(url_for('register'))
        user = User(
            name=name,
            email=email,
            password=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password, password):
            flash('Invalid email or password.', 'error')
            return redirect(url_for('login'))
        login_user(user, remember=True)
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ===== MAIN ROUTES =====

@app.route('/')
@login_required
def index():
    month_filter = request.args.get('month', '')
    search = request.args.get('search', '')

    query = Expense.query.filter_by(user_id=current_user.id)
    if month_filter:
        y, m = month_filter.split('-')
        query = query.filter(
            db_extract('year', Expense.date) == int(y),
            db_extract('month', Expense.date) == int(m)
        )
    if search:
        query = query.filter(Expense.name.ilike(f'%{search}%'))

    expenses = query.order_by(Expense.date.desc()).all()
    all_expenses = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.date.desc()).all()
    total = sum(e.amount for e in expenses)

    categories = ['Food', 'Transport', 'Shopping', 'Health', 'Other']
    category_totals = [sum(e.amount for e in expenses if e.category == c) for c in categories]

    today = date.today()
    this_m = sum(e.amount for e in all_expenses if e.date.year == today.year and e.date.month == today.month)
    last_month = today.month - 1 if today.month > 1 else 12
    last_year = today.year if today.month > 1 else today.year - 1
    last_m = sum(e.amount for e in all_expenses if e.date.year == last_year and e.date.month == last_month)
    max_m = max(this_m, last_m, 1)
    monthly_diff = this_m - last_m

    budgets = {b.category: b.limit for b in Budget.query.filter_by(user_id=current_user.id).all()}
    budget_data = []
    for cat in categories:
        spent = sum(e.amount for e in all_expenses if e.category == cat)
        budget_data.append({'name': cat, 'spent': spent, 'limit': budgets.get(cat, 0)})

    biggest = max(all_expenses, key=lambda e: e.amount) if all_expenses else None
    top_expenses = sorted(all_expenses, key=lambda e: e.amount, reverse=True)[:5]
    category_breakdown = [(c, sum(e.amount for e in all_expenses if e.category == c)) for c in categories if any(e.category == c for e in all_expenses)]

    monthly_totals = []
    for i in range(5, -1, -1):
        m = (today.month - i - 1) % 12 + 1
        y = today.year - ((i - today.month + 1) // 12 + (1 if (today.month - i - 1) < 0 else 0))
        mt = sum(e.amount for e in all_expenses if e.date.month == m and e.date.year == y)
        if mt > 0:
            monthly_totals.append((calendar.month_abbr[m] + f' {y}', mt))

    days_in_month = today.day
    daily_avg = this_m / days_in_month if days_in_month > 0 else 0
    weekday_total = sum(e.amount for e in all_expenses if e.date.weekday() < 5)
    weekend_total = sum(e.amount for e in all_expenses if e.date.weekday() >= 5)

    return render_template('index.html',
        expenses=expenses, total=total,
        categories=categories, category_totals=category_totals,
        month_filter=month_filter, search=search,
        insights=get_insights(expenses),
        recurring_names=get_recurring(all_expenses),
        biggest=biggest, top_expenses=top_expenses,
        this_month_total=this_m, last_month_total=last_m,
        this_month_pct=min(this_m/max_m*100, 100),
        last_month_pct=min(last_m/max_m*100, 100),
        monthly_diff=monthly_diff,
        budget_data=budget_data,
        category_breakdown=category_breakdown,
        monthly_totals=monthly_totals,
        daily_avg=daily_avg,
        weekday_total=weekday_total, weekend_total=weekend_total,
        recent_expenses=all_expenses[:8],
        streak=get_streak(all_expenses),
        personality=get_personality(all_expenses)
    )

@app.route('/add', methods=['POST'])
@login_required
def add_expense():
    db.session.add(Expense(
        name=request.form['name'],
        amount=float(request.form['amount']),
        category=request.form['category'],
        date=datetime.strptime(request.form['date'], '%Y-%m-%d').date(),
        user_id=current_user.id
    ))
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/delete/<int:eid>', methods=['POST'])
@login_required
def delete_expense(eid):
    expense = Expense.query.get_or_404(eid)
    if expense.user_id != current_user.id:
        return redirect(url_for('index'))
    db.session.delete(expense)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/edit/<int:eid>', methods=['GET', 'POST'])
@login_required
def edit_expense(eid):
    expense = Expense.query.get_or_404(eid)
    if expense.user_id != current_user.id:
        return redirect(url_for('index'))
    if request.method == 'POST':
        expense.name = request.form['name']
        expense.amount = float(request.form['amount'])
        expense.category = request.form['category']
        expense.date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('edit.html', expense=expense)

@app.route('/set_budget', methods=['POST'])
@login_required
def set_budget():
    cat = request.form['category']
    limit = float(request.form['limit'])
    budget = Budget.query.filter_by(category=cat, user_id=current_user.id).first()
    if budget:
        budget.limit = limit
    else:
        db.session.add(Budget(category=cat, limit=limit, user_id=current_user.id))
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/export')
@login_required
def export_csv():
    expenses = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.date.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Name', 'Amount', 'Category', 'Date'])
    for e in expenses:
        writer.writerow([e.id, e.name, e.amount, e.category, e.date])
    output.seek(0)
    return Response(output, mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=expenses.csv'})

with app.app_context():
    db.create_all()

@app.route('/reset-db-now')
def reset_db():
    db.drop_all()
    db.create_all()
    return 'Database reset successfully!'

if __name__ == '__main__':
    app.run(debug=True)