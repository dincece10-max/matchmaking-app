# -*- coding: utf-8 -*-
"""
Created on Mon Aug 10 13:50:52 2026

@author: User
"""

import os.path
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

app = Flask(__name__)
DB_NAME = "matchmaking.db"
SCOPES = ['https://www.googleapis.com/auth/calendar']

# --- 1. SQLITE DATABASE SETUP ---
def init_db():
    """Creates the matchmaking database table if it doesn't exist."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS startups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            funding_stage TEXT NOT NULL,
            description TEXT NOT NULL,
            founder_email TEXT NOT NULL,
            is_approved INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()  # Run database initialization automatically


# --- 2. GOOGLE CALENDAR LOGIC ---
def get_calendar_credentials() -> Credentials:
    creds = None
    folder_path = os.path.dirname(os.path.abspath(__file__))
    token_file_path = os.path.join(folder_path, 'token.json')
    
    possible_names = ['credentials.json', 'credentials.json.json', 'credentials.json.txt', 'credentials']
    cred_file = None
    for name in possible_names:
        full_path = os.path.join(folder_path, name)
        if os.path.exists(full_path):
            cred_file = full_path
            break

    if os.path.exists(token_file_path):
        creds = Credentials.from_authorized_user_file(token_file_path, SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not cred_file:
                raise FileNotFoundError("Missing 'credentials.json' in project folder!")
            flow = InstalledAppFlow.from_client_secrets_file(cred_file, SCOPES)
            creds = flow.run_local_server(port=0)
            
        with open(token_file_path, 'w') as token_file:
            token_file.write(creds.to_json())
            
    return creds


def create_google_meet_event(summary: str, description: str, start_time: datetime, emails: list) -> str:
    creds = get_calendar_credentials()
    service = build('calendar', 'v3', credentials=creds)
    end_time = start_time + timedelta(minutes=30)

    event = {
        'summary': summary,
        'description': description,
        'start': {'dateTime': start_time.isoformat(), 'timeZone': 'UTC'},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': 'UTC'},
        'attendees': [{'email': email} for email in emails],
        'conferenceData': {
            'createRequest': {
                'requestId': f"meet-{int(start_time.timestamp())}",
                'conferenceSolutionKey': {'type': 'hangoutsMeet'}
            }
        }
    }

    event_result = service.events().insert(
        calendarId='primary',
        body=event,
        conferenceDataVersion=1,
        sendUpdates='all'
    ).execute()

    return event_result.get('hangoutLink')


# --- 3. WEB ROUTES ---

# Public Directory: Shows ONLY approved startups from database
@app.route('/')
def home():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    startups = cursor.execute('SELECT * FROM startups WHERE is_approved = 1').fetchall()
    conn.close()
    return render_template('index.html', startups=startups)


# Registration Form: Where founders submit startup details
# --- WEB ROUTES ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            category = request.form.get('category')
            funding_stage = request.form.get('funding_stage')
            description = request.form.get('description')
            founder_email = request.form.get('founder_email')

            print(f"📥 Received submission: {name}, {founder_email}")  # Debug print

            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO startups (name, category, funding_stage, description, founder_email, is_approved)
                VALUES (?, ?, ?, ?, ?, 0)
            ''', (name, category, funding_stage, description, founder_email))
            conn.commit()
            conn.close()

            print("✅ Successfully inserted into database!")  # Debug print
            return render_template('register.html', success=True)

        except Exception as e:
            print(f"❌ DATABASE ERROR ON REGISTER: {e}")  # Prints error in Spyder console
            return render_template('register.html', success=False, error=str(e))

    return render_template('register.html', success=False)
# Admin Dashboard: Where YOU approve pending startups
@app.route('/admin')
def admin_dashboard():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    pending = cursor.execute('SELECT * FROM startups WHERE is_approved = 0').fetchall()
    approved = cursor.execute('SELECT * FROM startups WHERE is_approved = 1').fetchall()
    conn.close()
    return render_template('admin.html', pending=pending, approved=approved)


# Approve Route: Updates database record to is_approved = 1
@app.route('/admin/approve')
def approve_startup():
    startup_id = request.args.get('id')
    if startup_id:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('UPDATE startups SET is_approved = 1 WHERE id = ?', (startup_id,))
        conn.commit()
        conn.close()
    return redirect(url_for('admin_dashboard'))


# Meeting Booking Endpoint
@app.route('/api/book-meeting', methods=['POST'])
def book_meeting():
    data = request.json
    startup_id = data.get('startup_id')

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    startup = cursor.execute('SELECT * FROM startups WHERE id = ?', (startup_id,)).fetchone()
    conn.close()

    if not startup:
        return jsonify({"success": False, "error": "Startup not found"}), 404

    try:
        meeting_time = datetime.utcnow() + timedelta(days=1)
        
        meet_url = create_google_meet_event(
            summary=f"Matchmaking Session: Investor x {startup['name']}",
            description=f"30-minute introductory meeting with {startup['name']}.",
            start_time=meeting_time,
            emails=["your_email@gmail.com", startup['founder_email']]
        )

        return jsonify({
            "success": True,
            "meet_url": meet_url,
            "startup_name": startup['name'],
            "time": meeting_time.strftime("%Y-%m-%d %H:00 UTC")
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)