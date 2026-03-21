from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)

# Tell Flask where the database file lives
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///expenses.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# This class = one table in the database
class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    date = db.Column(db.Date, nullable=False)

    def __repr__(self):
        return f'<Expense {self.name}>'

@app.route('/')
def index():
    expenses = Expense.query.order_by(Expense.date.desc()).all()
    total = sum(expense.amount for expense in expenses)

    # Calculate total per category
    categories = ['Food', 'Transport', 'Shopping', 'Health', 'Other']
    category_totals = []
    for cat in categories:
        cat_total = sum(e.amount for e in expenses if e.category == cat)
        category_totals.append(cat_total)

    return render_template('index.html',
        expenses=expenses,
        total=total,
        categories=categories,
        category_totals=category_totals
    )

@app.route('/add', methods=['POST'])
def add_expense():
    name = request.form['name']
    amount = float(request.form['amount'])
    category = request.form['category']
    date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()

    new_expense = Expense(
        name=name,
        amount=amount,
        category=category,
        date=date
    )

    db.session.add(new_expense)
    db.session.commit()

    return redirect(url_for('index'))

@app.route('/delete/<int:expense_id>', methods=['POST'])
def delete_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    db.session.delete(expense)
    db.session.commit()
    return redirect(url_for('index'))

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)