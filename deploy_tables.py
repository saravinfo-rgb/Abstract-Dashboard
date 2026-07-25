import psycopg2

try:
    print("Connecting directly to Render Cloud Host...")
    
    # Explicit parameters to bypass all local settings
    conn = psycopg2.connect(
        host="dpg-d9hkepupbkes73a8pqeg-a.oregon-postgres.render.com",
        database="jid_dashboard",
        user="jid_dashboard_user",
        password="0CyDe4l5wcz0rmcRb94jVdkPYk55hP5d",
        port=5432,
        sslmode="require"
    )
    cursor = conn.cursor()
    
    print("Reading setup_db.sql file...")
    with open('setup_db.sql', 'r', encoding='utf-8') as f:
        sql_script = f.read()
        
    print("Executing database setup scripts...")
    cursor.execute(sql_script)
    conn.commit()
    
    print("Success! All tables created successfully on Render. 🎉")
    cursor.close()
    conn.close()

except Exception as e:
    print("\nAn error occurred during deployment:")
    print(e)
