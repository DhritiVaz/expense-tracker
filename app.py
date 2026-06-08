from flask import Flask, render_template, request, redirect, url_for, session, Response, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, datetime, timedelta
from collections import defaultdict
import os, calendar, csv, io

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')

db_url = os.environ.get('DATABASE_URL', 'sqlite:///expenses.db')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ===== MODELS =====

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    date = db.Column(db.Date, nullable=False)
    type = db.Column(db.String(10), default='expense')  # 'income' or 'expense'
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True)

class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    limit = db.Column(db.Float, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    balance = db.Column(db.Float, nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===== HELPERS =====

def _adjust_account_balance(account_id, type_, amount, reverse=False):
    if not account_id:
        return
    account = Account.query.get(account_id)
    if not account or account.user_id != current_user.id:
        return
    delta = amount if type_ == 'income' else -amount
    if reverse:
        delta = -delta
    account.balance += delta

def get_insights(expenses):
    if not expenses:
        return []
    insights = []
    cat_totals = defaultdict(float)
    for e in expenses:
        if e.type == 'expense':
            cat_totals[e.category] += e.amount
    if cat_totals:
        top = max(cat_totals, key=cat_totals.get)
        insights.append(f"You spend most on {top} — ₹{cat_totals[top]:.0f} total")
    weekday = sum(e.amount for e in expenses if e.type == 'expense' and e.date.weekday() < 5)
    weekend = sum(e.amount for e in expenses if e.type == 'expense' and e.date.weekday() >= 5)
    if weekday and weekend:
        insights.append(f"Weekday spending (₹{weekday:.0f}) vs weekend (₹{weekend:.0f})")
    expense_list = [e for e in expenses if e.type == 'expense']
    if expense_list:
        avg = sum(e.amount for e in expense_list) / len(expense_list)
        insights.append(f"Average expense is ₹{avg:.0f}")
        biggest = max(expense_list, key=lambda e: e.amount)
        insights.append(f"Biggest expense: {biggest.name} at ₹{biggest.amount:.0f}")
    return insights

def get_recurring(expenses):
    names = [e.name.lower() for e in expenses if e.type == 'expense']
    return {n for n in names if names.count(n) > 1}

def get_streak(expenses):
    if not expenses:
        return 0
    dates = sorted({e.date for e in expenses}, reverse=True)
    streak = 0
    check = date.today()
    for d in dates:
        if d == check:
            streak += 1
            check -= timedelta(days=1)
        elif d < check:
            break
    return streak

def get_personality(expenses):
    expense_list = [e for e in expenses if e.type == 'expense']
    if not expense_list:
        return {'icon': '🌱', 'title': 'Fresh Start', 'desc': 'Start tracking to discover your spending personality'}
    cat_totals = defaultdict(float)
    for e in expense_list:
        cat_totals[e.category] += e.amount
    top = max(cat_totals, key=cat_totals.get) if cat_totals else 'Other'
    personalities = {
        'Food': {'icon': '🍜', 'title': 'The Foodie', 'desc': 'Your heart (and wallet) lives in the kitchen'},
        'Transport': {'icon': '🚗', 'title': 'The Commuter', 'desc': 'Always on the move, always spending on the go'},
        'Shopping': {'icon': '🛍️', 'title': 'The Shopaholic', 'desc': 'Retail therapy is your love language'},
        'Health': {'icon': '💪', 'title': 'The Wellness Seeker', 'desc': 'Investing in yourself, one expense at a time'},
        'Other': {'icon': '🎯', 'title': 'The Wildcard', 'desc': 'Unpredictable and spontaneous with spending'},
    }
    return personalities.get(top, personalities['Other'])

# ===== PDF HELPERS =====

# ===== ROUTES =====

@app.route('/', methods=['GET'])
@login_required
def index():
    search = request.args.get('search', '')
    month_filter = request.args.get('month', '')
    today = date.today()

    all_transactions = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.date.desc()).all()

    # Filtered for display
    transactions = all_transactions
    if search:
        transactions = [e for e in transactions if search.lower() in e.name.lower()]
    if month_filter:
        y, m = map(int, month_filter.split('-'))
        transactions = [e for e in transactions if e.date.year == y and e.date.month == m]

    # Split by type
    all_expenses = [e for e in all_transactions if e.type == 'expense']
    all_income = [e for e in all_transactions if e.type == 'income']

    total_expenses = sum(e.amount for e in all_expenses)
    total_income = sum(e.amount for e in all_income)
    net = total_income - total_expenses

    # For display (filtered)
    display_expenses = [e for e in transactions if e.type == 'expense']
    display_income = [e for e in transactions if e.type == 'income']

    biggest = max(all_expenses, key=lambda e: e.amount) if all_expenses else None
    recent_transactions = all_transactions[:8]

    # Monthly comparison
    this_month_exp = sum(e.amount for e in all_expenses if e.date.year == today.year and e.date.month == today.month)
    last_m = today.month - 1 or 12
    last_y = today.year if today.month > 1 else today.year - 1
    last_month_exp = sum(e.amount for e in all_expenses if e.date.year == last_y and e.date.month == last_m)
    monthly_diff = this_month_exp - last_month_exp
    max_monthly = max(this_month_exp, last_month_exp) or 1
    this_month_pct = round(this_month_exp / max_monthly * 100)
    last_month_pct = round(last_month_exp / max_monthly * 100)

    # Monthly totals (expenses)
    monthly_totals = []
    for i in range(5, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        mt = sum(e.amount for e in all_expenses if e.date.month == m and e.date.year == y)
        if mt > 0:
            monthly_totals.append((calendar.month_abbr[m] + f' {y}', mt))

    # Day of week
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    day_totals = [sum(e.amount for e in all_expenses if e.date.weekday() == i) for i in range(7)]

    # Reports
    weekday_total = sum(e.amount for e in all_expenses if e.date.weekday() < 5)
    weekend_total = sum(e.amount for e in all_expenses if e.date.weekday() >= 5)
    days_this_month = today.day
    daily_avg = this_month_exp / days_this_month if days_this_month else 0
    top_expenses = sorted(all_expenses, key=lambda e: e.amount, reverse=True)[:5]

    categories = ['Food', 'Transport', 'Shopping', 'Health', 'Other']
    category_totals = [sum(e.amount for e in all_expenses if e.category == c) for c in categories]
    category_breakdown = [(c, t) for c, t in zip(categories, category_totals) if t > 0]

    # Income categories
    income_categories = ['Salary', 'Freelance', 'Gift', 'Investment', 'Other']
    income_cat_totals = [sum(e.amount for e in all_income if e.category == c) for c in income_categories]
    income_breakdown = [(c, t) for c, t in zip(income_categories, income_cat_totals) if t > 0]

    # Budget
    budgets = Budget.query.filter_by(user_id=current_user.id).all()
    budget_map = {b.category: b.limit for b in budgets}
    budget_data = [{'name': c, 'spent': sum(e.amount for e in all_expenses if e.category == c),
                    'limit': budget_map.get(c, 0)} for c in categories]

    # Accounts
    accounts = Account.query.filter_by(user_id=current_user.id).all()
    default_account = next((a for a in accounts if a.is_default), None)
    total_balance = sum(a.balance for a in accounts)
    balance_after_spending = total_balance

    recurring_names = get_recurring(all_transactions)
    insights = get_insights(all_transactions)

    return render_template('index.html',
        expenses=transactions,
        display_expenses=display_expenses,
        display_income=display_income,
        total=total_expenses,
        total_income=total_income,
        net=net,
        biggest=biggest,
        recent_transactions=recent_transactions,
        this_month_total=this_month_exp,
        last_month_total=last_month_exp,
        monthly_diff=monthly_diff,
        this_month_pct=this_month_pct,
        last_month_pct=last_month_pct,
        monthly_totals=monthly_totals,
        day_names=day_names,
        day_totals=day_totals,
        weekday_total=weekday_total,
        weekend_total=weekend_total,
        daily_avg=daily_avg,
        top_expenses=top_expenses,
        categories=categories,
        category_totals=category_totals,
        category_breakdown=category_breakdown,
        income_categories=income_categories,
        income_cat_totals=income_cat_totals,
        income_breakdown=income_breakdown,
        budget_data=budget_data,
        accounts=accounts,
        default_account=default_account,
        total_balance=total_balance,
        balance_after_spending=balance_after_spending,
        recurring_names=recurring_names,
        insights=insights,
        search=search,
        month_filter=month_filter,
    )

@app.route('/add', methods=['POST'])
@login_required
def add():
    name = request.form.get('name', '').strip()
    amount = float(request.form.get('amount', '0'))
    category = request.form.get('category', 'Other')
    date_str = request.form.get('date', str(date.today()))
    type_ = request.form.get('type', 'expense')
    tab = request.form.get('tab', 'expenses')
    account_id_raw = request.form.get('account_id', '').strip()
    account_id = int(account_id_raw) if account_id_raw else None

    try:
        entry = Expense(
            name=name,
            amount=amount,
            category=category,
            date=datetime.strptime(date_str, '%Y-%m-%d').date(),
            type=type_,
            user_id=current_user.id,
            account_id=account_id
        )
        db.session.add(entry)
        _adjust_account_balance(account_id, type_, amount)
        db.session.commit()
    except Exception as e:
        print(f"Error adding: {e}")

    return redirect(f'/?tab={tab}')

@app.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id):
    entry = Expense.query.get_or_404(id)
    if entry.user_id == current_user.id:
        tab = entry.type
        _adjust_account_balance(entry.account_id, entry.type, entry.amount, reverse=True)
        db.session.delete(entry)
        db.session.commit()
        return redirect(f'/?tab={tab}s')
    return redirect('/')

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    entry = Expense.query.get_or_404(id)
    if entry.user_id != current_user.id:
        return redirect('/')
    if request.method == 'POST':
        new_amount = float(request.form.get('amount', entry.amount))
        new_type = request.form.get('type', entry.type)
        account_id_raw = request.form.get('account_id', '').strip()
        new_account_id = int(account_id_raw) if account_id_raw else None

        # Reverse old effect on old account
        _adjust_account_balance(entry.account_id, entry.type, entry.amount, reverse=True)

        entry.name = request.form.get('name', entry.name)
        entry.amount = new_amount
        entry.category = request.form.get('category', entry.category)
        entry.type = new_type
        entry.account_id = new_account_id
        date_str = request.form.get('date')
        if date_str:
            entry.date = datetime.strptime(date_str, '%Y-%m-%d').date()

        # Apply new effect on new account
        _adjust_account_balance(new_account_id, new_type, new_amount)

        db.session.commit()
        return redirect(f'/?tab={entry.type}s')
    accounts = Account.query.filter_by(user_id=current_user.id).all()
    return render_template('edit.html', expense=entry, accounts=accounts)

@app.route('/set_budgets_bulk', methods=['POST'])
@login_required
def set_budgets_bulk():
    data = request.get_json()
    for item in data.get('budgets', []):
        category = item.get('category')
        limit = float(item.get('limit', 0))
        budget = Budget.query.filter_by(user_id=current_user.id, category=category).first()
        if budget:
            budget.limit = limit
        else:
            budget = Budget(category=category, limit=limit, user_id=current_user.id)
            db.session.add(budget)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/set_budget', methods=['POST'])
@login_required
def set_budget():
    category = request.form.get('category')
    limit = float(request.form.get('limit', 0))
    budget = Budget.query.filter_by(user_id=current_user.id, category=category).first()
    if budget:
        budget.limit = limit
    else:
        budget = Budget(category=category, limit=limit, user_id=current_user.id)
        db.session.add(budget)
    db.session.commit()
    return redirect('/?tab=budget')

@app.route('/export')
@login_required
def export():
    all_transactions = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.date.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Name', 'Category', 'Type', 'Amount'])
    for e in all_transactions:
        writer.writerow([e.date, e.name, e.category, e.type, e.amount])
    output.seek(0)
    return Response(output, mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment;filename=transactions.csv'})

@app.route('/accounts/add', methods=['POST'])
@login_required
def add_account():
    name = request.form.get('name', '').strip()
    balance = float(request.form.get('balance', 0))
    account = Account(name=name, balance=balance, user_id=current_user.id)
    db.session.add(account)
    db.session.commit()
    return redirect('/?tab=accounts')

@app.route('/accounts/delete/<int:id>', methods=['POST'])
@login_required
def delete_account(id):
    account = Account.query.get_or_404(id)
    if account.user_id == current_user.id:
        db.session.delete(account)
        db.session.commit()
    return redirect('/?tab=accounts')

@app.route('/accounts/update/<int:id>', methods=['POST'])
@login_required
def update_account(id):
    account = Account.query.get_or_404(id)
    if account.user_id == current_user.id:
        account.balance = float(request.form.get('balance', account.balance))
        db.session.commit()
    return redirect('/?tab=accounts')

@app.route('/accounts/set_default/<int:id>', methods=['POST'])
@login_required
def set_default_account(id):
    Account.query.filter_by(user_id=current_user.id).update({'is_default': False})
    account = Account.query.get_or_404(id)
    if account.user_id == current_user.id:
        account.is_default = True
    db.session.commit()
    return redirect('/?tab=accounts')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        if User.query.filter_by(email=email).first():
            return render_template('register.html', error='Email already registered')
        user = User(name=name, email=email, password=generate_password_hash(password, method='pbkdf2:sha256'))
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect('/')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect('/')
        return render_template('login.html', error='Invalid email or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')

with app.app_context():
    db.create_all()
    for migration_sql in [
        "ALTER TABLE expense ADD COLUMN type VARCHAR(10) DEFAULT 'expense'",
        "UPDATE expense SET type='expense' WHERE type IS NULL",
        "ALTER TABLE expense ADD COLUMN account_id INTEGER REFERENCES account(id)",
        "ALTER TABLE account ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT 0",
    ]:
        try:
            db.session.execute(db.text(migration_sql))
            db.session.commit()
        except Exception:
            pass

if __name__ == '__main__':
    app.run(debug=True, port=5001)