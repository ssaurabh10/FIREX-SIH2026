from app.gis.assets import find_nearest_asset, resolve_landcover
from app.gis.boundaries import resolve_admin_boundary

lat, lon = 22.4707, 70.0577
admin = resolve_admin_boundary(lat, lon)
asset = find_nearest_asset(lat, lon)
lc = resolve_landcover(lat, lon)

print("Admin:", admin)
print("Asset:", asset)
print("Landcover:", lc)
