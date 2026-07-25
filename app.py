from flask import Flask, request, jsonify, send_file, session, redirect, url_for, render_template_string
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import shutil
import json
import re
import hashlib
import secrets
from datetime import datetime
from werkzeug.utils import secure_filename
from functools import wraps
import logging

# ===== LOGGING SETUP =====
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='.', static_url_path='')

# ===== SECRET KEY =====
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
CORS(app)

# ===== DATABASE CONFIGURATION =====
# Try to get DATABASE_URL from environment (Render.com provides this)
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    # Parse DATABASE_URL for Render.com PostgreSQL
    # Render provides DATABASE_URL in format: postgresql://user:password@host:port/dbname
    logger.info(f"Using DATABASE_URL from environment")
    
    # You can use the URL directly with psycopg2
    def get_db_connection():
        try:
            import urllib.parse
            url = urllib.parse.urlparse(DATABASE_URL)
            
            conn = psycopg2.connect(
                host=url.hostname,
                database=url.path[1:],
                user=url.username,
                password=url.password,
                port=url.port or 5432
            )
            return conn
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            return None
else:
    # Fallback to individual environment variables or local development
    logger.info("Using individual DB environment variables")
    
    DB_CONFIG = {
        'host': os.environ.get('DB_HOST', 'localhost'),
        'database': os.environ.get('DB_NAME', 'jid_dashboard'),
        'user': os.environ.get('DB_USER', 'postgres'),
        'password': os.environ.get('DB_PASSWORD', ''),
        'port': os.environ.get('DB_PORT', '5432')
    }
    
    def get_db_connection():
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            return conn
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            return None

# ===== FILE STORAGE CONFIGURATION =====
FILE_BASE_PATH = os.path.join(os.path.dirname(__file__), 'files')
ALLOWED_EXTENSIONS = {'pdf', 'xml', 'txt', 'json'}
os.makedirs(FILE_BASE_PATH, exist_ok=True)

# ===== PASSWORD HASHING =====
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, hashed):
    return hash_password(password) == hashed

# ===== LOGIN DECORATORS =====
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

# ===== HELPER FUNCTIONS =====
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_jid_folder(jid_code, stage_name):
    folder = os.path.join(FILE_BASE_PATH, stage_name, jid_code)
    os.makedirs(folder, exist_ok=True)
    return folder

def save_file(file, jid_code, stage_name, file_type):
    if not file or not allowed_file(file.filename):
        return None
    
    original_filename = secure_filename(file.filename)
    ext = original_filename.rsplit('.', 1)[1].lower()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    file_type_mapping = {
        'correction': 'correction.pdf',
        'sample': 'sample.pdf',
        'sample_xml': 'sample.xml',
        'final_pdf': 'final.pdf',
        'final_xml': 'final.xml'
    }
    
    filename = file_type_mapping.get(file_type, f"{file_type}_{timestamp}.{ext}")
    jid_folder = get_jid_folder(jid_code, stage_name)
    file_path = os.path.join(jid_folder, filename)
    
    if os.path.exists(file_path):
        backup_path = f"{file_path}.{timestamp}.bak"
        os.rename(file_path, backup_path)
    
    file.save(file_path)
    return file_path

# ===== AUTH PAGES =====
# [SIGNUP_PAGE and LOGIN_PAGE HTML - same as previous version]
# For brevity, I'm including them as variables

# ===== SIGNUP PAGE =====
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        role = request.form.get('role', 'user')
        
        if not username or not password:
            return render_template_string(SIGNUP_PAGE, error='Username and password are required')
        
        if len(username) < 3:
            return render_template_string(SIGNUP_PAGE, error='Username must be at least 3 characters')
        
        if len(password) < 6:
            return render_template_string(SIGNUP_PAGE, error='Password must be at least 6 characters')
        
        if password != confirm_password:
            return render_template_string(SIGNUP_PAGE, error='Passwords do not match')
        
        conn = get_db_connection()
        if not conn:
            return render_template_string(SIGNUP_PAGE, error='Database connection failed')
        
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id FROM users WHERE username = %s", (username,))
                if cur.fetchone():
                    return render_template_string(SIGNUP_PAGE, error='Username already exists')
                
                if email:
                    cur.execute("SELECT id FROM users WHERE email = %s", (email,))
                    if cur.fetchone():
                        return render_template_string(SIGNUP_PAGE, error='Email already registered')
                
                hashed_password = hash_password(password)
                cur.execute("""
                    INSERT INTO users (username, password_hash, full_name, email, role, created_at)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    RETURNING id, username, role
                """, (username, hashed_password, full_name, email, role))
                
                user = cur.fetchone()
                conn.commit()
                
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user['role']
                session['full_name'] = full_name or username
                
                return redirect(url_for('dashboard'))
                
        except Exception as e:
            conn.rollback()
            logger.error(f"Signup error: {e}")
            return render_template_string(SIGNUP_PAGE, error=f'Error creating account: {str(e)}')
        finally:
            conn.close()
    
    return render_template_string(SIGNUP_PAGE, error=None)

