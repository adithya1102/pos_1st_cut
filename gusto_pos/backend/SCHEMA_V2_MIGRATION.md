# v2.0 Schema Migration - Implementation Complete

## Overview
The backend has been successfully updated to implement the v2.0 SQL schema. All SQLAlchemy models, Pydantic schemas, and database initialization scripts have been refactored to match the specification exactly.

## Changes Made

### 1. **Module Structure Refactoring**

#### Products → Menu
- **Deprecated**: `app/modules/products/`
- **New**: `app/modules/menu/` with:
  - `model.py`: Menu, MenuCategory, MenuItem, ItemModifier classes
  - `schema.py`: Pydantic schemas for all entities
  - `service.py`: Business logic layer
  - `controller.py`: API endpoints

#### New Module: Customers
- **Path**: `app/modules/customers/`
- Files: `model.py`, `schema.py`, `service.py`, `controller.py`
- **Model**: Customer with id (UUID), name, phone_number (Unique)

### 2. **Database Models (SQLAlchemy)**

#### Organizations (Updated)
- Existing model verified ✓
- Fields: id (UUID), name, gst_number
- Relationships updated with proper cascading

#### Outlets (Enhanced)
- **New Field**: `geofence_radius_meters` (Integer, default 100)
- **New Relationship**: `tables` → Links to Table model
- **New Relationship**: `menus` → Links to Menu model
- **New Relationship**: `orders` → Links to Order model

#### Tables (NEW)
- **Path**: `app/modules/outlets/model.py`
- Fields:
  - id (UUID, PK)
  - outlet_id (FK to outlets)
  - table_number (Integer)
  - status (Enum: AVAILABLE, OCCUPIED, RESERVED)
- Relationships: outlet, orders

#### Users (Updated)
- **Existing Fields**: Verified and working
  - id (UUID)
  - username (String, unique)
  - hashed_password (String)
  - is_active (Boolean)
  - role_id (FK to roles - Integer)
  - outlet_id (FK to outlets - UUID)
- **Foreign Keys**: Properly configured

#### Roles (Verified)
- **ID Type**: Integer (Serial/AutoIncrement) ✓
- Fields: id (Integer), name (String, unique), permissions (JSON/JSONB)

#### Menu (NEW)
- Fields:
  - id (UUID, PK)
  - outlet_id (FK to outlets)
  - version_label (String)
  - is_latest (Boolean)
- Relationships: outlet, categories

#### MenuCategory (NEW)
- Fields:
  - id (UUID, PK)
  - menu_id (FK to menus)
  - name (String)
- Relationships: menu, items

#### MenuItem (NEW)
- Fields:
  - id (UUID, PK)
  - category_id (FK to menu_categories)
  - name (String)
  - short_code (String, unique)
  - base_price (Decimal)
  - is_veg (Boolean)
  - is_active (Boolean)
- Relationships: category, modifiers

#### ItemModifier (NEW)
- Fields:
  - id (UUID, PK)
  - menu_item_id (FK to menu_items)
  - name (String)
  - description (String, optional)
  - price_adjustment (Decimal)
- Relationships: menu_item

#### Orders (Refactored)
- **New Fields**:
  - readable_id (Integer, Serial, Unique)
  - table_id (FK to tables, optional)
  - customer_id (FK to customers, optional)
  - order_status (Enum: PENDING, CONFIRMED, IN_KITCHEN, READY, SERVED, COMPLETED, CANCELLED)
  - kitchen_token (String, optional)
- **Updated Fields**:
  - outlet_id (FK, not optional)
  - total_amount (Decimal, not optional)
- **Relationships**: outlet, table, customer, items

#### Customers (NEW)
- Fields:
  - id (UUID, PK)
  - name (String)
  - phone_number (String, unique)
- Relationships: orders

### 3. **Pydantic Schemas (Updated)**

All schemas updated for Pydantic v2 compatibility:
- Changed `orm_mode = True` → `from_attributes = True`
- Added comprehensive request/response schemas
- Proper type hints and validation

**New Schema Files**:
- `menu/schema.py`: MenuCreate, MenuResponse, MenuCategoryCreate, MenuItemCreate, MenuItemResponse, ItemModifierCreate, ItemModifierResponse
- `customers/schema.py`: CustomerCreate, CustomerUpdate, CustomerResponse
- `outlets/schema.py`: TableCreate, TableRead, TableUpdate + OutletCreate, OutletRead, OutletUpdate

**Updated Schema Files**:
- `users/schema.py`: Added UserUpdate schema
- `orders/schema.py`: Complete refactor with OrderCreate, OrderUpdate, OrderRead
- `categories/schema.py`: Added CategoryCreate, CategoryUpdate

