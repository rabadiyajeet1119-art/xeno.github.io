from flask import Flask, render_template, request, jsonify
import requests
import re
import sqlite3
from datetime import datetime

app = Flask(__name__)

# =========================
# CONFIG & KEYS
# =========================
OPENROUTER_API_KEY = "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"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SERPAPI_KEY = "cd194f7cdffbf618db1e90cc998ae24d7266e0d4c9cc4537b9f0cae99283cd47"
DB_FILE = "xeno.db"

# =========================
# DATABASE HANDLER
# =========================
def init_db():
    """Create database tables if they don't exist."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Table for Chat Sessions
    c.execute('''CREATE TABLE IF NOT EXISTS sessions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    # Table for Messages
    c.execute('''CREATE TABLE IF NOT EXISTS messages 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, role TEXT, content TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

# Initialize DB on start
init_db()

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# =========================
# HELPER FUNCTIONS
# =========================
def get_system_context():
    now = datetime.now()
    return f"Current Date: {now.strftime('%A, %B %d, %Y')}. Time: {now.strftime('%I:%M %p')}."

def remove_symbols(text):
    clean = re.sub(r"[*#_`~>\[\]]", "", text).strip()
    return clean

def search_internet(query):
    print(f"\n--- Searching Google for: {query} ---")
    params = {"q": query, "engine": "google", "api_key": SERPAPI_KEY, "num": 3, "hl": "en", "gl": "in"}
    try:
        r = requests.get("https://serpapi.com/search", params=params, timeout=10)
        data = r.json() if r and r.text else {}
        if "error" in data: return None
        results = []
        if "answer_box" in data:
            ab = data["answer_box"]
            results.append(f"Direct Answer: {ab.get('title','')} {ab.get('answer','')} {ab.get('snippet','')}")
        if "organic_results" in data:
            for item in data["organic_results"][:2]:
                results.append(f"Source: {item.get('snippet','')}")
        return "\n".join(results) if results else None
    except Exception as e:
        print(f"Search Error: {e}")
        return None

# =========================
# ROUTES (CHAT HISTORY APIs)
# =========================

@app.route('/')
def home():
    return render_template('index.html')

# 1. Get All Sessions (Sidebar List)
@app.route('/sessions', methods=['GET'])
def get_sessions():
    conn = get_db_connection()
    sessions = conn.execute('SELECT * FROM sessions ORDER BY created_at DESC').fetchall()
    conn.close()
    return jsonify([dict(s) for s in sessions])

# 2. Get Specific Chat Messages
@app.route('/sessions/<int:session_id>', methods=['GET'])
def get_chat_history(session_id):
    conn = get_db_connection()
    messages = conn.execute('SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC', (session_id,)).fetchall()
    conn.close()
    return jsonify([dict(m) for m in messages])

# 3. Delete Session
@app.route('/sessions/<int:session_id>', methods=['DELETE'])
def delete_session(session_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
    conn.execute('DELETE FROM messages WHERE session_id = ?', (session_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})

# =========================
# MAIN ASK ROUTE (UPDATED)
# =========================
@app.route('/ask', methods=['POST'])
def ask():
    data = request.json
    user_input = data.get('message', '')
    session_id = data.get('session_id') # Frontend sends session ID
    
    text_lower = user_input.lower()
    
    # --- 1. Manage Session ---
    conn = get_db_connection()
    if not session_id:
        # Create new session if not exists
        title = user_input[:30] + "..." if len(user_input) > 30 else user_input
        cursor = conn.execute('INSERT INTO sessions (title) VALUES (?)', (title,))
        session_id = cursor.lastrowid
        conn.commit()
    
    # Save User Message
    conn.execute('INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)', (session_id, 'user', user_input))
    conn.commit()

    # --- 2. Search Logic ---
    search_triggers = ["price", "news", "weather", "score", "latest", "live", "date", "stock", "who is", "meaning", "cricket"]
    search_data = None
    if any(t in text_lower for t in search_triggers) or "?" in user_input:
        search_data = search_internet(user_input)

    if search_data:
        system_content = f"You are Xeno. {get_system_context()}. Google Results: {search_data}. Answer using this data."
    else:
        system_content = f"You are Xeno. {get_system_context()}. Answer based on your internal knowledge."

    final_instruction = (
        f"{system_content} "
        f"IMPORTANT: You are a bilingual assistant (Hindi and English). "
        f"If user speaks Hindi, reply in Hindi. If English, reply in English. "
        f"Do NOT use emojis. Do NOT use Markdown formatting."
    )

    messages = [{"role": "system", "content": final_instruction}, {"role": "user", "content": user_input}]
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    
    try:
        r = requests.post(OPENROUTER_URL, headers=headers, json={"model": "deepseek/deepseek-chat", "messages": messages}, timeout=15)
        if r.status_code == 200:
            ai_text = r.json()["choices"][0]["message"]["content"]
            clean_reply = remove_symbols(ai_text)
            
            # Save Bot Message
            conn.execute('INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)', (session_id, 'bot', clean_reply))
            conn.commit()
            conn.close()

            return jsonify({"reply": clean_reply, "session_id": session_id})
        else:
    return jsonify({
        "reply": f"OpenRouter Error: {r.status_code} | {r.text}"
    })
    except Exception as e:
        return jsonify({"reply": "Connection Error."})

if __name__ == '__main__':
    app.run(debug=True)
