"""Update router.py for zone support."""
import os

router_path = os.path.join('app', 'modules', 'tables', 'router.py')

with open(router_path, 'r') as f:
    content = f.read()

# 1. In open_table: add zone to TableSession creation
old_create = '''    session = TableSession(
        outlet_id=data.outlet_id,
        table_id=data.table_id,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=12)
    )'''
new_create = '''    session = TableSession(
        outlet_id=data.outlet_id,
        table_id=data.table_id,
        zone=data.zone,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=12)
    )'''
content = content.replace(old_create, new_create)

# 2. In validate_token - static QR path: return zone from session
old_static_valid = '''        return TableSessionValidate(
            token=token,
            table_id=table_id,
            outlet_id=outlet_id,
            is_valid=True,
            message="Valid"
        )'''
new_static_valid = '''        return TableSessionValidate(
            token=token,
            table_id=table_id,
            outlet_id=outlet_id,
            zone=session.zone or "normal",
            is_valid=True,
            message="Valid"
        )'''
content = content.replace(old_static_valid, new_static_valid)

# 3. In validate_token - dynamic token path: return zone from session
old_dynamic_valid = '''    return TableSessionValidate(
        token=token,
        table_id=session.table_id,
        outlet_id=str(session.outlet_id),
        is_valid=True,
        message="Valid"
    )'''
new_dynamic_valid = '''    return TableSessionValidate(
        token=token,
        table_id=session.table_id,
        outlet_id=str(session.outlet_id),
        zone=session.zone or "normal",
        is_valid=True,
        message="Valid"
    )'''
content = content.replace(old_dynamic_valid, new_dynamic_valid)

with open(router_path, 'w') as f:
    f.write(content)
print(f'Updated {router_path}')
