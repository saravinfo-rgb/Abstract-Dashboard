import psycopg2
from psycopg2.extras import RealDictCursor
import os
import re

# ===== CONFIGURATION =====
DB_CONFIG = {
    'host': 'localhost',
    'database': 'jid_dashboard',
    'user': 'postgres',
    'password': '6r6wyur*Gk1&25',  # Change this to your actual password
    'port': '5432'
}

def get_db_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        return None

def read_jids_from_file():
    """Read JIDs from JIDs.txt file - simplified parser"""
    try:
        with open('JIDs.txt', 'r', encoding='utf-8') as f:
            content = f.read()
        
        print(f"📄 Read file with {len(content)} characters")
        
        # Split by lines
        lines = content.split('\n')
        print(f"📄 Found {len(lines)} lines")
        
        stages = {}
        current_stage = None
        
        # Process each line
        for i, line in enumerate(lines):
            line = line.strip()
            
            # Skip empty lines
            if not line:
                continue
            
            # Check if this is a stage name (uppercase, no dashes)
            # Stage names: RSVP, S100, etc.
            if line.isupper() or (line[0].isupper() and len(line) <= 10):
                # Check if next line has dashes
                if i + 1 < len(lines) and ('------' in lines[i + 1] or '-----' in lines[i + 1]):
                    # This is a stage name
                    current_stage = line
                    stages[current_stage] = []
                    print(f"  📌 Found stage: {current_stage}")
                    continue
            
            # Check if this line has dashes (skip it)
            if '------' in line or '-----' in line:
                continue
            
            # If we have a current stage and this is a JID (uppercase)
            if current_stage and line and line.isupper():
                # Skip if it looks like a section header
                if line not in ['GRAND TOTAL', 'Grand Total']:
                    stages[current_stage].append(line)
        
        # Remove empty stages
        stages = {k: v for k, v in stages.items() if k and v}
        
        print(f"\n📊 Parsing Summary:")
        if stages:
            for stage, jids in stages.items():
                print(f"  📌 {stage}: {len(jids)} JIDs")
                if len(jids) > 0:
                    print(f"     First 5: {', '.join(jids[:5])}")
        else:
            print("  ❌ No stages found")
        
        return stages
        
    except FileNotFoundError:
        print("❌ JIDs.txt file not found!")
        print("   Please make sure JIDs.txt is in the current directory.")
        return None
    except Exception as e:
        print(f"❌ Error reading JIDs.txt: {e}")
        import traceback
        traceback.print_exc()
        return None

