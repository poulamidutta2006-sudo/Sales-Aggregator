# ===================== High-Value Sales Aggregator =====================
# Flask + built-in sqlite3 only. All backend logic lives in this one file.
import sqlite3, csv, io, os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, Response, send_file

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'sales.db')
THRESHOLDS = [1000, 2500, 5000, 10000]      # options for the threshold dropdowns
FMT = '%Y-%m-%d %H:%M:%S'                    # how dates are stored in SQLite

# (days_ago, minutes_extra, product, customer, amount, type) -> 12 demo rows
SEED = [
    (0, 30, 'MacBook Pro', 'Aarav S.', 124000, 'sale'),
    (0, 95, 'Mouse', 'Amit K.', 850, 'sale'),
    (1, 60, 'iPhone 16 Pro', 'Priya M.', 119900, 'sale'),
    (2, 200, '4K Monitor', 'Rohan K.', 28500, 'sale'),
    (3, 120, 'Mechanical Keyboard', 'Anita G.', 6500, 'sale'),
    (5, 300, 'Wireless Earbuds', 'Sneha R.', 4200, 'sale'),
    (7, 90, 'Gaming Laptop', 'Vikram P.', 89000, 'sale'),
    (9, 400, 'Smartwatch', 'Neha T.', 12500, 'sale'),
    (11, 150, 'Bluetooth Speaker', 'Priya M.', 2800, 'sale'),
    (14, 250, 'Tablet', 'Rohan K.', 32000, 'sale'),
    (18, 180, 'Laptop Charger', 'Amit K.', 1500, 'refund'),
    (22, 330, 'Smartwatch', 'Neha T.', 12500, 'refund'),
]

