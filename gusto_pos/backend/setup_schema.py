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
    
    # Read and execute SQL
    with open('schema.sql', 'r') as f:
        sql_script = f.read()
    
    # Execute all statements
    cursor.execute(sql_script)
    conn.commit()
    
    print('✓ Database schema created successfully')
    print('✓ Tables created: organizations, customers, roles, outlets, users, tables, menus, menu_categories, menu_items, item_modifiers, orders, order_items, daily_sales_summary')
    print('✓ Default roles seeded: Owner, Manager, Kitchen, Waiter')
    
    cursor.close()
    conn.close()
except psycopg2.Error as e:
    print(f'Database error: {e}')
    sys.exit(1)
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)
