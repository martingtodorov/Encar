import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, Tooltip } from "react-leaflet";
import "leaflet/dist/leaflet.css";

/**
 * The route the container takes, drawn from the ports in its own status messages.
 *
 * Circle markers rather than Leaflet's default pin: the default icon is loaded from an
 * asset path that webpack rewrites, which is the classic "markers disappear in production"
 * bug. Solid ports are behind the ship, hollow ones are still ahead, and the dashed leg is
 * the part of the voyage that has not happened yet.
 */
const sea = (m) => Number.isFinite(m?.lat) && Number.isFinite(m?.lon);

export const VesselMap = ({ milestones = [], position, vesselName = "", labelFor }) => {
  const stops = [];
  milestones.filter(sea).forEach((m) => {
    const prev = stops[stops.length - 1];
    // Consecutive events in the same port are one stop on the map.
    if (prev && prev.lat === m.lat && prev.lon === m.lon) {
      prev.events.push(m);
      prev.estimated = prev.estimated && m.estimated;
      return;
    }
    stops.push({ ...m, events: [m] });
  });

  const ship = sea(position) ? [position.lat, position.lon] : null;
  const points = stops.map((s) => [s.lat, s.lon]);
  if (!points.length) return null;

  const doneLeg = stops.filter((s) => !s.estimated).map((s) => [s.lat, s.lon]);
  const aheadStart = Math.max(0, doneLeg.length - 1);
  const aheadLeg = points.slice(aheadStart);
  const all = ship ? [...points, ship] : points;

  return (
    <div
      data-testid="track-map"
      // `isolate` + z-0: Leaflet gives its own panes and controls z-index 400-1000, which
      // sat on top of the site header (z-40). A stacking context of our own keeps all of
      // that inside the map, without touching Leaflet's internal ordering.
      className="relative isolate z-0 h-[320px] w-full overflow-hidden rounded-[12px] border border-border sm:h-[380px]"
    >
      <MapContainer
        bounds={all.length > 1 ? all : undefined}
        center={all.length === 1 ? all[0] : undefined}
        zoom={all.length === 1 ? 5 : undefined}
        boundsOptions={{ padding: [30, 30] }}
        scrollWheelZoom={false}
        worldCopyJump
        style={{ height: "100%", width: "100%", background: "#0b1520" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {doneLeg.length > 1 && (
          <Polyline positions={doneLeg} pathOptions={{ color: "#e11d48", weight: 3 }} />
        )}
        {aheadLeg.length > 1 && (
          <Polyline
            positions={aheadLeg}
            pathOptions={{ color: "#94a3b8", weight: 2, dashArray: "6 8" }}
          />
        )}

        {stops.map((s, i) => (
          <CircleMarker
            key={`${s.lat}-${s.lon}-${i}`}
            center={[s.lat, s.lon]}
            radius={6}
            pathOptions={{
              color: s.estimated ? "#94a3b8" : "#e11d48",
              fillColor: s.estimated ? "#ffffff" : "#e11d48",
              fillOpacity: 1,
              weight: 2,
            }}
          >
            <Tooltip direction="top">{s.location}</Tooltip>
            <Popup>
              <strong>{s.location}</strong>
              <br />
              {s.events.map((e, n) => (
                <span key={n}>
                  {labelFor ? labelFor(e.code) : e.code}
                  {e.estimated ? " (est.)" : ""}
                  <br />
                </span>
              ))}
            </Popup>
          </CircleMarker>
        ))}

        {ship && (
          <CircleMarker
            center={ship}
            radius={9}
            pathOptions={{ color: "#ffffff", fillColor: "#0ea5e9", fillOpacity: 1, weight: 3 }}
          >
            <Tooltip direction="top" permanent>
              {vesselName || "Vessel"}
            </Tooltip>
          </CircleMarker>
        )}
      </MapContainer>
    </div>
  );
};

export default VesselMap;