# ---------------------------- Database helpers ----------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create tables; insert 12 demo transactions if the table is empty."""
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product TEXT NOT NULL, customer TEXT NOT NULL,
        amount REAL NOT NULL, type TEXT NOT NULL,
        created_at TEXT NOT NULL)""")
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    for k, v in [('threshold', '5000'), ('currency', 'INR'), ('auto_calc', 'on')]:
        conn.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", (k, v))
    if conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0:
        now = datetime.now()
        for days_ago, mins, product, customer, amount, kind in SEED:
            when = (now - timedelta(days=days_ago, minutes=mins)).strftime(FMT)
            conn.execute("INSERT INTO transactions (product, customer, amount, type, created_at) VALUES (?,?,?,?,?)",
                         (product, customer, amount, kind, when))
    conn.commit()
    conn.close()

def get_setting(key):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row['value'] if row else None

def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def get_threshold():
    """Threshold from the URL (?threshold=2500) if given, else the saved one in SQLite."""
    t = request.args.get('threshold', type=int)
    return t if t in THRESHOLDS else int(get_setting('threshold'))

def get_sales():
    """Fetch ONLY the last 30 calendar days (rolling window) from SQLite."""
    conn = get_db()
    rows = conn.execute("""SELECT * FROM transactions
        WHERE date(created_at) >= date('now', 'localtime', '-29 days')
        ORDER BY created_at DESC""").fetchall()
    conn.close()
    # LIST COMPREHENSION: turn each SQLite row into a normal Python dictionary
    return [dict(r) for r in rows]

# ---------------------------- Calculation helpers ----------------------------
def classify(sales, threshold):
    # LIST COMPREHENSION: add a 'category' label (Refund / Premium / Regular) to every sale
    return [dict(s, category='Refund' if s['type'] == 'refund'
                 else 'Premium' if s['amount'] > threshold else 'Regular') for s in sales]

def last_30_days():
    # LIST COMPREHENSION: build the list of the last 30 dates (oldest -> today)
    today = datetime.now().date()
    return [(today - timedelta(days=29 - i)).strftime('%Y-%m-%d') for i in range(30)]

def daily_totals(sales, kind):
    # LIST COMPREHENSION (nested): for each of the 30 days, add up amounts of that type
    return [sum([s['amount'] for s in sales if s['type'] == kind and s['created_at'][:10] == d])
            for d in last_30_days()]

def chart_labels():
    # LIST COMPREHENSION: nice labels like "Nov 12" for chart axes
    return [datetime.strptime(d, '%Y-%m-%d').strftime('%b %d') for d in last_30_days()]

# ---------------------------- Template filters ----------------------------
@app.template_filter('inr')
def inr(n):
    """Format a number the Indian way: 124000 -> ₹1,24,000"""
    n = int(round(n))
    s = str(abs(n))
    if len(s) > 3:
        last3, rest, groups = s[-3:], s[:-3], []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        s = ','.join(groups) + ',' + last3
    return ('-' if n < 0 else '') + '₹' + s

@app.template_filter('dmy')
def dmy(value):
    return datetime.strptime(value[:10], '%Y-%m-%d').strftime('%d %b %Y')

@app.template_filter('hm')
def hm(value):
    return datetime.strptime(value, FMT).strftime('%I:%M %p')

# ---------------------------- 1. Dashboard ----------------------------
@app.route('/')
def dashboard():
    threshold = get_threshold()
    sales = classify(get_sales(), threshold)

    # LIST COMPREHENSION: keep only premium sales (sales above the threshold)
    premium_sales = [s for s in sales if s['type'] == 'sale' and s['amount'] > threshold]
    # LIST COMPREHENSION: keep the remaining normal sales
    regular_sales = [s for s in sales if s['type'] == 'sale' and s['amount'] <= threshold]
    # LIST COMPREHENSION: total earned = sum of all sale amounts
    total_earned = sum([s['amount'] for s in sales if s['type'] == 'sale'])
    # LIST COMPREHENSION: total loss = sum of all refund amounts
    total_loss = sum([s['amount'] for s in sales if s['type'] == 'refund'])
    # SET COMPREHENSION: a set removes duplicates -> unique customer names
    total_customers = len({s['customer'] for s in sales})

    return render_template('dashboard.html', threshold=threshold, thresholds=THRESHOLDS,
        total_earned=total_earned, total_loss=total_loss, total_customers=total_customers,
        premium_count=len(premium_sales), regular_count=len(regular_sales),
        labels=chart_labels(), revenue=daily_totals(sales, 'sale'), latest=sales[:8])

# ---------------------------- 2. Add New Data ----------------------------
@app.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        t = request.form.get('threshold', type=int)
        if t in THRESHOLDS:
            set_setting('threshold', str(t))          # save threshold in settings table
        product = request.form.get('product', '').strip()
        customer = request.form.get('customer', '').strip()
        try:
            amount = float(request.form.get('amount', '0').replace(',', ''))
        except ValueError:
            amount = 0
        kind = 'refund' if request.form.get('type') == 'refund' else 'sale'
        if product and customer and amount > 0:
            conn = get_db()
            # created_at is filled automatically with the current date & time
            conn.execute("INSERT INTO transactions (product, customer, amount, type, created_at) VALUES (?,?,?,?,?)",
                         (product, customer, amount, kind, datetime.now().strftime(FMT)))
            conn.commit()
            conn.close()
        return redirect(url_for('add'))

    threshold = get_threshold()
    sales = classify(get_sales(), threshold)
    today = datetime.now().strftime('%Y-%m-%d')
    # LIST COMPREHENSION: keep only the entries added today
    today_entries = [s for s in sales if s['created_at'][:10] == today]
    return render_template('add.html', threshold=threshold, thresholds=THRESHOLDS, entries=today_entries)

# ---------------------------- 3. Premium Sales ----------------------------
@app.route('/premium')
def premium():
    threshold = get_threshold()
    sales = classify(get_sales(), threshold)
    # LIST COMPREHENSION: the main filter -> premium sales above the threshold
    premium_sales = [s for s in sales if s['type'] == 'sale' and s['amount'] > threshold]
    # LIST COMPREHENSION: revenue of premium sales only
    revenue = sum([s['amount'] for s in premium_sales])
    average = revenue / len(premium_sales) if premium_sales else 0
    return render_template('premium.html', threshold=threshold, thresholds=THRESHOLDS,
                           premium_sales=premium_sales, revenue=revenue, average=average)

# ---------------------------- 4. Customers ----------------------------
@app.route('/customers')
def customers():
    threshold = get_threshold()
    sales = get_sales()

    def summary(name):
        # LIST COMPREHENSION: all sales made by this one customer
        orders = [s for s in sales if s['customer'] == name and s['type'] == 'sale']
        spent = sum([s['amount'] for s in orders])
        # LIST COMPREHENSION: this customer's premium purchases
        premium_orders = [s for s in orders if s['amount'] > threshold]
        tier = 'VIP Premium' if spent > 3 * threshold else 'Premium' if spent > threshold else 'Regular'
        last = max([s['created_at'] for s in orders]) if orders else ''
        return {'name': name, 'orders': len(orders), 'spent': spent,
                'premium_orders': len(premium_orders), 'last': last, 'tier': tier}

    names = {s['customer'] for s in sales}                     # unique customer names
    # LIST COMPREHENSION: build one summary row per customer (skip refund-only customers)
    rows = [c for c in [summary(n) for n in names] if c['orders'] > 0]
    rows.sort(key=lambda c: c['spent'], reverse=True)
    # LIST COMPREHENSION: customers with at least one premium purchase
    premium_buyers = [c for c in rows if c['premium_orders'] > 0]
    # LIST COMPREHENSION: customers with more than one order
    repeat = [c for c in rows if c['orders'] > 1]
    return render_template('customers.html', rows=rows, total=len(rows),
                           premium_buyers=len(premium_buyers), repeat=len(repeat))

# ---------------------------- 5. Monthly Reports ----------------------------
@app.route('/reports')
def reports():
    threshold = get_threshold()
    sales = get_sales()
    revenue = daily_totals(sales, 'sale')
    loss = daily_totals(sales, 'refund')
    gross = sum(revenue)
    total_loss = sum(loss)
    # LIST COMPREHENSION: revenue from premium sales only (for Premium Share %)
    premium_revenue = sum([s['amount'] for s in sales if s['type'] == 'sale' and s['amount'] > threshold])
    share = round(premium_revenue / gross * 100, 1) if gross else 0
    # LIST COMPREHENSION: pair each date with its revenue (skip empty days), then take top 3
    top_days = sorted([(d, r) for d, r in zip(last_30_days(), revenue) if r > 0],
                      key=lambda x: x[1], reverse=True)[:3]
    return render_template('reports.html', labels=chart_labels(), revenue=revenue, loss=loss,
                           gross=gross, total_loss=total_loss, net=gross - total_loss,
                           share=share, top_days=top_days)

@app.route('/export.csv')
def export_csv():
    """Download the last 30 days as a real CSV file."""
    sales = get_sales()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['Date', 'Product', 'Customer', 'Amount (INR)', 'Type'])
    for s in sales:
        writer.writerow([s['created_at'], s['product'], s['customer'], s['amount'], s['type']])
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=sales_last_30_days.csv'})

# ---------------------------- 6. Settings ----------------------------
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        t = request.form.get('threshold', type=int)
        if t in THRESHOLDS:
            set_setting('threshold', str(t))
        set_setting('currency', request.form.get('currency', 'INR'))
        set_setting('auto_calc', 'on' if request.form.get('auto_calc') else 'off')
        return redirect(url_for('settings', saved=1))
    conn = get_db()
    total_records = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    conn.close()
    return render_template('settings.html', threshold=int(get_setting('threshold')), thresholds=THRESHOLDS,
                           auto_calc=get_setting('auto_calc') == 'on',
                           total_records=total_records, saved=request.args.get('saved'))

@app.route('/backup')
def backup():
    return send_file(DB_PATH, as_attachment=True, download_name='sales_backup.db')

if __name__ == '__main__':
    init_db()                      # creates tables + demo data on first run
    app.run(debug=True)