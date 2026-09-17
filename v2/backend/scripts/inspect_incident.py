import sqlite3

conn = sqlite3.connect('v2/backend/data/firex_v2.db')
c = conn.cursor()
c.execute("SELECT id, incident_code, state, district, latitude, longitude, current_max_frp, classification, investigation_priority FROM incidents WHERE id LIKE '%stage5%' OR id LIKE '%pkg%'")
rows = c.fetchall()
print("Found rows:", rows)

if not rows:
    c.execute("SELECT id, incident_code, state, district, latitude, longitude, current_max_frp, classification, investigation_priority FROM incidents ORDER BY investigation_priority DESC LIMIT 5")
    print("Top priority incidents:", c.fetchall())
