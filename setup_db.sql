-- Drop existing database if it exists
DROP DATABASE IF EXISTS jid_dashboard;

-- Create fresh database
CREATE DATABASE jid_dashboard;

-- Connect to the new database
\c jid_dashboard;

-- Create stages table
CREATE TABLE stages (
    id SERIAL PRIMARY KEY,
    stage_name VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    sort_order INTEGER DEFAULT 0
);

-- Insert stages
INSERT INTO stages (stage_name, description, sort_order) VALUES
    ('RSVP', 'RSVP Stage', 1),
    ('S100', 'S100 Stage', 2);

-- Create JIDs table
CREATE TABLE jids (
    id SERIAL PRIMARY KEY,
    jid_code VARCHAR(50) UNIQUE NOT NULL,
    stage_id INTEGER REFERENCES stages(id) ON DELETE CASCADE,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

-- Create files table (materials - shared across stages)
CREATE TABLE files (
    id SERIAL PRIMARY KEY,
    jid_id INTEGER REFERENCES jids(id) ON DELETE CASCADE,
    file_type VARCHAR(50) NOT NULL,
    filename VARCHAR(255),
    file_path TEXT,
    version INTEGER DEFAULT 1,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(jid_id, file_type)
);

-- Create checklist_items table (stage-specific)
CREATE TABLE checklist_items (
    id SERIAL PRIMARY KEY,
    jid_id INTEGER REFERENCES jids(id) ON DELETE CASCADE,
    stage_id INTEGER REFERENCES stages(id) ON DELETE CASCADE,
    item_key VARCHAR(50) NOT NULL,
    item_label VARCHAR(100) NOT NULL,
    is_checked BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(jid_id, stage_id, item_key)
);

-- Create online_links table
CREATE TABLE online_links (
    id SERIAL PRIMARY KEY,
    jid_id INTEGER REFERENCES jids(id) ON DELETE CASCADE,
    link_url TEXT,
    link_type VARCHAR(50) DEFAULT 'publication',
    verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(jid_id)
);

-- Create indexes
CREATE INDEX idx_files_jid ON files(jid_id);
CREATE INDEX idx_checklist_jid_stage ON checklist_items(jid_id, stage_id);
CREATE INDEX idx_online_jid ON online_links(jid_id);

-- Insert default checklist items for each stage
-- Insert checklist items for DC stage
INSERT INTO checklist_items (jid_id, stage_id, item_key, item_label)
SELECT 
    j.id,
    s.id,
    items.item_key,
    items.item_label
FROM jids j
CROSS JOIN stages s
CROSS JOIN (
    VALUES 
        ('abstract_reviewed', 'Abstract Reviewed'),
        ('corrections_applied', 'Corrections Applied'),
        ('sample_verified', 'Sample Verified'),
        ('xml_validated', 'XML Validated')
) AS items(item_key, item_label)
WHERE s.stage_name = 'RSVP';

-- Insert checklist items for QC stage
INSERT INTO checklist_items (jid_id, stage_id, item_key, item_label)
SELECT 
    j.id,
    s.id,
    items.item_key,
    items.item_label
FROM jids j
CROSS JOIN stages s
CROSS JOIN (
    VALUES 
        ('quality_checked', 'Quality Checked'),
        ('corrections_verified', 'Corrections Verified'),
        ('format_verified', 'Format Verified'),
        ('xml_validated', 'XML Validated')
) AS items(item_key, item_label)
WHERE s.stage_name = 'S100';

-- Show tables
\dt