import os
import json

# Read JIDs from file
def read_jids_from_file():
    try:
        with open('JIDs.txt', 'r', encoding='utf-8') as f:
            content = f.read()
        
        lines = content.split('\n')
        stages = {}
        current_stage = None
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            # Check if this is a stage name
            if line.isupper() or (line[0].isupper() and len(line) <= 10):
                if i + 1 < len(lines) and ('------' in lines[i + 1] or '-----' in lines[i + 1]):
                    current_stage = line
                    stages[current_stage] = []
                    continue
            
            # Check if this line has dashes (skip it)
            if '------' in line or '-----' in line:
                continue
            
            # If we have a current stage and this is a JID (uppercase)
            if current_stage and line and line.isupper():
                if line not in ['GRAND TOTAL', 'Grand Total']:
                    stages[current_stage].append(line)
        
        return stages
    except Exception as e:
        print(f"❌ Error reading JIDs.txt: {e}")
        return {}

def create_folders():
    """Create folder structure for all JIDs"""
    print("=" * 60)
    print("📁 Creating Folder Structure")
    print("=" * 60)
    
    # Read JIDs
    stages = read_jids_from_file()
    if not stages:
        print("❌ No JIDs found in JIDs.txt")
        return
    
    # Base path for files
    FILE_BASE_PATH = os.path.join(os.path.dirname(__file__), 'files')
    
    # Create folders
    total_folders = 0
    for stage_name, jids in stages.items():
        stage_folder = os.path.join(FILE_BASE_PATH, stage_name)
        os.makedirs(stage_folder, exist_ok=True)
        print(f"\n📌 {stage_name}: {len(jids)} JIDs")
        
        for jid in jids:
            jid_folder = os.path.join(stage_folder, jid)
            os.makedirs(jid_folder, exist_ok=True)
            
            # Create sub-folders for each stage
            sub_stages = ['DC', 'QC', 'Pagination', 'Online']
            for sub_stage in sub_stages:
                sub_folder = os.path.join(jid_folder, sub_stage)
                os.makedirs(sub_folder, exist_ok=True)
                
                # Create default checklist.json
                checklist_path = os.path.join(sub_folder, 'checklist.json')
                if not os.path.exists(checklist_path):
                    default_checklist = {
                        'DC': {
                            'abstract_reviewed': False,
                            'corrections_applied': False,
                            'sample_verified': False,
                            'xml_validated': False,
                            'notes': ''
                        },
                        'QC': {
                            'quality_checked': False,
                            'corrections_verified': False,
                            'format_verified': False,
                            'xml_validated': False,
                            'notes': ''
                        },
                        'Pagination': {
                            'page_numbers_verified': False,
                            'layout_checked': False,
                            'final_approved': False,
                            'notes': ''
                        },
                        'Online': {
                            'online_link_verified': False,
                            'final_approved': False,
                            'publication_ready': False,
                            'notes': ''
                        }
                    }
                    with open(checklist_path, 'w') as f:
                        json.dump(default_checklist.get(sub_stage, {}), f, indent=4)
            
            total_folders += 1
            if total_folders % 10 == 0:
                print(f"  ✅ Created {total_folders} folders...")
    
    print(f"\n" + "=" * 60)
    print(f"✅ Successfully created folders for {total_folders} JIDs")
    print(f"📁 Files stored in: {FILE_BASE_PATH}")
    print("=" * 60)

if __name__ == "__main__":
    create_folders()