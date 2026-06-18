from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from datetime import datetime, date, timedelta
import sqlite3, hashlib, csv, io, random, os

app = Flask(__name__)
app.secret_key = 'edutrack_srmap_secret_2025'
DB = os.path.join(os.path.dirname(__file__), 'edutrack.db')

# Disable Cloudflare email obfuscation which breaks onclick handlers
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def query(sql, params=(), one=False):
    conn = get_db()
    cur = conn.execute(sql, params)
    rv = cur.fetchone() if one else cur.fetchall()
    conn.close()
    return (dict(rv) if rv else None) if one else [dict(r) for r in rv]

def execute(sql, params=()):
    conn = get_db()
    cur = conn.execute(sql, params)
    conn.commit()
    lid = cur.lastrowid
    conn.close()
    return lid

def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def current_user():
    uid = session.get('user_id')
    if uid:
        return query("SELECT * FROM users WHERE id=?", (uid,), one=True)
    return None

def get_attendance_pct(student_id, subject_id=None):
    if subject_id:
        total = query("SELECT COUNT(*) as c FROM attendance WHERE student_id=? AND subject_id=?", (student_id, subject_id), one=True)['c']
        present = query("SELECT COUNT(*) as c FROM attendance WHERE student_id=? AND subject_id=? AND status='present'", (student_id, subject_id), one=True)['c']
    else:
        total = query("SELECT COUNT(*) as c FROM attendance WHERE student_id=?", (student_id,), one=True)['c']
        present = query("SELECT COUNT(*) as c FROM attendance WHERE student_id=? AND status='present'", (student_id,), one=True)['c']
    return round((present / total * 100) if total > 0 else 100, 1)

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL, department TEXT, career_goal TEXT, interests TEXT, strengths TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, code TEXT, teacher_id INTEGER, department TEXT);
    CREATE TABLE IF NOT EXISTS timetable_slots (id INTEGER PRIMARY KEY AUTOINCREMENT, subject_id INTEGER, day_of_week TEXT, start_time TEXT, end_time TEXT, room TEXT, department TEXT, is_free_period INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS attendance (id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, subject_id INTEGER, slot_id INTEGER, date TEXT NOT NULL, status TEXT DEFAULT 'absent', marked_at TEXT DEFAULT CURRENT_TIMESTAMP, marked_by TEXT DEFAULT 'manual');
    CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, title TEXT NOT NULL, description TEXT, category TEXT, priority TEXT DEFAULT 'medium', status TEXT DEFAULT 'pending', due_date TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, is_suggested INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message TEXT, type TEXT DEFAULT 'info', is_read INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS leaderboard_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER UNIQUE, score INTEGER DEFAULT 0, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    conn.commit(); conn.close()

# 20 students — names only (no F1 branding)
F1_DRIVERS = [
    ('Charles Leclerc',    'charles_leclerc',    '', 'software engineer', 'coding,math',      'precision'),
    ('Carlos Sainz',       'carlos_sainz',       '', 'data science',      'math,coding',      'analysis'),
    ('Max Verstappen',     'max_verstappen',     '', 'software engineer', 'coding,gaming',    'speed'),
    ('Lando Norris',       'lando_norris',       '', 'web developer',     'coding,gaming',    'creativity'),
    ('George Russell',     'george_russell',     '', 'data science',      'math,writing',     'consistency'),
    ('Lewis Hamilton',     'lewis_hamilton',     '', 'entrepreneur',      'design,writing',   'leadership'),
    ('Oscar Piastri',      'oscar_piastri',      '', 'web developer',     'coding,design',    'strategy'),
    ('Fernando Alonso',    'fernando_alonso',    '', 'researcher',        'math,writing',     'experience'),
    ('Lance Stroll',       'lance_stroll',       '', 'entrepreneur',      'design,sports',    'composure'),
    ('Sergio Perez',       'sergio_perez',       '', 'government',        'writing,sports',   'consistency'),
    ('Valtteri Bottas',    'valtteri_bottas',    '', 'data science',      'math,sports',      'endurance'),
    ('Nico Hulkenberg',    'nico_hulkenberg',    '', 'software engineer', 'coding,math',      'resilience'),
    ('Pierre Gasly',       'pierre_gasly',       '', 'web developer',     'design,coding',    'flair'),
    ('Esteban Ocon',       'esteban_ocon',       '', 'researcher',        'writing,math',     'determination'),
    ('Yuki Tsunoda',       'yuki_tsunoda',       '', 'software engineer', 'coding,gaming',    'aggression'),
    ('Alex Albon',         'alex_albon',         '', 'entrepreneur',      'design,sports',    'adaptability'),
    ('Zhou Guanyu',        'zhou_guanyu',        '', 'data science',      'math,design',      'precision'),
    ('Kevin Magnussen',    'kevin_magnussen',    '', 'software engineer', 'coding,sports',    'grit'),
    ('Logan Sargeant',     'logan_sargeant',     '', 'web developer',     'coding,writing',   'ambition'),
    ('Nyck de Vries',      'nyck_de_vries',      '', 'researcher',        'math,writing',     'intellect'),
]

def seed_data():
    if query("SELECT COUNT(*) as c FROM users", one=True)['c'] > 0:
        return

    # Admin
    execute("INSERT INTO users (name,email,password,role,department) VALUES (?,?,?,?,?)",
            ('Admin','admin@srmap.edu', hash_password('kimi123'), 'admin', 'CSE'))

    # Teacher
    tid = execute("INSERT INTO users (name,email,password,role,department) VALUES (?,?,?,?,?)",
                  ('Dr. Priya Sharma', 'priya.sharma@srmap.edu', hash_password('max123'), 'teacher', 'CSE'))

    # Subjects — from actual SRMAP timetable image
    subjects_info = [
        ('Industry Standard Employability Soft Skills', 'AEC 201', 'S 610'),
        ('Hands On With Python',                        'CSE 205', 'S A11 / Y 101'),
        ('Coding Skill - II',                           'CSE 206', 'JC 302'),
        ('Probability and Statistics',                  'CSE 208', 'S 612'),
        ('Database Management Systems',                 'CSE 209', 'S A11 / Y 302'),
        ('Full Stack Development',                      'CSE 211', 'S A10'),
    ]
    subj_map = {}  # code -> id
    for name, code, room in subjects_info:
        sid = execute("INSERT INTO subjects (name,code,teacher_id,department) VALUES (?,?,?,?)", (name, code, tid, 'CSE'))
        subj_map[code] = (sid, room)

    # Real timetable from SRMAP image
    # Slots: (day, start, end, subject_code, is_free)
    real_slots = [
        # Monday
        ('Monday',    '09:00','09:50', 'CSE 211', 0),
        ('Monday',    '10:00','10:50', 'CSE 211', 0),
        ('Monday',    '11:00','11:50', 'CSE 211', 0),
        ('Monday',    '12:00','12:50', None,       1),  # lunch/break
        ('Monday',    '13:00','13:50', 'CSE 206',  0),
        ('Monday',    '14:00','14:50', 'CSE 209',  0),
        ('Monday',    '15:00','15:50', 'CSE 209',  0),
        # Tuesday
        ('Tuesday',   '09:00','09:50', 'CSE 205',  0),
        ('Tuesday',   '10:00','10:50', 'CSE 208',  0),
        ('Tuesday',   '11:00','11:50', 'AEC 201',  0),
        ('Tuesday',   '12:00','12:50', None,       1),
        ('Tuesday',   '13:00','13:50', 'CSE 211',  0),
        ('Tuesday',   '14:00','14:50', 'CSE 206',  0),
        ('Tuesday',   '15:00','15:50', 'CSE 206',  0),
        # Wednesday
        ('Wednesday', '09:00','09:50', 'CSE 206',  0),
        ('Wednesday', '10:00','10:50', 'CSE 206',  0),
        ('Wednesday', '11:00','11:50', 'CSE 211',  0),
        ('Wednesday', '12:00','12:50', None,       1),
        ('Wednesday', '13:00','13:50', 'CSE 209',  0),
        ('Wednesday', '14:00','14:50', 'CSE 209',  0),
        ('Wednesday', '15:00','15:50', 'CSE 209',  0),
        # Thursday
        ('Thursday',  '09:00','09:50', 'CSE 211',  0),
        ('Thursday',  '10:00','10:50', 'CSE 211',  0),
        ('Thursday',  '11:00','11:50', 'CSE 211',  0),
        ('Thursday',  '12:00','12:50', None,       1),
        ('Thursday',  '13:00','13:50', 'CSE 205',  0),
        ('Thursday',  '14:00','14:50', 'CSE 206',  0),
        ('Thursday',  '15:00','15:50', 'AEC 201',  0),
        # Friday
        ('Friday',    '09:00','09:50', 'CSE 206',  0),
        ('Friday',    '10:00','10:50', 'CSE 208',  0),
        ('Friday',    '11:00','11:50', None,       1),  # free
        ('Friday',    '12:00','12:50', None,       1),
        ('Friday',    '13:00','13:50', 'CSE 209',  0),
        ('Friday',    '14:00','14:50', 'CSE 211',  0),
        ('Friday',    '15:00','15:50', None,       1),
    ]
    for day, start, end, code, is_free in real_slots:
        if code and code in subj_map:
            subj_id, room = subj_map[code]
        else:
            subj_id, room = None, '-'
        execute("INSERT INTO timetable_slots (subject_id,day_of_week,start_time,end_time,room,department,is_free_period) VALUES (?,?,?,?,?,?,?)",
                (subj_id, day, start, end, room, 'CSE', is_free))
    subj_ids = [v[0] for v in subj_map.values()]

    # F1 Driver Students
    stu_ids = []
    for name, uname, team, goal, interests, strengths in F1_DRIVERS:
        email = f"{uname}@srmap.edu"
        sid = execute("INSERT INTO users (name,email,password,role,department,career_goal,interests,strengths) VALUES (?,?,?,?,?,?,?,?)",
                      (name, email, hash_password('123'), 'student', 'CSE', goal, interests, strengths))
        stu_ids.append(sid)

    # Historical attendance (last 30 days)
    # Give Verstappen/Leclerc high attendance, some others low
    attendance_weights = [
        [82,10,8],  # Leclerc
        [75,17,8],  # Sainz
        [90,7,3],   # Verstappen
        [70,22,8],  # Norris
        [85,10,5],  # Russell
        [60,32,8],  # Hamilton
        [80,14,6],  # Piastri
        [55,38,7],  # Alonso
        [72,20,8],  # Stroll
        [78,15,7],  # Perez
        [88,9,3],   # Bottas
        [74,18,8],  # Hulkenberg
        [79,14,7],  # Gasly
        [65,27,8],  # Ocon
        [83,12,5],  # Tsunoda
        [77,16,7],  # Albon
        [71,21,8],  # Zhou
        [68,24,8],  # Magnussen
        [58,34,8],  # Sargeant
        [73,19,8],  # de Vries
    ]
    for idx, stu_id in enumerate(stu_ids):
        weights = attendance_weights[idx] if idx < len(attendance_weights) else [72,20,8]
        for i in range(30):
            d = (date.today() - timedelta(days=i)).isoformat()
            for subj_id in subj_ids:
                status = random.choices(['present','absent','late'], weights=weights)[0]
                execute("INSERT INTO attendance (student_id,subject_id,date,status,marked_by) VALUES (?,?,?,?,?)",
                        (stu_id,subj_id,d,status,'manual'))

    # Sample tasks for Leclerc (first student)
    for title,cat,pri,days_fwd in [
        ('Optimize Fibonacci algorithm','study','high',3),
        ('Build personal portfolio site','career','medium',7),
        ('Complete ML Kaggle notebook','career','high',5),
        ('Read System Design Primer','skill','low',14),
        ('Practice LeetCode daily','skill','medium',2),
    ]:
        execute("INSERT INTO tasks (student_id,title,category,priority,due_date) VALUES (?,?,?,?,?)",
                (stu_ids[0],title,cat,pri,(date.today()+timedelta(days=days_fwd)).isoformat()))

    # Notifications for low-attendance drivers
    for idx, stu_id in enumerate(stu_ids):
        if attendance_weights[idx][0] < 70:
            driver_name = F1_DRIVERS[idx][0]
            execute("INSERT INTO notifications (user_id,message,type) VALUES (?,?,?)",
                    (stu_id,f"⚠️ {driver_name}, your attendance has dropped below 75%. Please attend classes regularly.", 'warning'))

    # Update leaderboard
    for stu_id in stu_ids:
        pct = get_attendance_pct(stu_id)
        tasks_done = query("SELECT COUNT(*) as c FROM tasks WHERE student_id=? AND status='done'", (stu_id,), one=True)['c']
        score = int(pct * 0.7 + tasks_done * 10 + random.randint(0,50))
        execute("INSERT OR REPLACE INTO leaderboard_cache (student_id, score) VALUES (?,?)", (stu_id, score))

    print("✅ EduTrack seeded for SRMAP!")
    print("  admin@srmap.edu / kimi123")
    print("  priya.sharma@srmap.edu / max123")
    print("  charles_leclerc@srmap.edu / 123")

# ─── ROUTES ──────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if current_user(): return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    user = query("SELECT * FROM users WHERE email=? AND password=?", (data['email'], hash_password(data['password'])), one=True)
    if user:
        session['user_id'] = user['id']
        return jsonify({'success': True, 'role': user['role'], 'name': user['name']})
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    if query("SELECT id FROM users WHERE email=?", (data['email'],), one=True):
        return jsonify({'success': False, 'message': 'Email already exists'}), 400
    uid = execute("INSERT INTO users (name,email,password,role,department,career_goal,interests,strengths) VALUES (?,?,?,?,?,?,?,?)",
                  (data['name'],data['email'],hash_password(data['password']),data.get('role','student'),
                   data.get('department','CSE'),data.get('career_goal',''),data.get('interests',''),data.get('strengths','')))
    session['user_id'] = uid
    return jsonify({'success': True, 'role': data.get('role','student')})

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if not current_user(): return redirect(url_for('index'))
    return render_template('dashboard.html')

@app.route('/api/me')
def api_me():
    u = current_user()
    if not u: return jsonify({'error': 'Not logged in'}), 401
    return jsonify({k: u[k] for k in ['id','name','email','role','department','career_goal','interests']})

@app.route('/api/stats')
def api_stats():
    u = current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    if u['role'] == 'student':
        overall = get_attendance_pct(u['id'])
        tasks_done = query("SELECT COUNT(*) as c FROM tasks WHERE student_id=? AND status='done'", (u['id'],), one=True)['c']
        tasks_pending = query("SELECT COUNT(*) as c FROM tasks WHERE student_id=? AND status='pending'", (u['id'],), one=True)['c']
        unread = query("SELECT COUNT(*) as c FROM notifications WHERE user_id=? AND is_read=0", (u['id'],), one=True)['c']
        subjects = query("SELECT * FROM subjects WHERE department=?", (u['department'],))
        sub_data = [{'name': s['name'], 'code': s['code'], 'pct': get_attendance_pct(u['id'], s['id'])} for s in subjects]
        streak = query("SELECT COUNT(*) as c FROM attendance WHERE student_id=? AND status='present' AND date >= ?", (u['id'], (date.today()-timedelta(days=7)).isoformat()), one=True)['c']
        return jsonify({'overall_attendance': overall, 'tasks_done': tasks_done, 'tasks_pending': tasks_pending,
                        'unread_notifications': unread, 'subject_attendance': sub_data, 'streak': streak})
    elif u['role'] == 'teacher':
        my_s = query("SELECT COUNT(*) as c FROM subjects WHERE teacher_id=?", (u['id'],), one=True)['c']
        total_stu = query("SELECT COUNT(*) as c FROM users WHERE role='student' AND department=?", (u['department'],), one=True)['c']
        today_r = query("SELECT COUNT(*) as c FROM attendance WHERE date=?", (date.today().isoformat(),), one=True)['c']
        low_att = [s for s in query("SELECT * FROM users WHERE role='student' AND department=?", (u['department'],)) if get_attendance_pct(s['id']) < 75]
        return jsonify({'my_subjects': my_s, 'total_students': total_stu, 'today_attendance_records': today_r, 'low_attendance_count': len(low_att)})
    else:
        ts = query("SELECT COUNT(*) as c FROM users WHERE role='student'", one=True)['c']
        tt = query("SELECT COUNT(*) as c FROM users WHERE role='teacher'", one=True)['c']
        tr = query("SELECT COUNT(*) as c FROM attendance WHERE date=?", (date.today().isoformat(),), one=True)['c']
        low = len([s for s in query("SELECT * FROM users WHERE role='student'") if get_attendance_pct(s['id']) < 75])
        return jsonify({'total_students': ts, 'total_teachers': tt, 'today_records': tr, 'low_attendance_count': low})

@app.route('/api/timetable')
def api_timetable():
    u = current_user()
    if not u: return jsonify([])
    slots = query("SELECT ts.*, s.name as subject_name FROM timetable_slots ts LEFT JOIN subjects s ON ts.subject_id=s.id WHERE ts.department=?", (u['department'] or 'CSE',))
    return jsonify([{'id':s['id'],'day':s['day_of_week'],'start':s['start_time'],'end':s['end_time'],
                     'subject':s['subject_name'] if s['subject_name'] else 'Free Period','room':s['room'],'is_free':bool(s['is_free_period'])} for s in slots])

@app.route('/api/attendance', methods=['GET'])
def api_attendance():
    u = current_user()
    if not u: return jsonify([])
    if u['role'] == 'student':
        records = query("SELECT a.*, s.name as subject_name FROM attendance a JOIN subjects s ON a.subject_id=s.id WHERE a.student_id=? ORDER BY a.date DESC LIMIT 30", (u['id'],))
        return jsonify([{'date':r['date'],'subject':r['subject_name'],'status':r['status'],'marked_by':r['marked_by']} for r in records])
    subj_id = request.args.get('subject_id', type=int)
    att_date = request.args.get('date', date.today().isoformat())
    records = query("SELECT a.*, u.name as student_name FROM attendance a JOIN users u ON a.student_id=u.id WHERE a.subject_id=? AND a.date=?", (subj_id, att_date))
    return jsonify([{'student_id':r['student_id'],'student_name':r['student_name'],'status':r['status'],'marked_at':r['marked_at']} for r in records])

@app.route('/api/attendance/mark', methods=['POST'])
def mark_attendance():
    u = current_user()
    if not u or u['role'] not in ['teacher','admin']: return jsonify({'error':'Unauthorized'}), 401
    data = request.json
    for entry in data.get('students', []):
        existing = query("SELECT id FROM attendance WHERE student_id=? AND subject_id=? AND date=?",
                         (entry['student_id'],data['subject_id'],data['date']), one=True)
        if existing:
            execute("UPDATE attendance SET status=? WHERE id=?", (entry['status'], existing['id']))
        else:
            execute("INSERT INTO attendance (student_id,subject_id,date,status,marked_by) VALUES (?,?,?,?,?)",
                    (entry['student_id'],data['subject_id'],data['date'],entry['status'],data.get('method','manual')))
        if entry['status'] == 'absent':
            execute("INSERT INTO notifications (user_id,message,type) VALUES (?,?,?)",
                    (entry['student_id'],f"You were marked absent for {data.get('subject_name','a class')} on {data['date']}.",'warning'))
    # Refresh leaderboard for all students
    for entry in data.get('students',[]):
        pct = get_attendance_pct(entry['student_id'])
        tasks_done = query("SELECT COUNT(*) as c FROM tasks WHERE student_id=? AND status='done'", (entry['student_id'],), one=True)['c']
        score = int(pct * 0.7 + tasks_done * 10)
        execute("INSERT OR REPLACE INTO leaderboard_cache (student_id, score) VALUES (?,?)", (entry['student_id'], score))
    return jsonify({'success': True, 'message': f"Attendance marked for {len(data.get('students',[]))} students"})

@app.route('/api/attendance/qr-mark', methods=['POST'])
def qr_mark():
    u = current_user()
    if not u or u['role'] != 'student': return jsonify({'error':'Unauthorized'}), 401
    data = request.json
    slot = query("SELECT * FROM timetable_slots WHERE id=?", (data.get('slot_id'),), one=True)
    if not slot or not slot['subject_id']: return jsonify({'error':'No active class'}), 400
    existing = query("SELECT id FROM attendance WHERE student_id=? AND subject_id=? AND date=?",
                     (u['id'],slot['subject_id'],date.today().isoformat()), one=True)
    if existing: return jsonify({'success':False,'message':'Already marked present today'})
    execute("INSERT INTO attendance (student_id,subject_id,slot_id,date,status,marked_by) VALUES (?,?,?,?,?,?)",
            (u['id'],slot['subject_id'],slot['id'],date.today().isoformat(),'present','qr'))
    return jsonify({'success':True,'message':'✅ Attendance marked via QR!'})

@app.route('/api/tasks', methods=['GET'])
def api_tasks():
    u = current_user()
    if not u: return jsonify([])
    return jsonify([dict(t) for t in query("SELECT * FROM tasks WHERE student_id=? ORDER BY created_at DESC", (u['id'],))])

@app.route('/api/tasks', methods=['POST'])
def create_task():
    u = current_user()
    if not u: return jsonify({'error':'Unauthorized'}), 401
    d = request.json
    tid = execute("INSERT INTO tasks (student_id,title,description,category,priority,due_date,is_suggested) VALUES (?,?,?,?,?,?,?)",
                  (u['id'],d['title'],d.get('description',''),d.get('category','study'),d.get('priority','medium'),d.get('due_date'),int(d.get('is_suggested',False))))
    return jsonify({'success':True,'id':tid})

@app.route('/api/tasks/<int:tid>', methods=['PATCH'])
def update_task(tid):
    u = current_user()
    d = request.json
    if 'status' in d:
        execute("UPDATE tasks SET status=? WHERE id=? AND student_id=?", (d['status'],tid,u['id']))
        pct = get_attendance_pct(u['id'])
        tasks_done = query("SELECT COUNT(*) as c FROM tasks WHERE student_id=? AND status='done'", (u['id'],), one=True)['c']
        score = int(pct * 0.7 + tasks_done * 10)
        execute("INSERT OR REPLACE INTO leaderboard_cache (student_id, score) VALUES (?,?)", (u['id'], score))
    return jsonify({'success':True})

@app.route('/api/tasks/<int:tid>', methods=['DELETE'])
def delete_task(tid):
    u = current_user()
    execute("DELETE FROM tasks WHERE id=? AND student_id=?", (tid,u['id']))
    return jsonify({'success':True})

@app.route('/api/tasks/suggest')
def suggest_tasks():
    u = current_user()
    if not u or u['role'] != 'student': return jsonify([])
    goal = (u['career_goal'] or '').lower()
    interests = (u['interests'] or '').lower().split(',')
    suggestions = []
    career_map = {
        'data science':[('Complete a Kaggle competition','career','high'),('Learn Pandas & NumPy deeply','skill','high'),('Build an end-to-end ML pipeline','career','medium')],
        'web developer':[('Build a full-stack React project','career','high'),('Learn REST API design patterns','skill','medium'),('Deploy a project on Vercel','career','medium')],
        'software engineer':[('Solve 2 LeetCode problems today','career','high'),('Study System Design fundamentals','skill','medium'),('Contribute to an open-source repo','career','low')],
        'researcher':[('Read one research paper today','study','high'),('Write a literature review section','career','medium'),('Update your research journal','study','low')],
        'government':[('Practice 20 aptitude questions','study','high'),('Read today\'s current affairs','study','medium'),('Revise Indian Constitution basics','study','medium')],
        'entrepreneur':[('Work 30 min on your business plan','career','high'),('Study one startup case study','skill','medium'),('Reach out to one mentor today','career','medium')],
    }
    for key, tasks in career_map.items():
        if key in goal:
            suggestions += [{'title':t,'category':c,'priority':p} for t,c,p in tasks[:2]]
    interest_map = {
        'coding':[('Solve a coding challenge on HackerRank','skill','medium')],
        'design':[('Sketch a UI mockup in Figma','skill','medium')],
        'math':[('Practice 10 calculus problems','study','medium')],
        'writing':[('Write a 300-word tech article','skill','low')],
        'gaming':[('Analyze game mechanics for a project idea','skill','low')],
        'sports':[('Plan a balanced study-sports schedule','personal','low')],
    }
    for interest in interests:
        interest = interest.strip()
        for key, tasks in interest_map.items():
            if key in interest:
                suggestions += [{'title':t,'category':c,'priority':p} for t,c,p in tasks]
    pct = get_attendance_pct(u['id'])
    if pct < 75:
        suggestions.insert(0,{'title':'🚨 Attend ALL classes this week — attendance critical!','category':'study','priority':'high'})
    suggestions += [
        {'title':'Review today\'s lecture notes for 20 min','category':'study','priority':'medium'},
        {'title':'Prepare 3 questions for your next class','category':'study','priority':'low'},
    ]
    return jsonify(suggestions[:6])

@app.route('/api/subjects', methods=['GET'])
def api_subjects():
    u = current_user()
    if not u: return jsonify([])
    if u['role'] == 'teacher':
        subjects = query("SELECT * FROM subjects WHERE teacher_id=?", (u['id'],))
    else:
        subjects = query("SELECT * FROM subjects WHERE department=?", (u['department'],))
    return jsonify([{'id':s['id'],'name':s['name'],'code':s['code']} for s in subjects])

@app.route('/api/subjects', methods=['POST'])
def create_subject():
    u = current_user()
    if not u or u['role'] not in ['teacher','admin']: return jsonify({'error':'Unauthorized'}), 401
    d = request.json
    sid = execute("INSERT INTO subjects (name,code,teacher_id,department) VALUES (?,?,?,?)", (d['name'],d.get('code',''),u['id'],u['department']))
    return jsonify({'success':True,'id':sid})

@app.route('/api/students')
def api_students():
    u = current_user()
    if not u or u['role'] not in ['teacher','admin']: return jsonify({'error':'Unauthorized'}), 401
    students = query("SELECT * FROM users WHERE role='student' AND department=?", (u['department'],))
    return jsonify([{'id':s['id'],'name':s['name'],'email':s['email'],'attendance_pct':get_attendance_pct(s['id'])} for s in students])

@app.route('/api/leaderboard')
def api_leaderboard():
    u = current_user()
    if not u: return jsonify([])
    rows = query("""SELECT lc.student_id, lc.score, u.name, u.email
        FROM leaderboard_cache lc JOIN users u ON lc.student_id=u.id
        ORDER BY lc.score DESC LIMIT 10""")
    result = []
    for i, r in enumerate(rows):
        pct = get_attendance_pct(r['student_id'])
        tasks_done = query("SELECT COUNT(*) as c FROM tasks WHERE student_id=? AND status='done'", (r['student_id'],), one=True)['c']
        result.append({'rank':i+1,'name':r['name'],'email':r['email'],'score':r['score'],
                       'attendance_pct':pct,'tasks_done':tasks_done,'is_me': r['student_id']==u['id']})
    return jsonify(result)

@app.route('/api/notifications')
def api_notifications():
    u = current_user()
    if not u: return jsonify([])
    return jsonify([dict(n) for n in query("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (u['id'],))])

@app.route('/api/notifications/read-all', methods=['POST'])
def read_all():
    u = current_user()
    if not u: return jsonify({'error':'Unauthorized'}), 401
    execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (u['id'],))
    return jsonify({'success':True})

@app.route('/api/analytics/attendance-trend')
def analytics_trend():
    u = current_user()
    if not u: return jsonify([])
    days = []
    for i in range(14,-1,-1):
        d = (date.today()-timedelta(days=i)).isoformat()
        if u['role'] == 'student':
            total = query("SELECT COUNT(*) as c FROM attendance WHERE student_id=? AND date=?", (u['id'],d), one=True)['c']
            present = query("SELECT COUNT(*) as c FROM attendance WHERE student_id=? AND date=? AND status='present'", (u['id'],d), one=True)['c']
        else:
            total = query("SELECT COUNT(*) as c FROM attendance WHERE date=?", (d,), one=True)['c']
            present = query("SELECT COUNT(*) as c FROM attendance WHERE date=? AND status='present'", (d,), one=True)['c']
        days.append({'date':d,'pct':round((present/total*100) if total>0 else 0,1),'total':total,'present':present})
    return jsonify(days)

@app.route('/api/export/attendance')
def export_attendance():
    u = current_user()
    if not u or u['role'] not in ['teacher','admin']: return jsonify({'error':'Unauthorized'}), 401
    records = query("SELECT a.date, u.name, u.email, s.name as subject, a.status, a.marked_by FROM attendance a JOIN users u ON a.student_id=u.id JOIN subjects s ON a.subject_id=s.id ORDER BY a.date DESC")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date','Student Name','Email','Subject','Status','Marked By'])
    for r in records: writer.writerow([r['date'],r['name'],r['email'],r['subject'],r['status'],r['marked_by']])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', download_name='attendance_srmap.csv', as_attachment=True)

@app.route('/api/profile/update', methods=['POST'])
def update_profile():
    u = current_user()
    if not u: return jsonify({'error':'Unauthorized'}), 401
    d = request.json
    execute("UPDATE users SET career_goal=?, interests=?, strengths=? WHERE id=?",
            (d.get('career_goal',''), d.get('interests',''), d.get('strengths',''), u['id']))
    return jsonify({'success':True})

if __name__ == '__main__':
    init_db()
    seed_data()
    app.run(debug=True, port=5000)