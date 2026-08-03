"""Maersk EDI status ingest: X12 315 and EDIFACT IFTSTA.

Maersk pushes container status messages to the customer (AS2/SFTP/VAN), so tracking is a
FEED, not a poll: messages land here, are parsed into one canonical event shape, and the
Track page reads them straight out of Mongo. No upstream calls, no quota, no keys.

Canonical event, shared with the REST path in tracking.py:
    {code, when, estimated, location, country, mode, vessel_name, vessel_imo, voyage}

Event codes are Maersk's own (VD departed, VA arrived, AR loaded, UV unloaded, AG in-gate,
AE gate-out for delivery, D delivered, ...). Estimated vs actual comes from the DTM
qualifier: X12 139 = estimated, 140 = actual; IFTSTA 132 = estimated, 133/334 = actual.
"""
import logging
import re
from datetime import datetime, timezone

log = logging.getLogger("edi")

X12_ESTIMATED = {"139"}
X12_ACTUAL = {"140"}
EDIFACT_ESTIMATED = {"132"}
EDIFACT_ACTUAL = {"133", "334", "178", "186"}

# IFTSTA status codes -> the same vocabulary the X12 guide uses, so the UI has one map.
IFTSTA_TO_X12 = {
    "1": "AG", "5": "AR", "6": "VD", "7": "VA", "8": "UV", "9": "AE",
    "38": "AR", "39": "UV", "44": "AV", "58": "RD", "79": "D",
}


def _now():
    return datetime.now(timezone.utc)


def _iso(date, time=None):
    """X12 CCYYMMDD (+ HHMM) or EDIFACT CCYYMMDDHHMM -> ISO 8601 UTC-naive local time.

    Carriers quote LOCAL time at the location and rarely send an offset, so the value is
    kept as sent and simply labelled; inventing a UTC offset would move events by hours.
    """
    d = re.sub(r"\D", "", date or "")
    t = re.sub(r"\D", "", time or "")
    if len(d) == 12:                      # EDIFACT packs the time into the date
        d, t = d[:8], d[8:]
    if len(d) != 8:
        return None
    hh, mm = (t[:2] or "00"), (t[2:4] or "00")
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}T{hh}:{mm}:00"


def _blank():
    return {"code": "", "when": None, "estimated": False, "location": "", "country": "",
            "unloc": "", "mode": "", "vessel_name": "", "vessel_imo": "", "voyage": ""}


def parse_x12_315(text):
    """One 315 transaction set per shipment status; a file may hold many."""
    body = text.replace("\r", "\n")
    # The element separator is fixed by ISA, the segment terminator is the char after ISA16.
    seg_term = "~"
    isa = body.find("ISA")
    elem = body[isa + 3] if isa >= 0 and len(body) > isa + 3 else "*"
    if isa >= 0:
        head = body[isa:isa + 106]
        if len(head) >= 106:
            seg_term = head[105]

    segments = [s.strip() for s in re.split(f"[{re.escape(seg_term)}\n]", body) if s.strip()]
    out, cur = [], None
    for seg in segments:
        f = seg.split(elem)
        tag = f[0].strip().upper()

        if tag == "B4":
            if cur and cur["event"]["code"]:
                out.append(cur)
            # Senders differ on whether the status code sits in B402 or B403 and on how
            # many optional elements they leave empty, so the elements are recognised by
            # shape rather than counted: a 1-2 letter status code, an 8-digit date with an
            # optional 4-digit time after it, a 4-letter equipment initial followed by the
            # container number.
            els = [e.strip() for e in f[1:]]
            ev = _blank()
            ev["code"] = next((e.upper() for e in els if re.fullmatch(r"[A-Za-z]{1,2}", e)), "")
            di = next((n for n, e in enumerate(els) if re.fullmatch(r"\d{8}", e)), None)
            date = els[di] if di is not None else ""
            time = ""
            if di is not None and di + 1 < len(els) and re.fullmatch(r"\d{3,4}", els[di + 1]):
                time = els[di + 1]
            ev["when"] = _iso(date, time)
            ii = next((n for n, e in enumerate(els) if re.fullmatch(r"[A-Z]{4}", e)), None)
            container = ""
            if ii is not None:
                nxt = els[ii + 1] if ii + 1 < len(els) else ""
                if re.fullmatch(r"\d{6,7}", nxt):
                    container = (els[ii] + nxt).upper()
            # Whatever sits between the timestamp and the container is the place name.
            if di is not None:
                after = di + (2 if time else 1)
                place = next((e for e in els[after:ii if ii is not None else len(els)]
                              if re.search(r"[A-Za-z]{3,}", e)), "")
                ev["location"] = place.title() if place.isupper() else place
            cur = {"container": container, "bol": "", "event": ev}

        elif cur and tag == "Q2":
            cur["event"]["vessel_name"] = (f[13] if len(f) > 13 else "").strip()
            cur["event"]["voyage"] = (f[9] if len(f) > 9 else "").strip()
            cur["event"]["mode"] = "VESSEL"

        elif cur and tag == "R4":
            # The port segment names the place properly ("Busan"), where B4 only carries a
            # code or an upper-case city, so it wins whenever it is present.
            name = (f[4] if len(f) > 4 else "").strip()
            if name:
                cur["event"]["location"] = name
            if (f[2] if len(f) > 2 else "").strip().upper() == "UN":
                cur["event"]["unloc"] = (f[3] if len(f) > 3 else "").strip().upper()
            if len(f) > 5 and f[5].strip():
                cur["event"]["country"] = f[5].strip()

        elif cur and tag == "DTM":
            q = (f[1] if len(f) > 1 else "").strip()
            when = _iso(f[2] if len(f) > 2 else "", f[3] if len(f) > 3 else "")
            if when:
                cur["event"]["when"] = when
            if q in X12_ESTIMATED:
                cur["event"]["estimated"] = True
            elif q in X12_ACTUAL:
                cur["event"]["estimated"] = False

        elif cur and tag == "N9" and (f[1] if len(f) > 1 else "").upper() == "BM":
            cur["bol"] = (f[2] if len(f) > 2 else "").strip().upper()

    if cur and cur["event"]["code"]:
        out.append(cur)
    return out