### 4. **Database Initialization**

#### New File: `app/core/init_db.py`
- Function: `init_initial_data(session: AsyncSession)`
- **Purpose**: Seeds default roles on first run
- **Roles Created**:
  1. **Owner**: Full permissions (view_dashboard, manage_staff, manage_inventory, view_reports, manage_menus, manage_outlets, manage_organizations, manage_payments, view_audit_logs)
  2. **Manager**: Limited permissions (excludes view_audit_logs and organization/outlet management)
  3. **Kitchen**: Kitchen-specific permissions (view_orders, update_order_status, view_kitchen_queue, print_kitchen_ticket)
  4. **Waiter**: Waiter-specific permissions (create_orders, view_orders, update_order_items, manage_tables, process_payments, view_menu)

#### Updated: `app/core/database.py`
- Imports all new models for proper SQLAlchemy registration
- Models imported: Menu, MenuCategory, MenuItem, ItemModifier, Table, Customer

#### Updated: `app/main.py`
- New import: `from app.core.init_db import init_initial_data`
- New import: `from app.modules.customers.controller`
- New import: `from app.modules.menu.controller`
- Updated router: Removed products_router, added menu_router and customers_router
- Updated startup event: Calls `init_initial_data()` after `init_db()`

### 5. **API Endpoints**

#### New Routes: `/api/v1/menus`
- POST `/` - Create menu
- GET `/{menu_id}` - Get menu
- GET `/outlet/{outlet_id}` - Get outlet's menus
- PUT `/{menu_id}` - Update menu
- DELETE `/{menu_id}` - Delete menu
- POST `/categories/` - Create category
- GET `/categories/{category_id}` - Get category
- GET `/categories/menu/{menu_id}` - Get menu's categories
- DELETE `/categories/{category_id}` - Delete category
- POST `/items/` - Create menu item
- GET `/items/{item_id}` - Get menu item
- GET `/items/category/{category_id}` - Get category's items
- PUT `/items/{item_id}` - Update menu item
- DELETE `/items/{item_id}` - Delete menu item
- POST `/modifiers/{menu_item_id}` - Create modifier
- GET `/modifiers/{modifier_id}` - Get modifier
- GET `/modifiers/item/{menu_item_id}` - Get item's modifiers
- DELETE `/modifiers/{modifier_id}` - Delete modifier

#### New Routes: `/api/v1/customers`
- POST `/` - Create customer
- GET `/{customer_id}` - Get customer
- GET `/phone/{phone_number}` - Get customer by phone
- GET `/` - List all customers
- PUT `/{customer_id}` - Update customer
- DELETE `/{customer_id}` - Delete customer

## Verification Checklist

✓ All models import successfully
✓ Database initialization logic implemented
✓ Seeding function created and working
✓ All schemas updated for Pydantic v2
✓ Foreign keys properly configured
✓ UUID vs Integer ID distinction maintained
✓ API routers updated and registered
✓ All relationships properly defined

## Running the System

### Start Database
```powershell
cd gusto_pos\backend
docker-compose up -d db
```

### Initialize Schema
```powershell
docker-compose up -d web
```

The application will:
1. Connect to the database
2. Create all tables based on models
3. Seed default roles if they don't exist

### API Endpoints
- Documentation: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

## Key Implementation Details

### Foreign Key Relationships
- `organizations` ← `outlets.organization_id`
- `outlets` ← `tables.outlet_id`
- `outlets` ← `menus.outlet_id`
- `menus` ← `menu_categories.menu_id`
- `menu_categories` ← `menu_items.category_id`
- `menu_items` ← `item_modifiers.menu_item_id`
- `roles` ← `users.role_id`
- `outlets` ← `users.outlet_id`
- `outlets` ← `orders.outlet_id`
- `tables` ← `orders.table_id`
- `customers` ← `orders.customer_id`

### Data Type Specifications
- **UUID Fields**: All primary keys except roles
- **Role ID**: Integer (autoincrement)
- **Timestamps**: created_at (all tables)
- **Enums**: OrderStatus, TableStatus, OrderStatusEnum, TableStatusEnum
- **Unique Constraints**: phone_number, short_code, username, role.name

## Next Steps

1. **Test Data Creation**: Use POST endpoints to create test data
2. **Integration Testing**: Verify all relationships work correctly
3. **Performance Testing**: Check query performance with indexes
4. **API Testing**: Use Postman/REST client to test all endpoints
5. **Frontend Integration**: Update frontend to use new endpoints
