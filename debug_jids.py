<<<<<<< HEAD
import re

print("=" * 60)
print("🔍 Debugging JIDs.txt File")
print("=" * 60)

with open('JIDs.txt', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"\n📄 Total lines: {len(lines)}")
print("\n📄 First 20 lines with character details:")
print("-" * 60)

for i, line in enumerate(lines[:20]):
    # Show line number, raw repr, and stripped version
    stripped = line.strip()
    print(f"{i+1:2d}: {repr(line)}")
    if stripped:
        print(f"    Stripped: '{stripped}'")
        print(f"    Ends with dashes: {stripped.endswith('------') or stripped.endswith('-----')}")
    print()

print("-" * 60)

# Try to find stage headers
print("\n🔍 Looking for stage headers:")
print("-" * 60)

stages = {}
current_stage = None

for i, line in enumerate(lines):
    line = line.strip()
    if not line:
        continue
    
    # Check if this is a stage header (ends with dashes)
    if line.endswith('------') or line.endswith('-----'):
        stage_name = line.replace('------', '').replace('-----', '').strip()
        if stage_name:
            stages[stage_name] = []
            current_stage = stage_name
            print(f"  ✅ Found stage at line {i+1}: '{stage_name}'")
    elif current_stage:
        # Skip if it looks like a section header or grand total
        if line and not line.startswith('---') and line != 'Grand Total':
            # Skip if it's just dashes or empty
            if not re.match(r'^-+$', line):
                stages[current_stage].append(line)

print(f"\n📊 Parsing Result:")
print(f"  Stages found: {len(stages)}")
for stage, jids in stages.items():
    print(f"  📌 {stage}: {len(jids)} JIDs")
    if len(jids) > 0:
=======
import re

print("=" * 60)
print("🔍 Debugging JIDs.txt File")
print("=" * 60)

with open('JIDs.txt', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"\n📄 Total lines: {len(lines)}")
print("\n📄 First 20 lines with character details:")
print("-" * 60)

for i, line in enumerate(lines[:20]):
    # Show line number, raw repr, and stripped version
    stripped = line.strip()
    print(f"{i+1:2d}: {repr(line)}")
    if stripped:
        print(f"    Stripped: '{stripped}'")
        print(f"    Ends with dashes: {stripped.endswith('------') or stripped.endswith('-----')}")
    print()

print("-" * 60)

# Try to find stage headers
print("\n🔍 Looking for stage headers:")
print("-" * 60)

stages = {}
current_stage = None

for i, line in enumerate(lines):
    line = line.strip()
    if not line:
        continue
    
    # Check if this is a stage header (ends with dashes)
    if line.endswith('------') or line.endswith('-----'):
        stage_name = line.replace('------', '').replace('-----', '').strip()
        if stage_name:
            stages[stage_name] = []
            current_stage = stage_name
            print(f"  ✅ Found stage at line {i+1}: '{stage_name}'")
    elif current_stage:
        # Skip if it looks like a section header or grand total
        if line and not line.startswith('---') and line != 'Grand Total':
            # Skip if it's just dashes or empty
            if not re.match(r'^-+$', line):
                stages[current_stage].append(line)

print(f"\n📊 Parsing Result:")
print(f"  Stages found: {len(stages)}")
for stage, jids in stages.items():
    print(f"  📌 {stage}: {len(jids)} JIDs")
    if len(jids) > 0:
>>>>>>> 63edfcaebc19798646b9f69bd786feee81dceafd
        print(f"     First 5: {', '.join(jids[:5])}")