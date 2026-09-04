# FIREX --- Section 1 Configuration
# ===================================
# Copy this file to config.py and fill in your MAP_KEY.
#
# Get your free MAP_KEY at:
#   https://firms.modaps.eosdis.nasa.gov/usfs/api/area/
#
# DO NOT commit config.py to version control — it contains your API key.

# Your NASA FIRMS MAP key
MAP_KEY = "YOUR_MAP_KEY_HERE"

# Geographic area to query (World, or a country code like "IND" for India)
# Use world-bounding-box format: "W,S,E,N" (lon-min, lat-min, lon-max, lat-max)
# Example for India: "68,6,98,38"
# Example for global: "world"
REGION = "IND"   # India — good for industrial fire context

# Number of past days to fetch (1, 2, ..., up to 10)
DAYS = 2

# FIRMS products to query
# Available: MODIS_NRT, VIIRS_SNPP_NRT, VIIRS_NOAA20_NRT, VIIRS_NOAA21_NRT
PRODUCTS = [
    "VIIRS_NOAA20_NRT",   # NOAA-20 (JPSS-1) VIIRS — newer, higher resolution
    "VIIRS_SNPP_NRT",     # Suomi NPP VIIRS
    "MODIS_NRT",          # Terra/Aqua MODIS
]
