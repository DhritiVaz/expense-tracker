# Expense Tracker

A full-stack personal finance web app built with Python, Flask, and PostgreSQL. Track expenses, set budgets, and get smart spending insights — with a natural language quick-add feature you won't find in most free tools.

**Live demo:** https://expense-tracker-ev7t.onrender.com

---

## Features

### Core
- Add, edit, and delete expenses with category tagging
- Filter by month and search by name
- Export all expenses to CSV

### Smart features
- **Natural language input** — type "lunch 80 today" and it adds instantly
- **Spending personality** — dynamically assigned based on your spending patterns
- **Smart insights** — weekend vs weekday spending, biggest categories, averages
- **Recurring expense detection** — automatically flags repeated expenses
- **Logging streak** — tracks consecutive days of expense logging
- **Can I afford it?** — enter a goal amount and get a personalised savings plan

### Budget & reports
- Set monthly budgets per category with visual progress bars
- Over-budget and near-limit alerts
- Monthly comparison (this month vs last month)
- Top 5 expenses, daily average, weekday vs weekend breakdown
- Monthly spending bar chart

### User accounts
- Secure registration and login
- Passwords hashed with Werkzeug
- Each user's data is completely private
- Persistent sessions with Flask-Login

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.14, Flask 3.1 |
| Database | PostgreSQL (Render), SQLite (local dev) |
| ORM | Flask-SQLAlchemy |
| Auth | Flask-Login, Werkzeug password hashing |
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| Charts | Chart.js |
| Deployment | Render (web service + PostgreSQL) |
| Version control | Git + GitHub |

---

## Running locally
```bash
# Clone the repo
git clone https://github.com/DhritiVaz/expense-tracker.git
cd expense-tracker

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Open http://localhost:5000 in your browser.

No environment variables needed for local dev — it uses SQLite automatically.

---

## Project structure
```
expense-tracker/
├── app.py              # Flask app, routes, database models
├── templates/
│   ├── index.html      # Main dashboard (Overview, Expenses, Budget, Reports tabs)
│   ├── login.html      # Login page
│   ├── register.html   # Registration page
│   └── edit.html       # Edit expense page
├── static/
│   └── style.css       # All styling, dark/light theme
├── requirements.txt    # Python dependencies
└── Procfile            # Render deployment config
```

---

## What I learned building this

- Full-stack web development with Flask and Jinja2 templating
- Relational database design with SQLAlchemy ORM
- User authentication with password hashing and session management
- Deploying a Python web app to production with PostgreSQL
- JavaScript DOM manipulation and Chart.js integration
- CSS Grid and responsive design
- Git workflow for a real project

---

## Screenshots

*(Add screenshots here)*

---

Built by Dhrit Vaz