# ===== LOGIN PAGE =====
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            return render_template_string(LOGIN_PAGE, error='Username and password are required')
        
        conn = get_db_connection()
        if not conn:
            logger.error("Database connection failed during login")
            return render_template_string(LOGIN_PAGE, error='Database connection failed')
        
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, username, password_hash, full_name, role, is_active
                    FROM users 
                    WHERE username = %s
                """, (username,))
                user = cur.fetchone()
                
                if not user:
                    logger.warning(f"Login attempt with unknown username: {username}")
                    return render_template_string(LOGIN_PAGE, error='Invalid username or password')
                
                if not user.get('is_active', True):
                    return render_template_string(LOGIN_PAGE, error='Account is deactivated. Please contact admin.')
                
                if not verify_password(password, user['password_hash']):
                    logger.warning(f"Invalid password for user: {username}")
                    return render_template_string(LOGIN_PAGE, error='Invalid username or password')
                
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user['role']
                session['full_name'] = user['full_name'] or user['username']
                
                cur.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = %s", (user['id'],))
                conn.commit()
                
                logger.info(f"User logged in successfully: {username}")
                return redirect(url_for('dashboard'))
                
        except Exception as e:
            logger.error(f"Login error: {e}")
            return render_template_string(LOGIN_PAGE, error=f'Login error: {str(e)}')
        finally:
            conn.close()
    
    return render_template_string(LOGIN_PAGE, error=None)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ===== DASHBOARD =====
@app.route('/')
@login_required
def dashboard():
    role = session.get('role', 'user')
    username = session.get('username', 'User')
    full_name = session.get('full_name', username)
    return render_template_string(DASHBOARD_PAGE, role=role, username=username, full_name=full_name)

# ===== API ROUTES =====
@app.route('/api/stages', methods=['GET'])
@login_required
def get_stages():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM stages ORDER BY sort_order")
            stages = cur.fetchall()
            return jsonify(stages)
    except Exception as e:
        logger.error(f"Error getting stages: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/jids', methods=['GET'])
@login_required
def get_jids():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT 
                    j.id,
                    j.jid_code,
                    j.status,
                    j.created_at,
                    j.updated_at,
                    s.stage_name,
                    COUNT(DISTINCT f.id) as file_count,
                    COUNT(DISTINCT c.id) as checklist_total,
                    SUM(CASE WHEN c.is_checked THEN 1 ELSE 0 END) as checklist_done
                FROM jids j
                JOIN stages s ON j.stage_id = s.id
                LEFT JOIN files f ON j.id = f.jid_id
                LEFT JOIN checklist_items c ON j.id = c.jid_id
                GROUP BY j.id, j.jid_code, j.status, j.created_at, j.updated_at, s.stage_name
                ORDER BY s.stage_name, j.jid_code
            """)
            jids = cur.fetchall()
            result = []
            for jid in jids:
                total = jid['checklist_total'] or 0
                done = jid['checklist_done'] or 0
                progress = (done / total * 100) if total > 0 else 0
                result.append({
                    'id': jid['id'],
                    'jid_code': jid['jid_code'],
                    'stage_name': jid['stage_name'],
                    'status': jid['status'],
                    'file_count': jid['file_count'] or 0,
                    'checklist_progress': round(progress, 1),
                    'created_at': jid['created_at'],
                    'updated_at': jid['updated_at']
                })
            return jsonify(result)
    except Exception as e:
        logger.error(f"Error getting JIDs: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/jids', methods=['POST'])
@admin_required
def create_jid():
    data = request.json
    jid_code = data.get('jid_code', '').upper()
    stage_name = data.get('stage_name')
    if not jid_code or not stage_name:
        return jsonify({'error': 'JID code and stage are required'}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM stages WHERE stage_name = %s", (stage_name,))
            stage = cur.fetchone()
            if not stage:
                return jsonify({'error': f'Stage "{stage_name}" not found'}), 400
            stage_id = stage['id']
            cur.execute("SELECT id FROM jids WHERE jid_code = %s", (jid_code,))
            if cur.fetchone():
                return jsonify({'error': f'JID "{jid_code}" already exists'}), 400
            cur.execute("INSERT INTO jids (jid_code, stage_id, status) VALUES (%s, %s, 'pending') RETURNING id", (jid_code, stage_id))
            jid_id = cur.fetchone()['id']
            conn.commit()
            return jsonify({'id': jid_id, 'jid_code': jid_code, 'stage_name': stage_name, 'message': 'JID created successfully'}), 201
    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating JID: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/jids/<int:jid_id>', methods=['DELETE'])
@admin_required
def delete_jid(jid_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT j.*, s.stage_name FROM jids j JOIN stages s ON j.stage_id = s.id WHERE j.id = %s", (jid_id,))
            jid = cur.fetchone()
            if not jid:
                return jsonify({'error': 'JID not found'}), 404
            jid_code = jid['jid_code']
            stage_name = jid['stage_name']
            cur.execute("DELETE FROM jids WHERE id = %s", (jid_id,))
            conn.commit()
            jid_folder = os.path.join(FILE_BASE_PATH, stage_name, jid_code)
            if os.path.exists(jid_folder):
                shutil.rmtree(jid_folder)
            return jsonify({'message': 'JID deleted successfully'})
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting JID: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/materials/<int:jid_id>', methods=['GET'])
@login_required
def get_materials(jid_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT f.*, j.jid_code FROM files f JOIN jids j ON f.jid_id = j.id WHERE f.jid_id = %s ORDER BY f.file_type", (jid_id,))
            files = cur.fetchall()
            for file in files:
                file['download_url'] = f"/api/files/download/{file['id']}"
            return jsonify(files)
    except Exception as e:
        logger.error(f"Error getting materials: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/upload/<int:jid_id>', methods=['POST'])
@admin_required
def upload_file(jid_id):
    file_type = request.form.get('file_type')
    file = request.files.get('file')
    if not file or not file_type:
        return jsonify({'error': 'File and file_type are required'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT j.*, s.stage_name FROM jids j JOIN stages s ON j.stage_id = s.id WHERE j.id = %s", (jid_id,))
            jid = cur.fetchone()
            if not jid:
                return jsonify({'error': 'JID not found'}), 404
            jid_code = jid['jid_code']
            stage_name = jid['stage_name']
        file_path = save_file(file, jid_code, stage_name, file_type)
        if not file_path:
            return jsonify({'error': 'Failed to save file'}), 500
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM files WHERE jid_id = %s AND file_type = %s", (jid_id, file_type))
            existing = cur.fetchone()
            if existing:
                cur.execute("UPDATE files SET filename = %s, file_path = %s, version = version + 1, uploaded_at = CURRENT_TIMESTAMP WHERE jid_id = %s AND file_type = %s RETURNING id", (file.filename, file_path, jid_id, file_type))
                file_id = cur.fetchone()[0]
            else:
                cur.execute("INSERT INTO files (jid_id, file_type, filename, file_path) VALUES (%s, %s, %s, %s) RETURNING id", (jid_id, file_type, file.filename, file_path))
                file_id = cur.fetchone()[0]
            conn.commit()
            return jsonify({'id': file_id, 'file_type': file_type, 'filename': file.filename, 'message': 'File uploaded successfully'}), 201
    except Exception as e:
        conn.rollback()
        logger.error(f"Error uploading file: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/files/download/<int:file_id>', methods=['GET'])
@login_required
def download_file(file_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM files WHERE id = %s", (file_id,))
            file = cur.fetchone()
            if not file:
                return jsonify({'error': 'File not found'}), 404
            if not os.path.exists(file['file_path']):
                return jsonify({'error': 'File not found on server'}), 404
            return send_file(file['file_path'], as_attachment=False, download_name=file['filename'])
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/files/<int:file_id>', methods=['DELETE'])
@admin_required
def delete_file(file_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT file_path FROM files WHERE id = %s", (file_id,))
            result = cur.fetchone()
            if not result:
                return jsonify({'error': 'File not found'}), 404
            file_path = result[0]
            cur.execute("DELETE FROM files WHERE id = %s", (file_id,))
            conn.commit()
            if os.path.exists(file_path):
                os.remove(file_path)
            return jsonify({'message': 'File deleted successfully'})
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting file: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/checklist/<int:jid_id>/<string:sub_stage>', methods=['GET'])
@login_required
def get_checklist_by_stage(jid_id, sub_stage):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT c.* FROM checklist_items c JOIN stages s ON c.stage_id = s.id WHERE c.jid_id = %s AND s.stage_name = %s ORDER BY c.id", (jid_id, sub_stage))
            checklist = cur.fetchall()
            return jsonify(checklist)
    except Exception as e:
        logger.error(f"Error getting checklist: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/checklist/<int:jid_id>/<string:sub_stage>/<string:item_key>', methods=['PUT'])
@admin_required
def update_checklist_item(jid_id, sub_stage, item_key):
    data = request.json
    is_checked = data.get('is_checked', False)
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE checklist_items SET is_checked = %s, updated_at = CURRENT_TIMESTAMP
                FROM stages s
                WHERE checklist_items.stage_id = s.id AND s.stage_name = %s
                AND checklist_items.jid_id = %s AND checklist_items.item_key = %s
                RETURNING checklist_items.id
            """, (is_checked, sub_stage, jid_id, item_key))
            if not cur.fetchone():
                return jsonify({'error': 'Checklist item not found'}), 404
            conn.commit()
            return jsonify({'message': 'Checklist updated successfully'})
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating checklist: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/checklist/<int:jid_id>/<string:sub_stage>/reset', methods=['POST'])
@admin_required
def reset_checklist_by_stage(jid_id, sub_stage):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE checklist_items SET is_checked = FALSE, updated_at = CURRENT_TIMESTAMP
                FROM stages s
                WHERE checklist_items.stage_id = s.id AND s.stage_name = %s
                AND checklist_items.jid_id = %s
            """, (sub_stage, jid_id))
            conn.commit()
            return jsonify({'message': 'Checklist reset successfully'})
    except Exception as e:
        conn.rollback()
        logger.error(f"Error resetting checklist: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/online/<int:jid_id>', methods=['GET'])
@login_required
def get_online_link(jid_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM online_links WHERE jid_id = %s ORDER BY updated_at DESC LIMIT 1", (jid_id,))
            link = cur.fetchone()
            return jsonify(link if link else {})
    except Exception as e:
        logger.error(f"Error getting online link: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/online/<int:jid_id>', methods=['POST'])
@admin_required
def update_online_link(jid_id):
    data = request.json
    link_url = data.get('link_url')
    if not link_url:
        return jsonify({'error': 'Link URL is required'}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM jids WHERE id = %s", (jid_id,))
            if not cur.fetchone():
                return jsonify({'error': 'JID not found'}), 404
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO online_links (jid_id, link_url, verified, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (jid_id) 
                DO UPDATE SET link_url = EXCLUDED.link_url, verified = EXCLUDED.verified, updated_at = CURRENT_TIMESTAMP
            """, (jid_id, link_url, False))
            conn.commit()
        return jsonify({'message': 'Online link updated successfully'})
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating online link: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/online/<int:jid_id>', methods=['DELETE'])
@admin_required
def delete_online_link(jid_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM online_links WHERE jid_id = %s", (jid_id,))
            conn.commit()
            return jsonify({'message': 'Online link deleted successfully'})
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting online link: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/export/<int:jid_id>', methods=['GET'])
@login_required
def export_jid_data(jid_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT j.*, s.stage_name FROM jids j JOIN stages s ON j.stage_id = s.id WHERE j.id = %s", (jid_id,))
            jid = cur.fetchone()
            if not jid:
                return jsonify({'error': 'JID not found'}), 404
            cur.execute("SELECT * FROM files WHERE jid_id = %s", (jid_id,))
            files = cur.fetchall()
            cur.execute("SELECT c.*, s.stage_name FROM checklist_items c JOIN stages s ON c.stage_id = s.id WHERE c.jid_id = %s", (jid_id,))
            checklists = cur.fetchall()
            cur.execute("SELECT * FROM online_links WHERE jid_id = %s", (jid_id,))
            online_link = cur.fetchone()
            export_data = {
                'jid': jid,
                'files': files,
                'checklists': checklists,
                'online_link': online_link,
                'exported_at': datetime.now().isoformat()
            }
            return jsonify(export_data)
    except Exception as e:
        logger.error(f"Error exporting JID data: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# ===== DATABASE INITIALIZATION =====
def create_users_table():
    conn = get_db_connection()
    if not conn:
        logger.error("Cannot connect to database to create users table")
        return
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    full_name VARCHAR(100),
                    email VARCHAR(100),
                    role VARCHAR(20) DEFAULT 'user',
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP
                )
            """)
            conn.commit()
            logger.info("✅ Users table created successfully")
    except Exception as e:
        logger.error(f"Error creating users table: {e}")
    finally:
        conn.close()

def create_default_users():
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Check if admin exists
            cur.execute("SELECT id FROM users WHERE username = 'admin'")
            if not cur.fetchone():
                hashed_password = hash_password('admin123')
                cur.execute("""
                    INSERT INTO users (username, password_hash, full_name, role)
                    VALUES (%s, %s, %s, %s)
                """, ('admin', hashed_password, 'Administrator', 'admin'))
                logger.info("✅ Created admin user: admin / admin123")
            
            # Check if user exists
            cur.execute("SELECT id FROM users WHERE username = 'user'")
            if not cur.fetchone():
                hashed_password = hash_password('user123')
                cur.execute("""
                    INSERT INTO users (username, password_hash, full_name, role)
                    VALUES (%s, %s, %s, %s)
                """, ('user', hashed_password, 'Demo User', 'user'))
                logger.info("✅ Created user: user / user123")
            
            conn.commit()
            
    except Exception as e:
        logger.error(f"Error creating default users: {e}")
    finally:
        conn.close()

# ===== HEALTH CHECK FOR RENDER =====
@app.route('/health')
def health_check():
    """Health check endpoint for Render.com"""
    try:
        conn = get_db_connection()
        if conn:
            conn.close()
            return jsonify({'status': 'healthy', 'database': 'connected'}), 200
        else:
            return jsonify({'status': 'unhealthy', 'database': 'disconnected'}), 500
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

# ===== MAIN =====
if __name__ == '__main__':
    print("=" * 60)
    print("🚀 JID Management Dashboard - Production")
    print("=" * 60)
    print(f"📁 Files stored in: {FILE_BASE_PATH}")
    print("=" * 60)
    
    # Create users table
    create_users_table()
    
    # Create default users
    create_default_users()
    
    # Get port from environment (Render sets this)
    port = int(os.environ.get('PORT', 5000))
    
    # On Render, we need to listen on 0.0.0.0
    app.run(debug=False, host='0.0.0.0', port=port)
=======
from flask import Flask, request, jsonify, send_file, send_from_directory, session, redirect, url_for, render_template_string
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import shutil
import json
import re
import hashlib
import secrets
from datetime import datetime
from werkzeug.utils import secure_filename
from functools import wraps

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = secrets.token_hex(32)  # Secure secret key
CORS(app)

# ===== CONFIGURATION =====
DB_CONFIG = {
    'host': 'localhost',
    'database': 'jid_dashboard',
    'user': 'postgres',
    'password': '6r6wyur*Gk1&25',  # Change this
    'port': '5432'
}

FILE_BASE_PATH = os.path.join(os.path.dirname(__file__), 'files')
ALLOWED_EXTENSIONS = {'pdf', 'xml', 'txt', 'json'}
os.makedirs(FILE_BASE_PATH, exist_ok=True)

# ===== DATABASE CONNECTION =====
def get_db_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

# ===== PASSWORD HASHING =====
def hash_password(password):
    """Hash a password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, hashed):
    """Verify a password against its hash"""
    return hash_password(password) == hashed

# ===== LOGIN DECORATORS =====
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

# ===== HELPER FUNCTIONS =====
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_jid_folder(jid_code, stage_name):
    folder = os.path.join(FILE_BASE_PATH, stage_name, jid_code)
    os.makedirs(folder, exist_ok=True)
    return folder

def get_stage_folder(jid_code, stage_name, sub_stage):
    folder = os.path.join(FILE_BASE_PATH, stage_name, jid_code, sub_stage)
    os.makedirs(folder, exist_ok=True)
    return folder

def save_file(file, jid_code, stage_name, file_type):
    if not file or not allowed_file(file.filename):
        return None
    
    original_filename = secure_filename(file.filename)
    ext = original_filename.rsplit('.', 1)[1].lower()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    file_type_mapping = {
        'correction': 'correction.pdf',
        'sample': 'sample.pdf',
        'sample_xml': 'sample.xml',
        'final_pdf': 'final.pdf',
        'final_xml': 'final.xml'
    }
    
    filename = file_type_mapping.get(file_type, f"{file_type}_{timestamp}.{ext}")
    jid_folder = get_jid_folder(jid_code, stage_name)
    file_path = os.path.join(jid_folder, filename)
    
    if os.path.exists(file_path):
        backup_path = f"{file_path}.{timestamp}.bak"
        os.rename(file_path, backup_path)
    
    file.save(file_path)
    return file_path

# ===== SIGNUP PAGE =====
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        role = request.form.get('role', 'user')
        
        # Validation
        if not username or not password:
            return render_template_string(SIGNUP_PAGE, error='Username and password are required')
        
        if len(username) < 3:
            return render_template_string(SIGNUP_PAGE, error='Username must be at least 3 characters')
        
        if len(password) < 6:
            return render_template_string(SIGNUP_PAGE, error='Password must be at least 6 characters')
        
        if password != confirm_password:
            return render_template_string(SIGNUP_PAGE, error='Passwords do not match')
        
        conn = get_db_connection()
        if not conn:
            return render_template_string(SIGNUP_PAGE, error='Database connection failed')
        
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Check if username already exists
                cur.execute("SELECT id FROM users WHERE username = %s", (username,))
                if cur.fetchone():
                    return render_template_string(SIGNUP_PAGE, error='Username already exists')
                
                # Check if email already exists (if provided)
                if email:
                    cur.execute("SELECT id FROM users WHERE email = %s", (email,))
                    if cur.fetchone():
                        return render_template_string(SIGNUP_PAGE, error='Email already registered')
                
                # Insert new user
                hashed_password = hash_password(password)
                cur.execute("""
                    INSERT INTO users (username, password_hash, full_name, email, role, created_at)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    RETURNING id, username, role
                """, (username, hashed_password, full_name, email, role))
                
                user = cur.fetchone()
                conn.commit()
                
                # Auto-login after signup
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user['role']
                session['full_name'] = full_name or username
                
                return redirect(url_for('dashboard'))
                
        except Exception as e:
            conn.rollback()
            return render_template_string(SIGNUP_PAGE, error=f'Error creating account: {str(e)}')
        finally:
            conn.close()
    
    return render_template_string(SIGNUP_PAGE, error=None)

# ===== SIGNUP PAGE HTML =====
SIGNUP_PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <title>JID Dashboard - Sign Up</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, sans-serif; }
        body { background: #f0f2f5; display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 20px; }
        .signup-container { background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 450px; max-width: 100%; }
        .signup-container h2 { text-align: center; margin-bottom: 8px; color: #1a1a2e; }
        .signup-container .subtitle { text-align: center; color: #94a3b8; font-size: 14px; margin-bottom: 24px; }
        .signup-container .logo { text-align: center; font-size: 48px; margin-bottom: 12px; }
        .form-group { margin-bottom: 16px; }
        .form-group label { display: block; font-size: 14px; font-weight: 500; margin-bottom: 4px; color: #1a1a2e; }
        .form-group input, .form-group select { width: 100%; padding: 10px 12px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 14px; }
        .form-group input:focus, .form-group select:focus { outline: none; border-color: #1a1a2e; }
        .form-group .hint { font-size: 12px; color: #94a3b8; margin-top: 4px; }
        .btn-primary { width: 100%; padding: 12px; background: #1a1a2e; color: white; border: none; border-radius: 6px; font-size: 16px; cursor: pointer; }
        .btn-primary:hover { background: #2d2d44; }
        .btn-secondary { width: 100%; padding: 12px; background: transparent; color: #1a1a2e; border: 2px solid #e2e8f0; border-radius: 6px; font-size: 16px; cursor: pointer; margin-top: 8px; }
        .btn-secondary:hover { background: #f1f5f9; }
        .error { background: #fee2e2; color: #991b1b; padding: 12px; border-radius: 6px; margin-bottom: 16px; text-align: center; }
        .success { background: #dcfce7; color: #166534; padding: 12px; border-radius: 6px; margin-bottom: 16px; text-align: center; }
        .login-link { text-align: center; margin-top: 16px; font-size: 14px; color: #64748b; }
        .login-link a { color: #1a1a2e; text-decoration: none; font-weight: 500; }
        .login-link a:hover { text-decoration: underline; }
        .role-selector { display: flex; gap: 12px; margin-top: 4px; }
        .role-option { flex: 1; padding: 10px; border: 2px solid #e2e8f0; border-radius: 6px; text-align: center; cursor: pointer; transition: all 0.2s; }
        .role-option:hover { border-color: #94a3b8; }
        .role-option.selected { border-color: #1a1a2e; background: #f1f5f9; }
        .role-option .role-icon { font-size: 24px; }
        .role-option .role-label { font-size: 13px; font-weight: 500; margin-top: 4px; }
        .role-option .role-desc { font-size: 11px; color: #94a3b8; }
    </style>
</head>
<body>
    <div class="signup-container">
        <div class="logo">📊</div>
        <h2>Create Account</h2>
        <div class="subtitle">Join the JID Management Dashboard</div>
        
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        
        <form method="POST">
            <div class="form-group">
                <label>Full Name</label>
                <input type="text" name="full_name" placeholder="Enter your full name">
            </div>
            
            <div class="form-group">
                <label>Username *</label>
                <input type="text" name="username" placeholder="Choose a username" required minlength="3">
                <div class="hint">At least 3 characters</div>
            </div>
            
            <div class="form-group">
                <label>Email</label>
                <input type="email" name="email" placeholder="Enter your email address">
            </div>
            
            <div class="form-group">
                <label>Password *</label>
                <input type="password" name="password" placeholder="Create a password" required minlength="6">
                <div class="hint">At least 6 characters</div>
            </div>
            
            <div class="form-group">
                <label>Confirm Password *</label>
                <input type="password" name="confirm_password" placeholder="Confirm your password" required>
            </div>
            
            <div class="form-group">
                <label>Role</label>
                <div class="role-selector">
                    <div class="role-option selected" onclick="selectRole('user')" id="role-user">
                        <div class="role-icon">👤</div>
                        <div class="role-label">User</div>
                        <div class="role-desc">View Only</div>
                    </div>
                    <div class="role-option" onclick="selectRole('admin')" id="role-admin">
                        <div class="role-icon">🔑</div>
                        <div class="role-label">Admin</div>
                        <div class="role-desc">Full Control</div>
                    </div>
                </div>
                <input type="hidden" name="role" id="selectedRole" value="user">
            </div>
            
            <button type="submit" class="btn-primary">Create Account</button>
        </form>
        
        <div class="login-link">
            Already have an account? <a href="/login">Login</a>
        </div>
    </div>
    
    <script>
        function selectRole(role) {
            document.querySelectorAll('.role-option').forEach(el => el.classList.remove('selected'));
            document.getElementById('role-' + role).classList.add('selected');
            document.getElementById('selectedRole').value = role;
        }
    </script>
</body>
</html>
'''

# ===== LOGIN PAGE =====
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            return render_template_string(LOGIN_PAGE, error='Username and password are required')
        
        conn = get_db_connection()
        if not conn:
            return render_template_string(LOGIN_PAGE, error='Database connection failed')
        
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, username, password_hash, full_name, role 
                    FROM users 
                    WHERE username = %s
                """, (username,))
                user = cur.fetchone()
                
                if not user:
                    return render_template_string(LOGIN_PAGE, error='Invalid username or password')
                
                if not verify_password(password, user['password_hash']):
                    return render_template_string(LOGIN_PAGE, error='Invalid username or password')
                
                # Login successful
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user['role']
                session['full_name'] = user['full_name'] or user['username']
                
                # Update last login
                cur.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = %s", (user['id'],))
                conn.commit()
                
                return redirect(url_for('dashboard'))
                
        except Exception as e:
            return render_template_string(LOGIN_PAGE, error=f'Login error: {str(e)}')
        finally:
            conn.close()
    
    return render_template_string(LOGIN_PAGE, error=None)

# ===== LOGIN PAGE HTML =====
LOGIN_PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <title>JID Dashboard - Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, sans-serif; }
        body { background: #f0f2f5; display: flex; justify-content: center; align-items: center; height: 100vh; }
        .login-container { background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 400px; }
        .login-container h2 { text-align: center; margin-bottom: 8px; color: #1a1a2e; }
        .login-container .subtitle { text-align: center; color: #94a3b8; font-size: 14px; margin-bottom: 24px; }
        .login-container .logo { text-align: center; font-size: 48px; margin-bottom: 12px; }
        .form-group { margin-bottom: 16px; }
        .form-group label { display: block; font-size: 14px; font-weight: 500; margin-bottom: 4px; color: #1a1a2e; }
        .form-group input { width: 100%; padding: 10px 12px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 14px; }
        .form-group input:focus { outline: none; border-color: #1a1a2e; }
        .btn-primary { width: 100%; padding: 12px; background: #1a1a2e; color: white; border: none; border-radius: 6px; font-size: 16px; cursor: pointer; }
        .btn-primary:hover { background: #2d2d44; }
        .error { background: #fee2e2; color: #991b1b; padding: 12px; border-radius: 6px; margin-bottom: 16px; text-align: center; }
        .signup-link { text-align: center; margin-top: 16px; font-size: 14px; color: #64748b; }
        .signup-link a { color: #1a1a2e; text-decoration: none; font-weight: 500; }
        .signup-link a:hover { text-decoration: underline; }
        .demo-info { background: #f8fafc; padding: 12px; border-radius: 6px; margin-top: 16px; font-size: 12px; color: #94a3b8; text-align: center; }
        .demo-info strong { color: #1a1a2e; }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">📊</div>
        <h2>Welcome Back</h2>
        <div class="subtitle">Login to JID Management Dashboard</div>
        
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        
        <form method="POST">
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" placeholder="Enter your username" required>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" placeholder="Enter your password" required>
            </div>
            <button type="submit" class="btn-primary">Login</button>
        </form>
        
        <div class="signup-link">
            Don't have an account? <a href="/signup">Sign Up</a>
        </div>
        
        <div class="demo-info">
            <strong>Demo Accounts:</strong><br>
            Admin: admin / admin123 | User: user / user123
        </div>
    </div>
</body>
</html>
'''

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ===== USER MANAGEMENT (Admin Only) =====
@app.route('/api/users', methods=['GET'])
@admin_required
def get_users():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, username, full_name, email, role, created_at, last_login, is_active
                FROM users
                ORDER BY created_at DESC
            """)
            users = cur.fetchall()
            return jsonify(users)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/users/<int:user_id>/role', methods=['PUT'])
@admin_required
def update_user_role(user_id):
    data = request.json
    new_role = data.get('role')
    if new_role not in ['admin', 'user']:
        return jsonify({'error': 'Invalid role'}), 400
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET role = %s WHERE id = %s RETURNING id", (new_role, user_id))
            if not cur.fetchone():
                return jsonify({'error': 'User not found'}), 404
            conn.commit()
            return jsonify({'message': 'User role updated successfully'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/users/<int:user_id>/status', methods=['PUT'])
@admin_required
def update_user_status(user_id):
    data = request.json
    is_active = data.get('is_active', True)
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET is_active = %s WHERE id = %s RETURNING id", (is_active, user_id))
            if not cur.fetchone():
                return jsonify({'error': 'User not found'}), 404
            conn.commit()
            return jsonify({'message': 'User status updated successfully'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# ===== DASHBOARD =====
@app.route('/')
@login_required
def dashboard():
    role = session.get('role', 'user')
    username = session.get('username', 'User')
    full_name = session.get('full_name', username)
    return render_template_string(DASHBOARD_PAGE, role=role, username=username, full_name=full_name)

# ===== DASHBOARD HTML (Updated with User Management) =====
DASHBOARD_PAGE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JID Management Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, sans-serif; }
        body { background: #f0f2f5; height: 100vh; display: flex; }
        
        .sidebar { width: 320px; background: white; padding: 20px; border-right: 1px solid #e2e8f0; overflow-y: auto; display: flex; flex-direction: column; }
        .sidebar-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .sidebar-header h2 { font-size: 20px; color: #1a1a2e; }
        .btn-primary { background: #1a1a2e; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 14px; }
        .btn-primary:hover { background: #2d2d44; }
        .btn-danger { background: #ef4444; color: white; border: none; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }
        .btn-danger:hover { background: #dc2626; }
        .btn-success { background: #22c55e; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 14px; }
        .btn-success:hover { background: #16a34a; }
        .btn-warning { background: #f59e0b; color: white; border: none; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }
        .btn-warning:hover { background: #d97706; }
        .btn-outline { background: transparent; border: 1px solid #e2e8f0; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }
        .btn-outline:hover { background: #f1f5f9; }
        
        .search-container { margin-bottom: 12px; }
        .search-container input { width: 100%; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 14px; }
        .search-container input:focus { outline: none; border-color: #1a1a2e; }
        
        .stage-header { padding: 8px 12px; margin: 8px 0 4px 0; background: #f1f5f9; border-radius: 6px; font-weight: 600; font-size: 13px; color: #1a1a2e; text-transform: uppercase; letter-spacing: 0.5px; }
        
        .jid-item { padding: 10px 14px; margin-bottom: 4px; border-radius: 6px; cursor: pointer; transition: all 0.2s; border-left: 3px solid transparent; }
        .jid-item:hover { background: #f1f5f9; }
        .jid-item.active { background: #1a1a2e; color: white; border-left-color: #22c55e; }
        .jid-item .jid-name { font-weight: 500; font-size: 14px; }
        .jid-item .jid-meta { font-size: 11px; color: #94a3b8; margin-top: 3px; }
        .jid-item.active .jid-meta { color: #cbd5e1; }
        .jid-item .progress-bar { height: 3px; background: #e2e8f0; border-radius: 2px; margin-top: 4px; overflow: hidden; }
        .jid-item .progress-bar .progress-fill { height: 100%; background: #22c55e; transition: width 0.3s; }
        .jid-item .status-badge { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 10px; margin-left: 6px; }
        .status-complete { background: #dcfce7; color: #166534; }
        .status-progress { background: #fef3c7; color: #92400e; }
        .status-pending { background: #fee2e2; color: #991b1b; }
        
        .main { flex: 1; padding: 24px; overflow-y: auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; flex-wrap: wrap; gap: 10px; }
        .header h1 { font-size: 22px; color: #1a1a2e; }
        .header .subtitle { font-size: 13px; color: #94a3b8; margin-top: 2px; }
        .header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
        
        .role-badge { display: inline-block; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 500; }
        .role-admin { background: #dbeafe; color: #1e40af; }
        .role-user { background: #dcfce7; color: #166534; }
        
        .tabs { display: flex; gap: 2px; margin-bottom: 20px; border-bottom: 2px solid #e2e8f0; }
        .tab { padding: 10px 20px; cursor: pointer; border: none; background: none; font-size: 14px; color: #64748b; border-bottom: 2px solid transparent; margin-bottom: -2px; }
        .tab.active { color: #1a1a2e; border-bottom-color: #1a1a2e; font-weight: 500; }
        .tab:hover { color: #1a1a2e; }
        
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        
        .files-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; margin: 16px 0; }
        .file-card { background: white; padding: 16px; border-radius: 8px; border: 1px solid #e2e8f0; }
        .file-card .file-icon { font-size: 32px; margin-bottom: 8px; }
        .file-card .file-name { font-size: 13px; font-weight: 500; word-break: break-all; }
        .file-card .file-type { font-size: 11px; color: #94a3b8; margin-top: 2px; }
        .file-card .file-meta { font-size: 11px; color: #94a3b8; margin-top: 4px; }
        .file-card .file-actions { margin-top: 10px; display: flex; gap: 6px; flex-wrap: wrap; }
        .file-card .file-actions button { padding: 3px 10px; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; }
        .btn-view { background: #e2e8f0; color: #1a1a2e; }
        .btn-view:hover { background: #cbd5e1; }
        .btn-download { background: #dbeafe; color: #1e40af; }
        .btn-download:hover { background: #bfdbfe; }
        .btn-delete { background: #fee2e2; color: #991b1b; }
        .btn-delete:hover { background: #fecaca; }
        
        .pdf-container { background: white; border-radius: 8px; padding: 16px; margin: 16px 0; border: 1px solid #e2e8f0; }
        .pdf-container iframe { width: 100%; height: 600px; border: none; border-radius: 4px; }
        
        .checklist { background: white; border-radius: 8px; padding: 20px; border: 1px solid #e2e8f0; margin: 16px 0; }
        .checklist-item { display: flex; align-items: center; gap: 12px; padding: 8px 0; border-bottom: 1px solid #f1f5f9; }
        .checklist-item:last-child { border-bottom: none; }
        .checklist-item input[type="checkbox"] { width: 18px; height: 18px; cursor: pointer; }
        .checklist-item .item-label { flex: 1; font-size: 14px; }
        .checklist-item .item-status { font-size: 12px; color: #94a3b8; }
        .checklist-progress { margin: 12px 0; }
        .checklist-progress .progress-bar { height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden; }
        .checklist-progress .progress-fill { height: 100%; background: #22c55e; transition: width 0.3s; }
        .checklist-progress .progress-text { font-size: 13px; color: #64748b; margin-top: 4px; }
        
        .stage-selector { display: flex; gap: 8px; margin: 12px 0; flex-wrap: wrap; }
        .stage-btn { padding: 6px 16px; border: 1px solid #e2e8f0; background: white; border-radius: 6px; cursor: pointer; font-size: 13px; }
        .stage-btn.active { background: #1a1a2e; color: white; border-color: #1a1a2e; }
        .stage-btn:hover { background: #f1f5f9; }
        .stage-btn.active:hover { background: #2d2d44; }
        
        .online-link-box { background: #f8fafc; padding: 16px; border-radius: 8px; border: 1px solid #e2e8f0; margin: 16px 0; }
        .online-link-box input[type="text"] { width: 100%; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 14px; margin: 8px 0; }
        
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; justify-content: center; align-items: center; }
        .modal.active { display: flex; }
        .modal-content { background: white; border-radius: 12px; padding: 30px; max-width: 600px; width: 90%; max-height: 80vh; overflow-y: auto; }
        .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .modal-header h3 { font-size: 18px; color: #1a1a2e; }
        .modal-close { background: none; border: none; font-size: 24px; cursor: pointer; color: #94a3b8; }
        .modal-close:hover { color: #1a1a2e; }
        .modal form .form-group { margin-bottom: 16px; }
        .modal form label { display: block; font-size: 14px; font-weight: 500; margin-bottom: 4px; color: #1a1a2e; }
        .modal form input[type="text"], .modal form select { width: 100%; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 14px; }
        .modal form input[type="file"] { width: 100%; padding: 8px 0; }
        
        .toast { position: fixed; bottom: 20px; right: 20px; background: #1a1a2e; color: white; padding: 14px 24px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); z-index: 2000; animation: slideIn 0.3s ease; }
        .toast.success { background: #16a34a; }
        .toast.error { background: #dc2626; }
        .toast.info { background: #2563eb; }
        @keyframes slideIn { from { transform: translateY(100px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
        
        .empty-state { text-align: center; color: #94a3b8; padding: 40px; }
        .empty-state .icon { font-size: 48px; margin-bottom: 12px; }
        
        .user-banner { background: #f8fafc; padding: 8px 16px; border-radius: 6px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; }
        .user-banner .user-info { font-size: 13px; color: #64748b; }
        
        .users-table { width: 100%; border-collapse: collapse; margin-top: 12px; }
        .users-table th { text-align: left; padding: 10px; background: #f1f5f9; font-size: 12px; text-transform: uppercase; color: #64748b; }
        .users-table td { padding: 10px; border-bottom: 1px solid #e2e8f0; font-size: 14px; }
        .users-table tr:hover { background: #f8fafc; }
        .users-table .status-active { color: #16a34a; }
        .users-table .status-inactive { color: #dc2626; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-header">
            <h2>📁 HMS Abstract</h2>
            <div>
                {% if role == 'admin' %}
                <button class="btn-primary" onclick="showCreateJIDModal()">+ New</button>
                {% endif %}
            </div>
        </div>
        
        <div class="search-container">
            <input type="text" id="searchInput" placeholder="🔍 Search JID..." onkeyup="filterJIDs()">
        </div>
        
        <div id="jidList" style="flex: 1; overflow-y: auto;"></div>
        
        <div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid #e2e8f0;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                <div>
                    <span class="role-badge {% if role == 'admin' %}role-admin{% else %}role-user{% endif %}">
                        {% if role == 'admin' %}🔑 Admin{% else %}👤 User{% endif %}
                    </span>
                    <span style="font-size: 13px; color: #64748b; margin-left: 8px;">{{ full_name }}</span>
                </div>
                <div style="display: flex; gap: 8px;">
                    {% if role == 'admin' %}
                    <button class="btn-outline" onclick="showUsersModal()">👥 Users</button>
                    {% endif %}
                    <a href="/logout" style="color: #ef4444; text-decoration: none; font-size: 13px;">Logout</a>
                </div>
            </div>
        </div>
    </div>

    <div class="main">
        <div class="header">
            <div>
                <h1 id="jidTitle">Select a JID to begin</h1>
                <div class="subtitle" id="jidSubtitle">Choose a JID from the sidebar to view details</div>
            </div>
            <div class="header-actions">
                {% if role == 'admin' %}
                <button class="btn-success" onclick="showUploadModal()" id="uploadBtn" style="display: none;">📤 Upload</button>
                <button class="btn-primary" onclick="showOnlineLinkModal()" id="onlineBtn" style="display: none;">🔗 Online Link</button>
                {% endif %}
                <button class="btn-outline" onclick="window.open('/api/export/' + currentJIDId, '_blank')" id="exportBtn" style="display: none;">📥 Export</button>
            </div>
        </div>
        
        <div class="stage-selector" id="stageSelector"></div>
        
        <div class="tabs">
            <button class="tab active" onclick="switchTab('files')">📄 Materials</button>
            <button class="tab" onclick="switchTab('pdf')">📑 PDF Viewer</button>
            <button class="tab" onclick="switchTab('checklist')">✅ Checklist</button>
            <button class="tab" onclick="switchTab('online')">🔗 Online</button>
        </div>
        
        <div class="tab-content active" id="tab-files"><div id="filesContainer"><div class="empty-state"><div class="icon">📂</div><p>No JID selected. Select a JID from the sidebar.</p></div></div></div>
        <div class="tab-content" id="tab-pdf"><div id="pdfContainer"><div class="empty-state"><div class="icon">📄</div><p>Select a JID to view PDFs</p></div></div></div>
        <div class="tab-content" id="tab-checklist"><div id="checklistContainer"><div class="empty-state"><div class="icon">✅</div><p>Select a JID to view checklist</p></div></div></div>
        <div class="tab-content" id="tab-online"><div id="onlineContainer"><div class="empty-state"><div class="icon">🔗</div><p>Select a JID to view online links</p></div></div></div>
    </div>

    <!-- Admin-Only Modals -->
    {% if role == 'admin' %}
    <div class="modal" id="createJIDModal">
        <div class="modal-content">
            <div class="modal-header"><h3>Create New JID</h3><button class="modal-close" onclick="closeModal('createJIDModal')">&times;</button></div>
            <form onsubmit="createJID(event)">
                <div class="form-group"><label>JID Code</label><input type="text" id="newJIDName" placeholder="e.g., ACEPJO" required></div>
                <div class="form-group"><label>Stage</label><select id="newJIDStage" required><option value="">Select Stage</option></select></div>
                <button type="submit" class="btn-primary" style="width:100%;">Create JID</button>
            </form>
        </div>
    </div>

    <div class="modal" id="uploadModal">
        <div class="modal-content">
            <div class="modal-header"><h3>📤 Upload Materials</h3><button class="modal-close" onclick="closeModal('uploadModal')">&times;</button></div>
            <div style="background:#f0fdf4;padding:12px;border-radius:6px;margin-bottom:16px;font-size:13px;color:#166534;">
                💡 Materials uploaded here are shared across all stages (DC, QC, Pagination, Online)
            </div>
            <form onsubmit="uploadFile(event)">
                <div class="form-group"><label>File Type</label>
                    <select id="fileType" required>
                        <option value="correction">Correction PDF</option>
                        <option value="sample">Sample PDF</option>
                        <option value="sample_xml">Sample XML</option>
                        <option value="final_pdf">Final PDF</option>
                        <option value="final_xml">Final XML</option>
                    </select>
                </div>
                <div class="form-group"><label>Select File</label><input type="file" id="fileInput" accept=".pdf,.xml,.txt" required></div>
                <button type="submit" class="btn-success" style="width:100%;">Upload</button>
            </form>
        </div>
    </div>

    <div class="modal" id="onlineLinkModal">
        <div class="modal-content">
            <div class="modal-header"><h3>🔗 Update Online Link</h3><button class="modal-close" onclick="closeModal('onlineLinkModal')">&times;</button></div>
            <form onsubmit="updateOnlineLink(event)">
                <div class="form-group"><label>Online Link URL</label><input type="url" id="onlineLinkInput" placeholder="https://example.com/article" required></div>
                <button type="submit" class="btn-success" style="width:100%;">Save Link</button>
            </form>
        </div>
    </div>

    <!-- Users Management Modal -->
    <div class="modal" id="usersModal">
        <div class="modal-content" style="max-width: 800px;">
            <div class="modal-header">
                <h3>👥 User Management</h3>
                <button class="modal-close" onclick="closeModal('usersModal')">&times;</button>
            </div>
            <div id="usersList">
                <div style="text-align:center;padding:20px;color:#94a3b8;">Loading users...</div>
            </div>
        </div>
    </div>
    {% endif %}

    <div id="toastContainer"></div>

    <script>
        let currentJIDId = null;
        let currentJIDCode = null;
        let currentStage = null;
        let currentSubStage = 'DC';
        let allJIDs = [];
        let allStages = [];
        let userRole = '{{ role }}';
        let filteredJIDs = [];

        const API_BASE = '';

        async function apiCall(endpoint, options = {}) {
            try {
                const response = await fetch(`${API_BASE}/api${endpoint}`, {
                    ...options,
                    headers: { 'Content-Type': 'application/json', ...options.headers }
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || 'API call failed');
                return data;
            } catch (error) {
                showToast(error.message, 'error');
                throw error;
            }
        }

        // ===== SEARCH FUNCTION =====
        function filterJIDs() {
            const searchTerm = document.getElementById('searchInput').value.toLowerCase().trim();
            const items = document.querySelectorAll('.jid-item');
            
            items.forEach(item => {
                const jidName = item.getAttribute('data-jid')?.toLowerCase() || '';
                if (searchTerm === '' || jidName.includes(searchTerm)) {
                    item.style.display = '';
                } else {
                    item.style.display = 'none';
                }
            });
        }

        async function loadStages() {
            try {
                allStages = await apiCall('/stages');
                const select = document.getElementById('newJIDStage');
                if (select) {
                    select.innerHTML = '<option value="">Select Stage</option>' + 
                        allStages.map(s => `<option value="${s.stage_name}">${s.stage_name}</option>`).join('');
                }
            } catch (error) {
                console.error('Failed to load stages:', error);
            }
        }

        async function loadJIDs() {
            try {
                allJIDs = await apiCall('/jids');
                filteredJIDs = allJIDs;
                renderJIDList();
                if (allJIDs.length > 0 && !currentJIDId) {
                    selectJID(allJIDs[0].id);
                }
            } catch (error) {
                console.error('Failed to load JIDs:', error);
                showToast('Database connection failed! Please check server logs.', 'error');
            }
        }

        function renderJIDList() {
            const container = document.getElementById('jidList');
            if (allJIDs.length === 0) {
                container.innerHTML = '<div class="empty-state" style="padding:20px;"><p>No JIDs created yet</p></div>';
                return;
            }
            
            let html = '';
            let currentStageGroup = '';
            
            allJIDs.forEach(jid => {
                if (jid.stage_name !== currentStageGroup) {
                    currentStageGroup = jid.stage_name;
                    html += `<div class="stage-header">📌 ${jid.stage_name}</div>`;
                }
                
                const statusClass = jid.checklist_progress === 100 ? 'status-complete' : 
                                   jid.checklist_progress > 0 ? 'status-progress' : 'status-pending';
                const statusText = jid.checklist_progress === 100 ? 'Complete' : 
                                  jid.checklist_progress > 0 ? 'In Progress' : 'Pending';
                
                html += `
                    <div class="jid-item ${jid.id === currentJIDId ? 'active' : ''}" data-jid="${jid.jid_code}" onclick="selectJID(${jid.id})">
                        <div>
                            <span class="jid-name">${jid.jid_code}</span>
                            <span class="status-badge ${statusClass}">${statusText}</span>
                        </div>
                        <div class="jid-meta">📄 ${jid.file_count || 0} materials • ${jid.checklist_progress || 0}% complete</div>
                        <div class="progress-bar"><div class="progress-fill" style="width: ${jid.checklist_progress || 0}%"></div></div>
                        <div class="jid-meta" style="margin-top:4px;display:flex;justify-content:space-between;align-items:center;">
                            <span>${jid.updated_at ? new Date(jid.updated_at).toLocaleDateString() : 'No updates'}</span>
                            ${userRole === 'admin' ? `<button class="btn-danger" onclick="event.stopPropagation(); deleteJID(${jid.id})">Delete</button>` : ''}
                        </div>
                    </div>
                `;
            });
            
            container.innerHTML = html;
        }

        async function selectJID(jidId) {
            currentJIDId = jidId;
            const jid = allJIDs.find(j => j.id === jidId);
            if (!jid) return;
            
            currentJIDCode = jid.jid_code;
            currentStage = jid.stage_name;
            currentSubStage = 'DC';
            
            document.getElementById('jidTitle').textContent = `📑 ${jid.jid_code}`;
            document.getElementById('jidSubtitle').textContent = `${jid.stage_name} • ${jid.file_count || 0} materials • ${jid.checklist_progress || 0}% complete`;
            
            if (userRole === 'admin') {
                document.getElementById('uploadBtn').style.display = 'inline-block';
                document.getElementById('onlineBtn').style.display = 'inline-block';
            }
            document.getElementById('exportBtn').style.display = 'inline-block';
            
            document.querySelectorAll('.jid-item').forEach(el => el.classList.remove('active'));
            document.querySelector(`.jid-item[onclick*="selectJID(${jidId})"]`)?.classList.add('active');
            
            renderStageSelector();
            await loadDataForCurrentStage();
        }

        function renderStageSelector() {
            const container = document.getElementById('stageSelector');
            const stages = ['DC', 'QC', 'Pagination', 'Online'];
            container.innerHTML = stages.map(stage => `
                <button class="stage-btn ${stage === currentSubStage ? 'active' : ''}" onclick="switchSubStage('${stage}')">${stage}</button>
            `).join('');
        }

        async function switchSubStage(stage) {
            currentSubStage = stage;
            renderStageSelector();
            await loadDataForCurrentStage();
            switchTab('files');
        }

        async function loadDataForCurrentStage() {
            await loadMaterials(currentJIDId);
            await loadPDF(currentJIDId);
            await loadChecklist(currentJIDId, currentSubStage);
            await loadOnlineLink(currentJIDId);
        }

        // ===== LOAD MATERIALS =====
        async function loadMaterials(jidId) {
            try {
                const files = await apiCall(`/materials/${jidId}`);
                renderMaterials(files);
            } catch (error) {
                console.error('Failed to load materials:', error);
            }
        }

        function renderMaterials(files) {
            const container = document.getElementById('filesContainer');
            
            const fileTypes = {
                'correction': { icon: '📄', label: 'Correction PDF' },
                'sample': { icon: '📄', label: 'Sample PDF' },
                'sample_xml': { icon: '📋', label: 'Sample XML' },
                'final_pdf': { icon: '📄', label: 'Final PDF' },
                'final_xml': { icon: '📋', label: 'Final XML' }
            };
            
            if (!files || files.length === 0) {
                container.innerHTML = `
                    <div style="background:#fef3c7;padding:16px;border-radius:8px;margin-bottom:16px;border:1px solid #fcd34d;">
                        <span style="font-size:14px;color:#92400e;">📌 Materials are shared across all stages (DC, QC, Pagination, Online)</span>
                    </div>
                    <div class="empty-state">
                        <div class="icon">📂</div>
                        <p>No materials uploaded yet</p>
                        ${userRole === 'admin' ? `<button class="btn-primary" onclick="showUploadModal()" style="margin-top:12px;">Upload Materials</button>` : ''}
                    </div>
                `;
                return;
            }
            
            let html = `
                <div style="background:#f0fdf4;padding:16px;border-radius:8px;margin-bottom:16px;border:1px solid #bbf7d0;">
                    <span style="font-size:14px;color:#166534;">✅ Materials are shared across all stages (DC, QC, Pagination, Online)</span>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                    <span style="font-size:14px;color:#64748b;">📁 ${currentJIDCode} / ${currentStage}</span>
                    ${userRole === 'admin' ? `<button class="btn-success" onclick="showUploadModal()">📤 Upload</button>` : ''}
                </div>
                <div class="files-grid">
            `;
            
            files.forEach(file => {
                const info = fileTypes[file.file_type] || { icon: '📄', label: file.file_type };
                html += `
                    <div class="file-card">
                        <div class="file-icon">${info.icon}</div>
                        <div class="file-name">${file.filename}</div>
                        <div class="file-type">${info.label}</div>
                        <div class="file-meta">v${file.version} • ${new Date(file.uploaded_at).toLocaleDateString()}</div>
                        <div class="file-actions">
                            ${file.file_type.includes('pdf') ? `<button class="btn-view" onclick="viewPDFFile(${file.id})">View</button>` : ''}
                            <button class="btn-download" onclick="downloadFile(${file.id})">Download</button>
                            ${userRole === 'admin' ? `<button class="btn-delete" onclick="deleteFile(${file.id})">Delete</button>` : ''}
                        </div>
                    </div>
                `;
            });
            
            html += `</div>`;
            container.innerHTML = html;
        }

        // ===== LOAD PDF =====
        async function loadPDF(jidId) {
            try {
                const files = await apiCall(`/materials/${jidId}`);
                const pdfFile = files.find(f => f.file_type === 'correction' || f.file_type === 'final_pdf');
                const container = document.getElementById('pdfContainer');
                if (pdfFile) {
                    container.innerHTML = `
                        <div class="pdf-container">
                            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                                <span><strong>${pdfFile.filename}</strong> (v${pdfFile.version}) • Shared across all stages</span>
                                <button class="btn-download" onclick="downloadFile(${pdfFile.id})">Download</button>
                            </div>
                            <iframe src="/api/files/download/${pdfFile.id}" style="width:100%;height:600px;border:none;border-radius:4px;"></iframe>
                        </div>
                    `;
                } else {
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="icon">📄</div>
                            <p>No PDF files available</p>
                            ${userRole === 'admin' ? `<button class="btn-primary" onclick="showUploadModal()" style="margin-top:12px;">Upload a PDF</button>` : ''}
                        </div>
                    `;
                }
            } catch (error) {
                console.error('Failed to load PDF:', error);
            }
        }

        function viewPDFFile(fileId) { window.open(`/api/files/download/${fileId}`, '_blank'); }
        function downloadFile(fileId) { window.open(`/api/files/download/${fileId}`, '_blank'); }

        // ===== DELETE FILE (Admin Only) =====
        async function deleteFile(fileId) {
            if (userRole !== 'admin') {
                showToast('Access denied. Admin only.', 'error');
                return;
            }
            if (!confirm('Are you sure you want to delete this file?')) return;
            try {
                await apiCall(`/files/${fileId}`, { method: 'DELETE' });
                showToast('File deleted successfully', 'success');
                await loadMaterials(currentJIDId);
                await loadPDF(currentJIDId);
                await loadJIDs();
            } catch (error) {
                console.error('Failed to delete file:', error);
            }
        }

        // ===== LOAD CHECKLIST =====
        async function loadChecklist(jidId, subStage) {
            try {
                const checklist = await apiCall(`/checklist/${jidId}/${subStage}`);
                renderChecklist(checklist, subStage);
            } catch (error) {
                console.error('Failed to load checklist:', error);
            }
        }

        function renderChecklist(checklist, subStage) {
            const container = document.getElementById('checklistContainer');
            if (!checklist || checklist.length === 0) {
                container.innerHTML = `<div class="empty-state"><div class="icon">✅</div><p>No checklist items found for ${subStage}</p></div>`;
                return;
            }
            
            const total = checklist.length;
            const done = checklist.filter(item => item.is_checked).length;
            const progress = total > 0 ? (done / total * 100) : 0;
            const isAdmin = userRole === 'admin';
            
            container.innerHTML = `
                <div class="checklist">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                        <h3 style="font-size:18px;">✅ Checklist - ${subStage}</h3>
                        ${isAdmin ? `<button class="btn-danger" onclick="resetChecklist()">Reset All</button>` : ''}
                    </div>
                    <div style="background:#f0fdf4;padding:12px;border-radius:6px;margin-bottom:16px;font-size:13px;color:#166534;">
                        📌 This checklist is specific to ${subStage} stage
                        ${!isAdmin ? '<br>👤 View-only mode' : ''}
                    </div>
                    <div class="checklist-progress">
                        <div class="progress-bar"><div class="progress-fill" style="width: ${progress}%"></div></div>
                        <div class="progress-text">${done} of ${total} items completed (${Math.round(progress)}%)</div>
                    </div>
                    ${checklist.map(item => `
                        <div class="checklist-item">
                            ${isAdmin ? `<input type="checkbox" ${item.is_checked ? 'checked' : ''} onchange="updateChecklist('${item.item_key}', this.checked)">` : 
                                        `<span style="width:18px;text-align:center;">${item.is_checked ? '✅' : '⬜'}</span>`}
                            <span class="item-label">${item.item_label}</span>
                            <span class="item-status">${item.is_checked ? '✅ Done' : '⏳ Pending'}</span>
                        </div>
                    `).join('')}
                </div>
            `;
        }

        async function updateChecklist(itemKey, isChecked) {
            if (userRole !== 'admin') {
                showToast('Access denied. Admin only.', 'error');
                return;
            }
            try {
                await apiCall(`/checklist/${currentJIDId}/${currentSubStage}/${itemKey}`, {
                    method: 'PUT',
                    body: JSON.stringify({ is_checked: isChecked })
                });
                showToast('Checklist updated', 'success');
                await loadChecklist(currentJIDId, currentSubStage);
                await loadJIDs();
            } catch (error) {
                console.error('Failed to update checklist:', error);
            }
        }

        async function resetChecklist() {
            if (userRole !== 'admin') {
                showToast('Access denied. Admin only.', 'error');
                return;
            }
            if (!confirm(`Are you sure you want to reset all checklist items for ${currentSubStage}?`)) return;
            try {
                await apiCall(`/checklist/${currentJIDId}/${currentSubStage}/reset`, { method: 'POST' });
                showToast('Checklist reset', 'success');
                await loadChecklist(currentJIDId, currentSubStage);
                await loadJIDs();
            } catch (error) {
                console.error('Failed to reset checklist:', error);
            }
        }

        // ===== LOAD ONLINE LINK =====
        async function loadOnlineLink(jidId) {
            try {
                const linkData = await apiCall(`/online/${jidId}`);
                renderOnlineLink(linkData);
            } catch (error) {
                console.error('Failed to load online link:', error);
            }
        }

        function renderOnlineLink(linkData) {
            const container = document.getElementById('onlineContainer');
            const isAdmin = userRole === 'admin';
            
            if (linkData && linkData.link_url) {
                container.innerHTML = `
                    <div class="online-link-box">
                        <h3 style="font-size:16px;margin-bottom:12px;">🔗 Online Publication Link</h3>
                        <div style="background:#f1f5f9;padding:12px;border-radius:6px;word-break:break-all;">
                            <a href="${linkData.link_url}" target="_blank" style="color:#2563eb;">${linkData.link_url}</a>
                        </div>
                        <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;">
                            <span style="font-size:13px;color:#64748b;">Status: ${linkData.verified ? '✅ Verified' : '⏳ Pending Verification'}</span>
                            ${isAdmin ? `
                                <button class="btn-warning" onclick="showOnlineLinkModal()">Update Link</button>
                                <button class="btn-danger" onclick="deleteOnlineLink()">Delete Link</button>
                            ` : ''}
                        </div>
                        <div style="margin-top:8px;font-size:12px;color:#94a3b8;">Updated: ${linkData.updated_at ? new Date(linkData.updated_at).toLocaleString() : 'Never'}</div>
                    </div>
                `;
            } else {
                container.innerHTML = `
                    <div class="empty-state"><div class="icon">🔗</div>
                    <p>No online link configured</p>
                    ${isAdmin ? `<button class="btn-primary" onclick="showOnlineLinkModal()" style="margin-top:12px;">Add Online Link</button>` : ''}
                    </div>
                `;
            }
        }

        // ===== ADMIN-ONLY FUNCTIONS =====
        // ===== USER MANAGEMENT =====
        async function showUsersModal() {
            if (userRole !== 'admin') {
                showToast('Access denied. Admin only.', 'error');
                return;
            }
            document.getElementById('usersModal').classList.add('active');
            await loadUsers();
        }

        async function loadUsers() {
            try {
                const users = await apiCall('/users');
                renderUsers(users);
            } catch (error) {
                console.error('Failed to load users:', error);
            }
        }

        function renderUsers(users) {
            const container = document.getElementById('usersList');
            if (!users || users.length === 0) {
                container.innerHTML = '<div class="empty-state"><p>No users found</p></div>';
                return;
            }
            
            let html = `
                <table class="users-table">
                    <thead>
                        <tr>
                            <th>Username</th>
                            <th>Full Name</th>
                            <th>Email</th>
                            <th>Role</th>
                            <th>Status</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
            `;
            
            users.forEach(user => {
                const isActive = user.is_active !== false;
                html += `
                    <tr>
                        <td><strong>${user.username}</strong></td>
                        <td>${user.full_name || '-'}</td>
                        <td>${user.email || '-'}</td>
                        <td>
                            <select onchange="updateUserRole(${user.id}, this.value)" style="padding:4px 8px;border-radius:4px;border:1px solid #e2e8f0;">
                                <option value="user" ${user.role === 'user' ? 'selected' : ''}>User</option>
                                <option value="admin" ${user.role === 'admin' ? 'selected' : ''}>Admin</option>
                            </select>
                        </td>
                        <td class="${isActive ? 'status-active' : 'status-inactive'}">
                            ${isActive ? '✅ Active' : '❌ Inactive'}
                        </td>
                        <td>
                            <button class="btn-warning" onclick="toggleUserStatus(${user.id}, ${!isActive})" style="font-size:11px;padding:2px 8px;">
                                ${isActive ? 'Deactivate' : 'Activate'}
                            </button>
                        </td>
                    </tr>
                `;
            });
            
            html += `</tbody></table>`;
            container.innerHTML = html;
        }

        async function updateUserRole(userId, newRole) {
            if (userRole !== 'admin') {
                showToast('Access denied. Admin only.', 'error');
                return;
            }
            try {
                await apiCall(`/users/${userId}/role`, {
                    method: 'PUT',
                    body: JSON.stringify({ role: newRole })
                });
                showToast('User role updated successfully', 'success');
                await loadUsers();
            } catch (error) {
                showToast(error.message, 'error');
            }
        }

        async function toggleUserStatus(userId, isActive) {
            if (userRole !== 'admin') {
                showToast('Access denied. Admin only.', 'error');
                return;
            }
            try {
                await apiCall(`/users/${userId}/status`, {
                    method: 'PUT',
                    body: JSON.stringify({ is_active: isActive })
                });
                showToast(`User ${isActive ? 'activated' : 'deactivated'} successfully`, 'success');
                await loadUsers();
            } catch (error) {
                showToast(error.message, 'error');
            }
        }

        async function updateOnlineLink(event) {
            if (userRole !== 'admin') {
                showToast('Access denied. Admin only.', 'error');
                return;
            }
            event.preventDefault();
            const url = document.getElementById('onlineLinkInput').value.trim();
            if (!url) { showToast('Please enter a valid URL', 'error'); return; }
            try {
                await apiCall(`/online/${currentJIDId}`, { method: 'POST', body: JSON.stringify({ link_url: url }) });
                showToast('Online link updated successfully', 'success');
                closeModal('onlineLinkModal');
                document.getElementById('onlineLinkInput').value = '';
                await loadOnlineLink(currentJIDId);
            } catch (error) { showToast(error.message, 'error'); }
        }

        async function deleteOnlineLink() {
            if (userRole !== 'admin') {
                showToast('Access denied. Admin only.', 'error');
                return;
            }
            if (!confirm('Are you sure you want to delete the online link?')) return;
            try {
                await apiCall(`/online/${currentJIDId}`, { method: 'DELETE' });
                showToast('Online link deleted', 'success');
                await loadOnlineLink(currentJIDId);
            } catch (error) { console.error('Failed to delete online link:', error); }
        }

        async function uploadFile(event) {
            if (userRole !== 'admin') {
                showToast('Access denied. Admin only.', 'error');
                return;
            }
            event.preventDefault();
            const fileType = document.getElementById('fileType').value;
            const fileInput = document.getElementById('fileInput');
            const file = fileInput.files[0];
            if (!file) { showToast('Please select a file', 'error'); return; }
            
            const formData = new FormData();
            formData.append('file_type', fileType);
            formData.append('file', file);
            
            try {
                const response = await fetch(`/api/upload/${currentJIDId}`, { method: 'POST', body: formData });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || 'Upload failed');
                showToast('File uploaded successfully', 'success');
                closeModal('uploadModal');
                document.getElementById('fileInput').value = '';
                await loadDataForCurrentStage();
                await loadJIDs();
            } catch (error) { showToast(error.message, 'error'); }
        }

        async function createJID(event) {
            if (userRole !== 'admin') {
                showToast('Access denied. Admin only.', 'error');
                return;
            }
            event.preventDefault();
            const code = document.getElementById('newJIDName').value.trim().toUpperCase();
            const stage = document.getElementById('newJIDStage').value;
            if (!code) { showToast('Please enter a JID code', 'error'); return; }
            if (!stage) { showToast('Please select a stage', 'error'); return; }
            try {
                const data = await apiCall('/jids', { method: 'POST', body: JSON.stringify({ jid_code: code, stage_name: stage }) });
                showToast('JID created successfully', 'success');
                closeModal('createJIDModal');
                document.getElementById('newJIDName').value = '';
                await loadJIDs();
                selectJID(data.id);
            } catch (error) { showToast(error.message, 'error'); }
        }

        async function deleteJID(jidId) {
            if (userRole !== 'admin') {
                showToast('Access denied. Admin only.', 'error');
                return;
            }
            if (!confirm('Are you sure you want to delete this JID and all its files?')) return;
            try {
                await apiCall(`/jids/${jidId}`, { method: 'DELETE' });
                showToast('JID deleted successfully', 'success');
                if (currentJIDId === jidId) {
                    currentJIDId = null;
                    document.getElementById('jidTitle').textContent = 'Select a JID to begin';
                    document.getElementById('jidSubtitle').textContent = 'Choose a JID from the sidebar to view details';
                    document.getElementById('uploadBtn').style.display = 'none';
                    document.getElementById('onlineBtn').style.display = 'none';
                    document.getElementById('exportBtn').style.display = 'none';
                    document.getElementById('stageSelector').innerHTML = '';
                    document.getElementById('filesContainer').innerHTML = '<div class="empty-state"><div class="icon">📂</div><p>No JID selected</p></div>';
                    document.getElementById('pdfContainer').innerHTML = '<div class="empty-state"><div class="icon">📄</div><p>No JID selected</p></div>';
                    document.getElementById('checklistContainer').innerHTML = '<div class="empty-state"><div class="icon">✅</div><p>No JID selected</p></div>';
                    document.getElementById('onlineContainer').innerHTML = '<div class="empty-state"><div class="icon">🔗</div><p>No JID selected</p></div>';
                }
                await loadJIDs();
            } catch (error) { showToast(error.message, 'error'); }
        }

        // ===== UI HELPERS =====
        function showCreateJIDModal() { 
            if (userRole !== 'admin') { showToast('Access denied. Admin only.', 'error'); return; }
            document.getElementById('createJIDModal').classList.add('active'); 
        }
        function showUploadModal() { 
            if (userRole !== 'admin') { showToast('Access denied. Admin only.', 'error'); return; }
            if (!currentJIDId) { showToast('Please select a JID first', 'error'); return; }
            document.getElementById('uploadModal').classList.add('active'); 
        }
        function showOnlineLinkModal() { 
            if (userRole !== 'admin') { showToast('Access denied. Admin only.', 'error'); return; }
            if (!currentJIDId) { showToast('Please select a JID first', 'error'); return; }
            document.getElementById('onlineLinkModal').classList.add('active');
            const linkInput = document.getElementById('onlineLinkInput');
            const existingLink = document.querySelector('#onlineContainer a');
            if (existingLink) linkInput.value = existingLink.href;
        }
        function closeModal(modalId) { document.getElementById(modalId).classList.remove('active'); }
        function switchTab(tabName) {
            document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
            document.querySelector(`.tab[onclick*="${tabName}"]`)?.classList.add('active');
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.getElementById(`tab-${tabName}`).classList.add('active');
        }
        function showToast(message, type = 'info') {
            const container = document.getElementById('toastContainer');
            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            toast.textContent = message;
            container.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        }

        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => { if (e.target === modal) modal.classList.remove('active'); });
        });

        loadStages();
        loadJIDs();
    </script>
</body>
</html>
'''

# ===== API ROUTES =====

@app.route('/api/stages', methods=['GET'])
@login_required
def get_stages():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM stages ORDER BY sort_order")
            stages = cur.fetchall()
            return jsonify(stages)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/jids', methods=['GET'])
@login_required
def get_jids():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT 
                    j.id,
                    j.jid_code,
                    j.status,
                    j.created_at,
                    j.updated_at,
                    s.stage_name,
                    COUNT(DISTINCT f.id) as file_count,
                    COUNT(DISTINCT c.id) as checklist_total,
                    SUM(CASE WHEN c.is_checked THEN 1 ELSE 0 END) as checklist_done
                FROM jids j
                JOIN stages s ON j.stage_id = s.id
                LEFT JOIN files f ON j.id = f.jid_id
                LEFT JOIN checklist_items c ON j.id = c.jid_id
                GROUP BY j.id, j.jid_code, j.status, j.created_at, j.updated_at, s.stage_name
                ORDER BY s.stage_name, j.jid_code
            """)
            jids = cur.fetchall()
            result = []
            for jid in jids:
                total = jid['checklist_total'] or 0
                done = jid['checklist_done'] or 0
                progress = (done / total * 100) if total > 0 else 0
                result.append({
                    'id': jid['id'],
                    'jid_code': jid['jid_code'],
                    'stage_name': jid['stage_name'],
                    'status': jid['status'],
                    'file_count': jid['file_count'] or 0,
                    'checklist_progress': round(progress, 1),
                    'created_at': jid['created_at'],
                    'updated_at': jid['updated_at']
                })
            return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/jids', methods=['POST'])
@admin_required
def create_jid():
    data = request.json
    jid_code = data.get('jid_code', '').upper()
    stage_name = data.get('stage_name')
    if not jid_code or not stage_name:
        return jsonify({'error': 'JID code and stage are required'}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM stages WHERE stage_name = %s", (stage_name,))
            stage = cur.fetchone()
            if not stage:
                return jsonify({'error': f'Stage "{stage_name}" not found'}), 400
            stage_id = stage['id']
            cur.execute("SELECT id FROM jids WHERE jid_code = %s", (jid_code,))
            if cur.fetchone():
                return jsonify({'error': f'JID "{jid_code}" already exists'}), 400
            cur.execute("INSERT INTO jids (jid_code, stage_id, status) VALUES (%s, %s, 'pending') RETURNING id", (jid_code, stage_id))
            jid_id = cur.fetchone()['id']
            conn.commit()
            return jsonify({'id': jid_id, 'jid_code': jid_code, 'stage_name': stage_name, 'message': 'JID created successfully'}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/jids/<int:jid_id>', methods=['DELETE'])
@admin_required
def delete_jid(jid_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT j.*, s.stage_name FROM jids j JOIN stages s ON j.stage_id = s.id WHERE j.id = %s", (jid_id,))
            jid = cur.fetchone()
            if not jid:
                return jsonify({'error': 'JID not found'}), 404
            jid_code = jid['jid_code']
            stage_name = jid['stage_name']
            cur.execute("DELETE FROM jids WHERE id = %s", (jid_id,))
            conn.commit()
            jid_folder = os.path.join(FILE_BASE_PATH, stage_name, jid_code)
            if os.path.exists(jid_folder):
                shutil.rmtree(jid_folder)
            return jsonify({'message': 'JID deleted successfully'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/materials/<int:jid_id>', methods=['GET'])
@login_required
def get_materials(jid_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT f.*, j.jid_code FROM files f JOIN jids j ON f.jid_id = j.id WHERE f.jid_id = %s ORDER BY f.file_type", (jid_id,))
            files = cur.fetchall()
            for file in files:
                file['download_url'] = f"/api/files/download/{file['id']}"
            return jsonify(files)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/upload/<int:jid_id>', methods=['POST'])
@admin_required
def upload_file(jid_id):
    file_type = request.form.get('file_type')
    file = request.files.get('file')
    if not file or not file_type:
        return jsonify({'error': 'File and file_type are required'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT j.*, s.stage_name FROM jids j JOIN stages s ON j.stage_id = s.id WHERE j.id = %s", (jid_id,))
            jid = cur.fetchone()
            if not jid:
                return jsonify({'error': 'JID not found'}), 404
            jid_code = jid['jid_code']
            stage_name = jid['stage_name']
        file_path = save_file(file, jid_code, stage_name, file_type)
        if not file_path:
            return jsonify({'error': 'Failed to save file'}), 500
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM files WHERE jid_id = %s AND file_type = %s", (jid_id, file_type))
            existing = cur.fetchone()
            if existing:
                cur.execute("UPDATE files SET filename = %s, file_path = %s, version = version + 1, uploaded_at = CURRENT_TIMESTAMP WHERE jid_id = %s AND file_type = %s RETURNING id", (file.filename, file_path, jid_id, file_type))
                file_id = cur.fetchone()[0]
            else:
                cur.execute("INSERT INTO files (jid_id, file_type, filename, file_path) VALUES (%s, %s, %s, %s) RETURNING id", (jid_id, file_type, file.filename, file_path))
                file_id = cur.fetchone()[0]
            conn.commit()
            return jsonify({'id': file_id, 'file_type': file_type, 'filename': file.filename, 'message': 'File uploaded successfully'}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/files/download/<int:file_id>', methods=['GET'])
@login_required
def download_file(file_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM files WHERE id = %s", (file_id,))
            file = cur.fetchone()
            if not file:
                return jsonify({'error': 'File not found'}), 404
            if not os.path.exists(file['file_path']):
                return jsonify({'error': 'File not found on server'}), 404
            return send_file(file['file_path'], as_attachment=False, download_name=file['filename'])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/files/<int:file_id>', methods=['DELETE'])
@admin_required
def delete_file(file_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT file_path FROM files WHERE id = %s", (file_id,))
            result = cur.fetchone()
            if not result:
                return jsonify({'error': 'File not found'}), 404
            file_path = result[0]
            cur.execute("DELETE FROM files WHERE id = %s", (file_id,))
            conn.commit()
            if os.path.exists(file_path):
                os.remove(file_path)
            return jsonify({'message': 'File deleted successfully'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/checklist/<int:jid_id>/<string:sub_stage>', methods=['GET'])
@login_required
def get_checklist_by_stage(jid_id, sub_stage):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT c.* FROM checklist_items c JOIN stages s ON c.stage_id = s.id WHERE c.jid_id = %s AND s.stage_name = %s ORDER BY c.id", (jid_id, sub_stage))
            checklist = cur.fetchall()
            return jsonify(checklist)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/checklist/<int:jid_id>/<string:sub_stage>/<string:item_key>', methods=['PUT'])
@admin_required
def update_checklist_item(jid_id, sub_stage, item_key):
    data = request.json
    is_checked = data.get('is_checked', False)
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE checklist_items SET is_checked = %s, updated_at = CURRENT_TIMESTAMP
                FROM stages s
                WHERE checklist_items.stage_id = s.id AND s.stage_name = %s
                AND checklist_items.jid_id = %s AND checklist_items.item_key = %s
                RETURNING checklist_items.id
            """, (is_checked, sub_stage, jid_id, item_key))
            if not cur.fetchone():
                return jsonify({'error': 'Checklist item not found'}), 404
            conn.commit()
            return jsonify({'message': 'Checklist updated successfully'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/checklist/<int:jid_id>/<string:sub_stage>/reset', methods=['POST'])
@admin_required
def reset_checklist_by_stage(jid_id, sub_stage):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE checklist_items SET is_checked = FALSE, updated_at = CURRENT_TIMESTAMP
                FROM stages s
                WHERE checklist_items.stage_id = s.id AND s.stage_name = %s
                AND checklist_items.jid_id = %s
            """, (sub_stage, jid_id))
            conn.commit()
            return jsonify({'message': 'Checklist reset successfully'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/online/<int:jid_id>', methods=['GET'])
@login_required
def get_online_link(jid_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM online_links WHERE jid_id = %s ORDER BY updated_at DESC LIMIT 1", (jid_id,))
            link = cur.fetchone()
            return jsonify(link if link else {})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/online/<int:jid_id>', methods=['POST'])
@admin_required
def update_online_link(jid_id):
    data = request.json
    link_url = data.get('link_url')
    if not link_url:
        return jsonify({'error': 'Link URL is required'}), 400
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM jids WHERE id = %s", (jid_id,))
            if not cur.fetchone():
                return jsonify({'error': 'JID not found'}), 404
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO online_links (jid_id, link_url, verified, updated_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (jid_id) 
                DO UPDATE SET link_url = EXCLUDED.link_url, verified = EXCLUDED.verified, updated_at = CURRENT_TIMESTAMP
            """, (jid_id, link_url, False))
            conn.commit()
        return jsonify({'message': 'Online link updated successfully'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/online/<int:jid_id>', methods=['DELETE'])
@admin_required
def delete_online_link(jid_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM online_links WHERE jid_id = %s", (jid_id,))
            conn.commit()
            return jsonify({'message': 'Online link deleted successfully'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/export/<int:jid_id>', methods=['GET'])
@login_required
def export_jid_data(jid_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT j.*, s.stage_name FROM jids j JOIN stages s ON j.stage_id = s.id WHERE j.id = %s", (jid_id,))
            jid = cur.fetchone()
            if not jid:
                return jsonify({'error': 'JID not found'}), 404
            cur.execute("SELECT * FROM files WHERE jid_id = %s", (jid_id,))
            files = cur.fetchall()
            cur.execute("SELECT c.*, s.stage_name FROM checklist_items c JOIN stages s ON c.stage_id = s.id WHERE c.jid_id = %s", (jid_id,))
            checklists = cur.fetchall()
            cur.execute("SELECT * FROM online_links WHERE jid_id = %s", (jid_id,))
            online_link = cur.fetchone()
            export_data = {
                'jid': jid,
                'files': files,
                'checklists': checklists,
                'online_link': online_link,
                'exported_at': datetime.now().isoformat()
            }
            return jsonify(export_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# ===== CREATE USERS TABLE =====
def create_users_table():
    conn = get_db_connection()
    if not conn:
        print("❌ Cannot connect to database to create users table")
        return
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    full_name VARCHAR(100),
                    email VARCHAR(100),
                    role VARCHAR(20) DEFAULT 'user',
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP
                )
            """)
            conn.commit()
            print("✅ Users table created successfully")
    except Exception as e:
        print(f"❌ Error creating users table: {e}")
    finally:
        conn.close()

# ===== CREATE DEFAULT ADMIN USER =====
def create_default_admin():
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Check if admin exists
            cur.execute("SELECT id FROM users WHERE username = 'admin'")
            if not cur.fetchone():
                # Create default admin
                hashed_password = hash_password('admin123')
                cur.execute("""
                    INSERT INTO users (username, password_hash, full_name, role)
                    VALUES (%s, %s, %s, %s)
                """, ('admin', hashed_password, 'Administrator', 'admin'))
                conn.commit()
                print("✅ Default admin user created: admin / admin123")
            else:
                print("ℹ️ Default admin user already exists")
    except Exception as e:
        print(f"❌ Error creating default admin: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 JID Management Dashboard")
    print("=" * 60)
    
    # Create users table
    create_users_table()
    
    # Create default admin
    create_default_admin()
    
    print(f"📁 Files stored in: {FILE_BASE_PATH}")
    print(f"🌐 Server: http://localhost:5000")
    print("=" * 60)
    print("🔑 Login at: http://localhost:5000/login")
    print("📝 Signup at: http://localhost:5000/signup")
    print("=" * 60)
    print("Default Admin: admin / admin123")
    print("Default User:  user / user123")
    print("=" * 60)
    
    app.run(debug=True, host='0.0.0.0', port=5000)
