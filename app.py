from flask import Flask, render_template, request, redirect, url_for, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import extract as db_extract
from datetime import datetime, date
from collections import Counter
import calendar, csv, io

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///expenses.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    date = db.Column(db.Date, nullable=False)

class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), unique=True, nullable=False)
    limit = db.Column(db.Float, nullable=False)

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

@app.route('/')
def index():
    month_filter = request.args.get('month', '')
    search = request.args.get('search', '')
    query = Expense.query
    if month_filter:
        y, m = month_filter.split('-')
        query = query.filter(db_extract('year', Expense.date)==int(y), db_extract('month', Expense.date)==int(m))
    if search:
        query = query.filter(Expense.name.ilike(f'%{search}%'))
    expenses = query.order_by(Expense.date.desc()).all()
    all_expenses = Expense.query.all()
    total = sum(e.amount for e in expenses)

    categories = ['Food', 'Transport', 'Shopping', 'Health', 'Other']
    category_totals = [sum(e.amount for e in expenses if e.category == c) for c in categories]

    # Monthly comparison
    today = date.today()
    this_m = sum(e.amount for e in all_expenses if e.date.year == today.year and e.date.month == today.month)
    last_month = today.month - 1 if today.month > 1 else 12
    last_year = today.year if today.month > 1 else today.year - 1
    last_m = sum(e.amount for e in all_expenses if e.date.year == last_year and e.date.month == last_month)
    max_m = max(this_m, last_m, 1)
    monthly_diff = this_m - last_m

    # Budget data
    budgets = {b.category: b.limit for b in Budget.query.all()}
    budget_data = []
    for cat in categories:
        spent = sum(e.amount for e in all_expenses if e.category == cat)
        budget_data.append({'name': cat, 'spent': spent, 'limit': budgets.get(cat, 0)})

    # Reports data
    biggest = max(all_expenses, key=lambda e: e.amount) if all_expenses else None
    top_expenses = sorted(all_expenses, key=lambda e: e.amount, reverse=True)[:5]
    category_breakdown = [(c, sum(e.amount for e in all_expenses if e.category == c)) for c in categories if any(e.category == c for e in all_expenses)]

    # Monthly totals (last 6 months)
    monthly_totals = []
    for i in range(5, -1, -1):
        m = (today.month - i - 1) % 12 + 1
        y = today.year - ((today.month - i - 1) // 12 + (1 if (today.month - i - 1) < 0 else 0))
        mt = sum(e.amount for e in all_expenses if e.date.month == m and e.date.year == y)
        if mt > 0:
            monthly_totals.append((calendar.month_abbr[m] + f' {y}', mt))

    # Daily average this month
    days_in_month = today.day
    daily_avg = this_m / days_in_month if days_in_month > 0 else 0

    # Weekday vs weekend
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
        recent_expenses=all_expenses[:8] if all_expenses else []
    )

@app.route('/add', methods=['POST'])
def add_expense():
    db.session.add(Expense(
        name=request.form['name'],
        amount=float(request.form['amount']),
        category=request.form['category'],
        date=datetime.strptime(request.form['date'], '%Y-%m-%d').date()
    ))
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/delete/<int:eid>', methods=['POST'])
def delete_expense(eid):
    db.session.delete(Expense.query.get_or_404(eid))
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/edit/<int:eid>', methods=['GET', 'POST'])
def edit_expense(eid):
    expense = Expense.query.get_or_404(eid)
    if request.method == 'POST':
        expense.name = request.form['name']
        expense.amount = float(request.form['amount'])
        expense.category = request.form['category']
        expense.date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('edit.html', expense=expense)

@app.route('/set_budget', methods=['POST'])
def set_budget():
    cat = request.form['category']
    limit = float(request.form['limit'])
    budget = Budget.query.filter_by(category=cat).first()
    if budget:
        budget.limit = limit
    else:
        db.session.add(Budget(category=cat, limit=limit))
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/export')
def export_csv():
    expenses = Expense.query.order_by(Expense.date.desc()).all()
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

if __name__ == '__main__':
    app.run(debug=True)