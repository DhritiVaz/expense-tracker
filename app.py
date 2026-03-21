from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

expenses = []

@app.route('/')
def index():
    return render_template('index.html', expenses=expenses)

@app.route('/add', methods=['POST'])
def add_expense():
    name = request.form['name']
    amount = request.form['amount']
    category = request.form['category']
    date = request.form['date']

    expense = {
        'name': name,
        'amount': amount,
        'category': category,
        'date': date
    }

    expenses.append(expense)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)