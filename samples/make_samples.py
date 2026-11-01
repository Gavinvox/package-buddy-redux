"""Builds synthetic sample files in the old Package Buddy backup formats.
All numbers, names and events here are made up for testing."""
from pathlib import Path
import sqlite3
from xml.sax.saxutils import escape

HERE = Path(__file__).parent

DETAILS = ("<?xml version=\"1.0\"?><Tracking><Version>2.2</Version><Summary><DeliveryDate>Mar 3, 2015</DeliveryDate>"
           "</Summary><Activity><Date>Mar 2, 2015</Date><Time>8:15 AM</Time><City>Springfield</City><State>IL</State>"
           "<Country>US</Country><Event>Departed facility</Event></Activity><Activity><Date>Mar 1, 2015</Date>"
           "<Time>6:02 PM</Time><City>Columbus</City><State>OH</State><Country>US</Country><Event>Picked up</Event>"
           "</Activity></Tracking>")

PACKAGES = [
    # number, description, carrier, carrier index, status, status code, receive, archived, details
    ("1ZTEST0000000000A1", "Sample: new headphones", "ups", 1, "In Transit - Springfield, IL - 1425283200", 1, 1, 0, DETAILS),
    ("TBA000000000001", "Sample: Amazon order", "", -1, "", 0, 1, 0, ""),
    ("SAMPLEDHL01", "Sample: gift for Mom", "dhl", 3, "Delivered - Chicago, IL - 1425369600", 2, 0, 1, ""),
    ("RR000000000GB", "Sample: book from the UK", "royalmail", 4, "Delivered - Lansing, MI - 1420070400", 2, 1, 1, ""),
    ("SAMPLEFEDEX1", "Sample: returned shoes", "fedex", 0, "Returned - Memphis, TN - 1419984000", 3, 0, 1, ""),
    ("SAMPLEOLD01", "Sample: carrier that no longer exists", "streamlite", 104, "In Transit", 1, 1, 1, ""),
]


def xml() -> str:
    out = ["<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>", "<PackageBuddy>",
           "<Settings><HourFormat>0</HourFormat><DateFormat>0</DateFormat></Settings>", "<PackageList>"]
    for n, d, c, ci, s, sc, r, a, det in PACKAGES:
        out.append("<Package>" + "".join(f"<{t}>{escape(str(v))}</{t}>" for t, v in [
            ("TrackingNumber", n), ("Description", d), ("Carrier", c), ("CarrierCode", ci), ("Status", s),
            ("StatusCode", sc), ("SendReceive", r), ("Archived", a), ("TrackingDetails", det), ("LastUpdate", ci)])
            + "</Package>")
    out += ["</PackageList>", "</PackageBuddy>"]
    return "\n".join(out)


def sqlite_db(path: Path) -> None:
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE tracking_numbers (_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
                "code STRING NOT NULL, timestamp LONG NOT NULL, tracknum STRING NOT NULL, carrier STRING NOT NULL, "
                "carrier_code INTEGER NOT NULL, description STRING NOT NULL, status STRING NOT NULL, "
                "status_code INTEGER NOT NULL, receive BOOLEAN NOT NULL, archived BOOLEAN NOT NULL, "
                "details STRING NOT NULL, dttm LONG NOT NULL, carrier2 STRING NOT NULL, "
                "carrier2_code INTEGER NOT NULL, details2 STRING NOT NULL)")
    for n, d, c, ci, s, sc, r, a, det in PACKAGES:
        con.execute("INSERT INTO tracking_numbers (user_id, code, timestamp, tracknum, carrier, carrier_code, "
                    "description, status, status_code, receive, archived, details, dttm, carrier2, carrier2_code, "
                    "details2) VALUES (0, ?, -1, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1425369600000, '', -1, '')",
                    (f"{ci}{n}", n, c, ci, d, s, sc, r, a, det))
    con.commit()
    con.close()


def android_backup(db_bytes: bytes, compressed: bool = True, encrypted: bool = False) -> bytes:
    """A synthetic `adb backup` file in the same layout Android writes: header lines + (zlib) tar."""
    import io
    import tarfile
    import time
    import zlib

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        entries = [("apps/com.psyrus.packagebuddy/_manifest", b"1\n285\n3.1.7\n"),
                   ("apps/com.psyrus.packagebuddy/sp/com.psyrus.packagebuddy_preferences.xml",
                    b"<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map />\n"),
                   ("apps/com.psyrus.packagebuddy/db/packagebuddy_db", db_bytes)]
        for name, data in entries:
            ti = tarfile.TarInfo(name)
            ti.size, ti.mtime, ti.mode = len(data), int(time.time()), 0o600
            tf.addfile(ti, io.BytesIO(data))
    payload = buf.getvalue()
    if encrypted:
        return b"ANDROID BACKUP\n5\n1\nAES-256\n" + b"0" * 64 + b"\n"  # header is all we need to test the refusal
    if compressed:
        payload = zlib.compress(payload)
    return b"ANDROID BACKUP\n5\n" + (b"1" if compressed else b"0") + b"\nnone\n" + payload


if __name__ == "__main__":
    (HERE / "sample_backup.xml").write_text(xml())
    sqlite_db(HERE / "sample_packagebuddy_db.sqlite")
    (HERE / "sample_packagebuddy.ab").write_bytes(
        android_backup((HERE / "sample_packagebuddy_db.sqlite").read_bytes()))
    print("wrote sample_backup.xml, sample_packagebuddy_db.sqlite and sample_packagebuddy.ab")
