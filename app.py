from flask import Flask, render_template, request, redirect, url_for, session, Response, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, datetime, timedelta
from collections import defaultdict
import os, calendar, csv, io, re

try:
    import pdfplumber
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

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

class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    limit = db.Column(db.Float, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    balance = db.Column(db.Float, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===== HELPERS =====

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

def _parse_date(s):
    s = str(s).strip()
    for fmt in ['%d/%m/%Y', '%d-%m-%Y', '%d %b %Y', '%d %B %Y', '%Y-%m-%d', '%d/%m/%y', '%d-%m-%y']:
        try:
            return datetime.strptime(s, fmt).date()
        except:
            continue
    return None

def _parse_amount(s):
    s = str(s).strip().upper().replace(',', '').replace(' ', '')
    txn_type = 'debit'
    if s.endswith('CR'):
        txn_type = 'credit'; s = s[:-2]
    elif s.endswith('DR'):
        txn_type = 'debit'; s = s[:-2]
    elif s.startswith('+'):
        txn_type = 'credit'; s = s[1:]
    elif s.startswith('-'):
        txn_type = 'debit'; s = s[1:]
    try:
        val = float(s)
        return (val, txn_type) if val > 0 else (None, None)
    except:
        return None, None

def categorize_description(desc):
    desc = desc.lower()
    rules = [
        ('Food',       ['swiggy','zomato','dominos','pizza','burger','mcdonalds','restaurant','cafe','food','lunch','dinner','breakfast','kitchen','dunzo']),
        ('Transport',  ['uber','ola','rapido','metro','irctc','railway','petrol','fuel','parking','toll','cab','auto','bus','flight','indigo','spicejet']),
        ('Shopping',   ['amazon','flipkart','myntra','meesho','ajio','shop','mall','retail','market','blinkit','zepto','instamart','bigbasket']),
        ('Health',     ['hospital','clinic','pharmacy','medic','doctor','apollo','fortis','gym','fitness','1mg','pharmeasy','wellness']),
        ('Salary',     ['salary','sal credit','payroll','stipend','wages']),
        ('Investment', ['mutual fund','mf purchase','sip','zerodha','groww','stock','nse','bse','demat']),
    ]
    for cat, keywords in rules:
        if any(k in desc for k in keywords):
            return cat
    return 'Other'

def parse_bank_statement(pdf_file):
    if not PDF_SUPPORT:
        return []
    transactions = []

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            parsed_from_table = False

            for table in (tables or []):
                if not table or len(table) < 2:
                    continue
                header = [str(c).lower().strip() if c else '' for c in (table[0] or [])]
                # detect columns
                date_col  = next((i for i, h in enumerate(header) if 'date' in h), None)
                desc_col  = next((i for i, h in enumerate(header) if any(k in h for k in ['narration','description','particulars','details','remarks','txn'])), None)
                debit_col = next((i for i, h in enumerate(header) if any(k in h for k in ['debit','withdrawal','dr'])), None)
                cred_col  = next((i for i, h in enumerate(header) if any(k in h for k in ['credit','deposit','cr'])), None)
                amt_col   = next((i for i, h in enumerate(header) if h in ['amount','amt']), None)

                start = 1 if date_col is not None else 0
                for row in table[start:]:
                    if not row or all(not c for c in row):
                        continue
                    cells = [str(c).strip() if c else '' for c in row]

                    d = _parse_date(cells[date_col]) if date_col is not None and date_col < len(cells) else None
                    if d is None:
                        d = _parse_date(cells[0])
                    if d is None:
                        continue

                    desc = ''
                    if desc_col is not None and desc_col < len(cells):
                        desc = cells[desc_col]
                    if not desc:
                        non_num = [c for c in cells[1:] if c and not re.match(r'^[\d,.\s]+(?:CR|DR)?$', c, re.I)]
                        desc = max(non_num, key=len, default='Transaction')

                    amount, txn_type = None, None
                    if debit_col is not None and debit_col < len(cells) and cells[debit_col]:
                        v, _ = _parse_amount(cells[debit_col])
                        if v: amount, txn_type = v, 'debit'
                    if amount is None and cred_col is not None and cred_col < len(cells) and cells[cred_col]:
                        v, _ = _parse_amount(cells[cred_col])
                        if v: amount, txn_type = v, 'credit'
                    if amount is None and amt_col is not None and amt_col < len(cells):
                        amount, txn_type = _parse_amount(cells[amt_col])
                    if amount is None:
                        for cell in reversed(cells):
                            v, t = _parse_amount(cell)
                            if v: amount, txn_type = v, t or 'debit'; break

                    if d and amount:
                        parsed_from_table = True
                        transactions.append({
                            'date': str(d),
                            'description': desc[:80] or 'Transaction',
                            'amount': round(amount, 2),
                            'type': 'income' if txn_type == 'credit' else 'expense',
                            'category': categorize_description(desc),
                        })

            if not parsed_from_table:
                text = page.extract_text() or ''
                date_re = re.compile(
                    r'\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4})\b',
                    re.I
                )
                amt_re = re.compile(r'([\d,]+\.?\d*)\s*(Cr|Dr)?', re.I)
                for line in text.split('\n'):
                    line = line.strip()
                    dm = date_re.search(line)
                    if not dm:
                        continue
                    d = _parse_date(dm.group())
                    if not d:
                        continue
                    matches = amt_re.findall(line)
                    amount, txn_type = None, 'debit'
                    for amt_s, suffix in reversed(matches):
                        v, _ = _parse_amount(amt_s + suffix)
                        if v:
                            amount = round(v, 2)
                            txn_type = 'credit' if suffix.upper() == 'CR' else 'debit'
                            break
                    if not amount:
                        continue
                    desc = line[dm.end():].strip()
                    desc = re.sub(r'[\d,]+\.?\d*\s*(Cr|Dr)?', '', desc, flags=re.I).strip()
                    desc = re.sub(r'\s+', ' ', desc)[:80] or 'Transaction'
                    transactions.append({
                        'date': str(d),
                        'description': desc,
                        'amount': amount,
                        'type': 'income' if txn_type == 'credit' else 'expense',
                        'category': categorize_description(desc),
                    })

    return transactions

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
    total_balance = sum(a.balance for a in accounts)
    balance_after_spending = total_balance - total_expenses + total_income

    recurring_names = get_recurring(all_transactions)
    streak = get_streak(all_transactions)
    insights = get_insights(all_transactions)
    personality = get_personality(all_transactions)

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
        total_balance=total_balance,
        balance_after_spending=balance_after_spending,
        recurring_names=recurring_names,
        streak=streak,
        insights=insights,
        personality=personality,
        search=search,
        month_filter=month_filter,
    )

@app.route('/add', methods=['POST'])
@login_required
def add():
    name = request.form.get('name', '').strip()
    amount = request.form.get('amount', '0')
    category = request.form.get('category', 'Other')
    date_str = request.form.get('date', str(date.today()))
    type_ = request.form.get('type', 'expense')
    tab = request.form.get('tab', 'expenses')

    try:
        entry = Expense(
            name=name,
            amount=float(amount),
            category=category,
            date=datetime.strptime(date_str, '%Y-%m-%d').date(),
            type=type_,
            user_id=current_user.id
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as e:
        print(f"Error adding: {e}")

    return redirect(f'/?tab={tab}')

@app.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id):
    entry = Expense.query.get_or_404(id)
    if entry.user_id == current_user.id:
        tab = entry.type  # redirect back to income or expenses tab
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
        entry.name = request.form.get('name', entry.name)
        entry.amount = float(request.form.get('amount', entry.amount))
        entry.category = request.form.get('category', entry.category)
        entry.type = request.form.get('type', entry.type)
        date_str = request.form.get('date')
        if date_str:
            entry.date = datetime.strptime(date_str, '%Y-%m-%d').date()
        db.session.commit()
        return redirect(f'/?tab={entry.type}s')
    return render_template('edit.html', expense=entry)

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

@app.route('/upload-statement', methods=['GET', 'POST'])
@login_required
def upload_statement():
    if not PDF_SUPPORT:
        return render_template('upload_statement.html', transactions=None,
                               error='pdfplumber is not installed on this server.')
    if request.method == 'GET':
        return render_template('upload_statement.html', transactions=None, error=None)

    f = request.files.get('pdf')
    if not f or not f.filename.lower().endswith('.pdf'):
        return render_template('upload_statement.html', transactions=None,
                               error='Please upload a valid PDF file.')
    try:
        txns = parse_bank_statement(f)
    except Exception as e:
        return render_template('upload_statement.html', transactions=None,
                               error=f'Could not parse PDF: {e}')

    if not txns:
        return render_template('upload_statement.html', transactions=None,
                               error='No transactions detected. Try a different statement or check the format.')

    existing_keys = {(str(e.date), e.amount) for e in Expense.query.filter_by(user_id=current_user.id).all()}
    for t in txns:
        t['duplicate'] = (t['date'], t['amount']) in existing_keys

    expense_cats  = ['Food', 'Transport', 'Shopping', 'Health', 'Other']
    income_cats   = ['Salary', 'Freelance', 'Gift', 'Investment', 'Other']
    return render_template('upload_statement.html', transactions=txns, error=None,
                           expense_cats=expense_cats, income_cats=income_cats)


@app.route('/import-statement', methods=['POST'])
@login_required
def import_statement():
    names      = request.form.getlist('name')
    amounts    = request.form.getlist('amount')
    dates      = request.form.getlist('date')
    categories = request.form.getlist('category')
    types      = request.form.getlist('type')

    imported = 0
    for i in range(len(names)):
        try:
            entry = Expense(
                name=names[i][:100],
                amount=float(amounts[i]),
                category=categories[i],
                date=datetime.strptime(dates[i], '%Y-%m-%d').date(),
                type=types[i],
                user_id=current_user.id
            )
            db.session.add(entry)
            imported += 1
        except Exception:
            continue
    db.session.commit()
    return redirect(f'/?tab=expenses&imported={imported}')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        if User.query.filter_by(email=email).first():
            return render_template('register.html', error='Email already registered')
        user = User(name=name, email=email, password=generate_password_hash(password))
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
    # Migrate: add type column if it doesn't exist, then backfill
    try:
        db.session.execute(db.text("ALTER TABLE expense ADD COLUMN type VARCHAR(10) DEFAULT 'expense'"))
        db.session.commit()
    except:
        pass  # column already exists
    try:
        db.session.execute(db.text("UPDATE expense SET type='expense' WHERE type IS NULL"))
        db.session.commit()
    except:
        pass

if __name__ == '__main__':
    app.run(debug=True)