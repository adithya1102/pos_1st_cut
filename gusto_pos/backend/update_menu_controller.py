"""Add zone-based menu endpoint to controller.py."""
import os

controller_path = os.path.join('app', 'modules', 'menu', 'controller.py')

with open(controller_path, 'r') as f:
    content = f.read()

# Add the zone-menu mapping and endpoint after the router definition
old_router_line = 'router = APIRouter(prefix="/menus", tags=["menus"])'

new_block = '''router = APIRouter(prefix="/menus", tags=["menus"])

# Zone-to-menu mapping for zone-based pricing
ZONE_MENU_MAP = {
    "normal": "dc88b6a6-129c-479f-8609-07b8525f4310",
    "fine_dine": "5ddd464b-f4d3-42d1-a007-10b63659c66f",
}


@router.get("/by-zone/{outlet_id}/{zone}", response_model=MenuResponse)
async def get_menu_by_zone(outlet_id: str, zone: str, db: AsyncSession = Depends(get_db)):
    """Get the correct menu for a given zone (normal or fine_dine)."""
    menu_id = ZONE_MENU_MAP.get(zone, ZONE_MENU_MAP["normal"])
    menu = await MenuService.get_menu_by_id(db, UUID(menu_id))
    if not menu:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu not found")
    return menu'''

content = content.replace(old_router_line, new_block, 1)

with open(controller_path, 'w') as f:
    f.write(content)

print(f'Updated {controller_path}')
