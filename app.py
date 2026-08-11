from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3

app = Flask(__name__)
app.secret_key = "super-secret-key-change-this-in-production"
DB_NAME = "matchmaking.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users Table (Supports both Founders and Investors)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL, -- 'founder' or 'investor'
            firm_name TEXT     -- Applicable for investors/funds
        )
    ''')

    # Startups Table (Linked to Founder User ID)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS startups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            funding_stage TEXT NOT NULL,
            description TEXT NOT NULL,
            approved INTEGER DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Bookings Table (Links Investor to Startup)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            startup_id INTEGER,
            investor_id INTEGER,
            time_slot TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (startup_id) REFERENCES startups (id),
            FOREIGN KEY (investor_id) REFERENCES users (id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- AUTHENTICATION ROUTES ---

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role') # 'founder' or 'investor'
        firm_name = request.form.get('firm_name', '')

        hashed_password = generate_password_hash(password)

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (name, email, password, role, firm_name)
                VALUES (?, ?, ?, ?, ?)
            ''', (name, email, hashed_password, role, firm_name))
            user_id = cursor.lastrowid

            # If user is a founder, also create their startup record
            if role == 'founder':
                company_name = request.form.get('company_name')
                category = request.form.get('category')
                funding_stage = request.form.get('funding_stage')
                description = request.form.get('description')

                cursor.execute('''
                    INSERT INTO startups (user_id, name, category, funding_stage, description)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, company_name, category, funding_stage, description))

            conn.commit()
            conn.close()
            return redirect(url_for('login', registered=True))
        except sqlite3.IntegrityError:
            conn.close()
            return render_template('signup.html', error="Email already registered!")

    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['role'] = user['role']
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Invalid email or password.")

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# --- MAIN DIRECTORY ROUTE ---

@app.route('/')
def index():
    conn = get_db_connection()
    startups = conn.execute('SELECT * FROM startups WHERE approved = 1').fetchall()
    
    # If logged in as Founder, fetch their bookings from investors
    my_bookings = []
    if session.get('role') == 'founder':
        founder_startup = conn.execute('SELECT id FROM startups WHERE user_id = ?', (session['user_id'],)).fetchone()
        if founder_startup:
            my_bookings = conn.execute('''
                SELECT b.time_slot, u.name as investor_name, u.firm_name
                FROM bookings b
                JOIN users u ON b.investor_id = u.id
                WHERE b.startup_id = ?
            ''', (founder_startup['id'],)).fetchall()

    conn.close()
    
    available_slots = [
        "Tomorrow at 10:00 AM",
        "Tomorrow at 02:00 PM",
        "Tomorrow at 04:30 PM",
        "Thursday at 11:00 AM",
        "Friday at 03:00 PM"
    ]
    
    return render_template('index.html', startups=startups, available_slots=available_slots, my_bookings=my_bookings)


# --- BOOKING API ROUTE ---

@app.route('/api/book-meeting', methods=['POST'])
def book_meeting():
    if 'user_id' not in session or session.get('role') != 'investor':
        return jsonify({"success": False, "error": "Only logged-in investors can book meetings. Please sign in as an investor."})

    data = request.get_json()
    startup_id = data.get('startup_id')
    selected_time = data.get('time_slot')

    conn = get_db_connection()
    startup = conn.execute('SELECT * FROM startups WHERE id = ?', (startup_id,)).fetchone()

    if not startup:
        conn.close()
        return jsonify({"success": False, "error": "Startup not found."})

    # Record booking linked to investor ID
    conn.execute('INSERT INTO bookings (startup_id, investor_id, time_slot) VALUES (?, ?, ?)',
                 (startup_id, session['user_id'], selected_time))
    conn.commit()
    conn.close()

    investor_name = session.get('user_name')
    meeting_title = f"{startup['name']} x {investor_name}"

    return jsonify({
        "success": True,
        "startup_name": startup['name'],
        "investor_name": investor_name,
        "meeting_title": meeting_title,
        "time": selected_time,
        "meet_url": "https://meet.google.com/new"
    })

if __name__ == '__main__':
    app.run(debug=True)