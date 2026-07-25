<<<<<<< HEAD
import psycopg2

DB_CONFIG = {
    'host': 'localhost',
    'database': 'jid_dashboard',
    'user': 'postgres',
    'password': '6r6wyur*Gk1&25',  # Change this to your actual password
    'port': '5432'
}

try:
    conn = psycopg2.connect(**DB_CONFIG)
    print("✅ Database connection successful!")
    
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM jids")
        count = cur.fetchone()[0]
        print(f"📊 Total JIDs in database: {count}")
        
    conn.close()
except Exception as e:
=======
import psycopg2

DB_CONFIG = {
    'host': 'localhost',
    'database': 'jid_dashboard',
    'user': 'postgres',
    'password': '6r6wyur*Gk1&25',  # Change this to your actual password
    'port': '5432'
}

try:
    conn = psycopg2.connect(**DB_CONFIG)
    print("✅ Database connection successful!")
    
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM jids")
        count = cur.fetchone()[0]
        print(f"📊 Total JIDs in database: {count}")
        
    conn.close()
except Exception as e:
>>>>>>> 63edfcaebc19798646b9f69bd786feee81dceafd
    print(f"❌ Database connection failed: {e}")