def parse_iftsta(text):
    """EDIFACT IFTSTA D99B: CNI groups, each STS with its DTM/LOC/TDT/EQD context."""
    body = text.replace("\r", "").replace("\n", "")
    segments = [s.strip() for s in body.split("'") if s.strip()]
    out, cur, ctx = [], None, {"container": "", "bol": ""}

    for seg in segments:
        f = seg.split("+")
        tag = f[0].strip().upper()

        if tag == "EQD":
            ctx["container"] = (f[2].split(":")[0] if len(f) > 2 else "").strip().upper()
        elif tag == "RFF":
            comp = (f[1] if len(f) > 1 else "").split(":")
            if comp and comp[0].upper() in ("BM", "BN") and len(comp) > 1:
                ctx["bol"] = comp[1].strip().upper()
        elif tag == "STS":
            if cur and cur["event"]["code"]:
                out.append(cur)
            raw = (f[2].split(":")[0] if len(f) > 2 else "").strip()
            ev = _blank()
            ev["code"] = IFTSTA_TO_X12.get(raw, raw.upper())
            cur = {"container": ctx["container"], "bol": ctx["bol"], "event": ev}
        elif cur and tag == "DTM":
            comp = (f[1] if len(f) > 1 else "").split(":")
            q = comp[0] if comp else ""
            when = _iso(comp[1] if len(comp) > 1 else "")
            if when:
                cur["event"]["when"] = when
            if q in EDIFACT_ESTIMATED:
                cur["event"]["estimated"] = True
            elif q in EDIFACT_ACTUAL:
                cur["event"]["estimated"] = False
        elif cur and tag == "LOC":
            comp = (f[2] if len(f) > 2 else "").split(":")
            cur["event"]["unloc"] = (comp[0] if comp else "").strip().upper()
            cur["event"]["location"] = (comp[3] if len(comp) > 3 else comp[0]).strip()
        elif cur and tag == "TDT":
            cur["event"]["mode"] = "VESSEL"
            cur["event"]["voyage"] = (f[2] if len(f) > 2 else "").strip()
            # The means-of-transport group sits at a different position depending on the
            # sender's D99B profile, so the name and the IMO are recognised by shape.
            comps = [c.strip() for part in f[3:] for c in part.split(":") if c.strip()]
            # The longest alphabetic component is the vessel name; shorter ones are carrier
            # and agency codes like "MAEU".
            names = [c for c in comps if re.fullmatch(r"[A-Za-z][A-Za-z .'\-]{4,}", c)]
            cur["event"]["vessel_name"] = max(names, key=len) if names else ""
            cur["event"]["vessel_imo"] = next(
                (c for c in comps if re.fullmatch(r"\d{7}", c)), "")

    if cur and cur["event"]["code"]:
        out.append(cur)
    return out


def parse(text):
    """Sniff the format and parse. Returns (events, format)."""
    t = (text or "").lstrip()
    if t.upper().startswith("ISA") or "\nB4" in t or "~B4" in t:
        return parse_x12_315(t), "X12_315"
    if t.upper().startswith("UNB") or t.upper().startswith("UNA") or "STS+" in t:
        return parse_iftsta(t), "IFTSTA"
    raise ValueError("unrecognised EDI message: expected an X12 315 or an EDIFACT IFTSTA")


async def ingest(db, text):
    """Store parsed events idempotently. The same message may be delivered twice."""
    rows, fmt = parse(text)
    stored, skipped = 0, 0
    for r in rows:
        ref = r["container"] or r["bol"]
        if not ref or not r["event"]["when"]:
            skipped += 1
            continue
        ev = r["event"]
        # One row per (reference, code, timestamp): a redelivered message updates in place
        # instead of duplicating the timeline.
        await db.shipment_events.update_one(
            {"ref": ref, "code": ev["code"], "when": ev["when"]},
            {"$set": {**ev, "ref": ref, "container": r["container"], "bol": r["bol"],
                      "source": fmt, "received_at": _now()}},
            upsert=True)
        stored += 1
    log.info("edi %s: %s events stored, %s skipped", fmt, stored, skipped)
    return {"format": fmt, "stored": stored, "skipped": skipped}


async def events_for(db, ref, by="container"):
    field = "bol" if by == "bol" else "container"
    rows = await db.shipment_events.find(
        {"$or": [{"ref": ref}, {field: ref}]}, {"_id": 0, "received_at": 0}
    ).to_list(500)
    return sorted(rows, key=lambda r: r["when"])
