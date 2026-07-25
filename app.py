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