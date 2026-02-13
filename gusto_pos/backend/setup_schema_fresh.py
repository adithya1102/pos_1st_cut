import psycopg2
import sys

try:
    conn = psycopg2.connect(
        host='127.0.0.1',
        user='gusto_admin',
        password='gusto_password',
        database='gusto_pos_v2'
    )
    cursor = conn.cursor()
    print('Connected to database...')
    
    # Drop all tables in reverse order of dependencies
    print('Dropping existing tables...')
    cursor.execute("""
        DROP TABLE IF EXISTS menu_history CASCADE;
        DROP TABLE IF EXISTS daily_sales_summary CASCADE;
        DROP TABLE IF EXISTS sync_logs CASCADE;
        DROP TABLE IF EXISTS audit_logs CASCADE;
        DROP TABLE IF EXISTS payments CASCADE;
        DROP TABLE IF EXISTS order_items CASCADE;
        DROP TABLE IF EXISTS orders CASCADE;
        DROP TABLE IF EXISTS inventory CASCADE;
        DROP TABLE IF EXISTS item_modifiers CASCADE;
        DROP TABLE IF EXISTS menu_items CASCADE;
        DROP TABLE IF EXISTS menu_categories CASCADE;
        DROP TABLE IF EXISTS menus CASCADE;
        DROP TABLE IF EXISTS otp_validations CASCADE;
        DROP TABLE IF EXISTS tables CASCADE;
        DROP TABLE IF EXISTS users CASCADE;
        DROP TABLE IF EXISTS outlets CASCADE;
        DROP TABLE IF EXISTS categories CASCADE;
        DROP TABLE IF EXISTS products CASCADE;
        DROP TABLE IF EXISTS customers CASCADE;
        DROP TABLE IF EXISTS roles CASCADE;
        DROP TABLE IF EXISTS organizations CASCADE;
    """)
    conn.commit()
    print('✓ Old tables dropped')
    
    # Read and execute new SQL
    with open('schema.sql', 'r') as f:
        sql_script = f.read()
    
    # Execute all statements
    cursor.execute(sql_script)
    conn.commit()
    
    print('✓ Database schema created successfully')
    print('✓ All tables created successfully')
    print('✓ Default roles seeded: Owner, Manager, Kitchen, Waiter')
    
    # Verify tables exist
    cursor.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public' 
        ORDER BY table_name;
    """)
    tables = cursor.fetchall()
    print(f'\n✓ Total tables created: {len(tables)}')
    for table in tables:
        print(f'  - {table[0]}')
    
    cursor.close()
    conn.close()
except psycopg2.Error as e:
    print(f'Database error: {e}')
    sys.exit(1)
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)