def import_jids():
    print("=" * 60)
    print("📊 JID Import Tool")
    print("=" * 60)
    
    stages = read_jids_from_file()
    if not stages:
        print("❌ No stages found in JIDs.txt")
        print("\n📄 Please check that your file has this format:")
        print("   RSVP")
        print("   ------")
        print("   ACEPJO")
        print("   ANNONC")
        print("   ...")
        return
    
    print(f"\n📁 Found {len(stages)} stages:")
    for stage, jids in stages.items():
        print(f"  📌 {stage}: {len(jids)} JIDs")
    
    conn = get_db_connection()
    if not conn:
        print("❌ Cannot connect to database. Please check your credentials.")
        return
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print("\n📥 Importing JIDs to database...")
            
            for stage_name, jids in stages.items():
                # Get or create stage
                cur.execute("SELECT id FROM stages WHERE stage_name = %s", (stage_name,))
                stage_result = cur.fetchone()
                
                if not stage_result:
                    print(f"  ⚠️ Stage '{stage_name}' not found, creating...")
                    cur.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 as next_order FROM stages")
                    next_order = cur.fetchone()['next_order']
                    
                    cur.execute("""
                        INSERT INTO stages (stage_name, description, sort_order)
                        VALUES (%s, %s, %s)
                        RETURNING id
                    """, (stage_name, f'{stage_name} Stage', next_order))
                    stage_id = cur.fetchone()['id']
                    conn.commit()
                    print(f"  ✅ Created stage: {stage_name}")
                else:
                    stage_id = stage_result['id']
                    print(f"  ✅ Found existing stage: {stage_name}")
                
                imported_count = 0
                skipped_count = 0
                
                for jid_code in jids:
                    jid_code = jid_code.strip()
                    if not jid_code:
                        continue
                    
                    # Check if JID already exists
                    cur.execute("SELECT id FROM jids WHERE jid_code = %s", (jid_code,))
                    existing = cur.fetchone()
                    
                    if existing:
                        print(f"  ⏭️ JID {jid_code} already exists, skipping...")
                        skipped_count += 1
                        continue
                    
                    # Insert JID
                    cur.execute("""
                        INSERT INTO jids (jid_code, stage_id, status)
                        VALUES (%s, %s, 'pending')
                        RETURNING id
                    """, (jid_code, stage_id))
                    jid_id = cur.fetchone()['id']
                    
                    # Get all stages for checklist
                    cur.execute("SELECT id, stage_name FROM stages")
                    all_stages = cur.fetchall()
                    
                    # Define checklist items for each stage
                    checklist_items_map = {
                        'RSVP': [
                            ('abstract_reviewed', 'Abstract Reviewed'),
                            ('corrections_applied', 'Corrections Applied'),
                            ('sample_verified', 'Sample Verified'),
                            ('xml_validated', 'XML Validated')
                        ],
                        'S100': [
                            ('quality_checked', 'Quality Checked'),
                            ('corrections_verified', 'Corrections Verified'),
                            ('format_verified', 'Format Verified'),
                            ('xml_validated', 'XML Validated')
                        ]
                    }
                    
                    default_items = [
                        ('reviewed', 'Reviewed'),
                        ('approved', 'Approved'),
                        ('completed', 'Completed')
                    ]
                    
                    for stage in all_stages:
                        stage_name_check = stage['stage_name']
                        stage_id_check = stage['id']
                        items = checklist_items_map.get(stage_name_check, default_items)
                        
                        for item_key, item_label in items:
                            try:
                                cur.execute("""
                                    INSERT INTO checklist_items (jid_id, stage_id, item_key, item_label)
                                    VALUES (%s, %s, %s, %s)
                                    ON CONFLICT (jid_id, stage_id, item_key) DO NOTHING
                                """, (jid_id, stage_id_check, item_key, item_label))
                            except Exception as e:
                                print(f"  ⚠️ Error adding checklist item {item_key}: {e}")
                    
                    imported_count += 1
                    if imported_count % 5 == 0:
                        print(f"  ✅ Imported {imported_count} JIDs...")
                
                print(f"\n  📊 {stage_name}: {imported_count} imported, {skipped_count} skipped")
                conn.commit()
            
            print("\n" + "=" * 60)
            print("📊 Import Summary")
            print("=" * 60)
            
            cur.execute("""
                SELECT s.stage_name, COUNT(j.id) as total
                FROM stages s
                LEFT JOIN jids j ON s.id = j.stage_id
                GROUP BY s.stage_name, s.sort_order
                ORDER BY s.sort_order
            """)
            summary = cur.fetchall()
            
            for row in summary:
                print(f"  📌 {row['stage_name']}: {row['total']} JIDs")
            
            cur.execute("SELECT COUNT(*) as total FROM jids")
            total = cur.fetchone()['total']
            print(f"\n  ✅ Total JIDs in database: {total}")
            
            cur.execute("SELECT COUNT(*) as total FROM checklist_items")
            total_items = cur.fetchone()['total']
            print(f"  ✅ Total checklist items: {total_items}")
            
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error importing JIDs: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()
        print("\n✅ Import completed!")

def check_database_status():
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print("\n📊 Database Status:")
            print("-" * 40)
            
            cur.execute("SELECT COUNT(*) as total FROM stages")
            stages_count = cur.fetchone()['total']
            print(f"  Stages: {stages_count}")
            
            cur.execute("SELECT COUNT(*) as total FROM jids")
            jids_count = cur.fetchone()['total']
            print(f"  JIDs: {jids_count}")
            
            cur.execute("SELECT COUNT(*) as total FROM checklist_items")
            checklist_count = cur.fetchone()['total']
            print(f"  Checklist Items: {checklist_count}")
            
            cur.execute("SELECT COUNT(*) as total FROM files")
            files_count = cur.fetchone()['total']
            print(f"  Files: {files_count}")
            
            print("-" * 40)
    except Exception as e:
        print(f"❌ Error checking database: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    import_jids()
    check_database_status()
    
    print("\n📝 Next Steps:")
    print("  1. Run: python create_folders.py")
    print("  2. Run: python app.py")
    print("  3. Open: http://localhost:5000")