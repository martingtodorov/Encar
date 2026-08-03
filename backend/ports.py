"""UN/LOCODE coordinates for the ports on the Korea -> Europe car route.

A geocoding service would be another dependency and another key for data that never
changes, so the handful of ports these shipments actually call at are kept here. Anything
unknown simply has no marker on the map: the timeline still shows the port by name.
Coordinates are the port basins, rounded to 2dp, which is well inside a map marker.
"""

PORTS = {
    # Korea (origin) and East Asia transhipment
    "KRPUS": ("Busan", 35.10, 129.04),
    "KRINC": ("Incheon", 37.45, 126.60),
    "KRKAN": ("Gwangyang", 34.90, 127.70),
    "KRUSN": ("Ulsan", 35.50, 129.38),
    "KRPTK": ("Pyeongtaek", 36.97, 126.82),
    "KRMAS": ("Masan", 35.19, 128.58),
    "CNSHA": ("Shanghai", 31.23, 121.49),
    "CNNGB": ("Ningbo", 29.87, 121.55),
    "CNYTN": ("Yantian", 22.59, 114.27),
    "CNTAO": ("Qingdao", 36.09, 120.32),
    "HKHKG": ("Hong Kong", 22.30, 114.13),
    "TWKHH": ("Kaohsiung", 22.61, 120.28),
    # South and South-East Asia
    "SGSIN": ("Singapore", 1.26, 103.83),
    "MYPKG": ("Port Klang", 3.00, 101.39),
    "MYTPP": ("Tanjung Pelepas", 1.36, 103.55),
    "LKCMB": ("Colombo", 6.95, 79.84),
    "INNSA": ("Nhava Sheva", 18.95, 72.95),
    # Middle East and Red Sea
    "AEJEA": ("Jebel Ali", 25.01, 55.06),
    "OMSLL": ("Salalah", 16.94, 54.01),
    "SAJED": ("Jeddah", 21.478, 39.16),
    "EGPSD": ("Port Said", 31.25, 32.30),
    "EGSUZ": ("Suez", 29.97, 32.55),
    "EGDAM": ("Damietta", 31.47, 31.76),
    # Mediterranean, Adriatic and Aegean
    "GRPIR": ("Piraeus", 37.94, 23.63),
    "GRSKG": ("Thessaloniki", 40.63, 22.92),
    "ITGIT": ("Gioia Tauro", 38.45, 15.90),
    "ITTRS": ("Trieste", 45.64, 13.76),
    "ITGOA": ("Genoa", 44.40, 8.90),
    "SIKOP": ("Koper", 45.55, 13.73),
    "HRRJK": ("Rijeka", 45.32, 14.44),
    "MTMLA": ("Malta Freeport", 35.82, 14.53),
    "ESALG": ("Algeciras", 36.13, -5.44),
    "ESVLC": ("Valencia", 39.44, -0.31),
    "ESBCN": ("Barcelona", 41.35, 2.17),
    "TRAMB": ("Ambarli", 40.96, 28.68),
    "TRIZM": ("Izmir", 38.44, 27.15),
    "TRMER": ("Mersin", 36.79, 34.63),
    # Black Sea - where Bulgarian and Romanian buyers collect
    "ROCND": ("Constanta", 44.17, 28.65),
    "BGVAR": ("Varna", 43.19, 27.92),
    "BGBOJ": ("Burgas", 42.49, 27.48),
    "UAODS": ("Odesa", 46.49, 30.73),
    "GEPTI": ("Poti", 42.15, 41.66),
    # North Europe
    "NLRTM": ("Rotterdam", 51.95, 4.14),
    "BEANR": ("Antwerp", 51.26, 4.40),
    "DEHAM": ("Hamburg", 53.54, 9.95),
    "DEBRV": ("Bremerhaven", 53.58, 8.57),
    "GBFXT": ("Felixstowe", 51.95, 1.31),
    "PLGDN": ("Gdansk", 54.40, 18.68),
    "LTKLJ": ("Klaipeda", 55.70, 21.13),
}

# Reverse lookup for messages that name the port but omit the code.
_BY_NAME = {name.lower(): (code, lat, lon) for code, (name, lat, lon) in PORTS.items()}


def locate(unloc="", name=""):
    """Coordinates for a port, by UN/LOCODE first and then by name. None when unknown."""
    hit = PORTS.get((unloc or "").strip().upper())
    if hit:
        return {"port": hit[0], "lat": hit[1], "lon": hit[2]}
    n = (name or "").strip().lower()
    if n in _BY_NAME:
        code, lat, lon = _BY_NAME[n]
        return {"port": PORTS[code][0], "lat": lat, "lon": lon}
    return None
