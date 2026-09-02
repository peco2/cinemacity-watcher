"""
Cinema City Ticket-Alert (Cloud-Version für GitHub Actions)
=============================================================
Läuft NICHT lokal, sondern automatisch alle paar Minuten in der GitHub-
Cloud (siehe .github/workflows/watch.yml). Da niemand vor dem Cloud-Rechner
sitzt, gibt es keinen Sound/Popup/Browser mehr - stattdessen wird bei einem
Treffer eine Push-Benachrichtigung übers Handy verschickt (ntfy.sh, wie
bisher).

WICHTIG zur Funktionsweise: Statt allgemein zu prüfen, ob "irgendein neuer
Tag" beim Kino freigeschaltet wurde (das würde fälschlich schon auslösen,
sobald IRGENDEIN Film an dem Tag läuft), wird HIER GEZIELT und AUSSCHLIESSLICH
für die paar Zieltage geprüft, ob eine passende Odyssea-IMAX-70mm-Vorstellung
existiert. Das ist präziser, weil normale Vorstellungen oft schon Wochen im
Voraus im Kalender auftauchen, bevor die gewünschte 70mm-Vorstellung selbst
freigeschaltet wird.

Der erkannte Zustand (welche konkreten Vorstellungen schon bekannt sind)
wird in state/seen.json gespeichert. Die GitHub Action committet diese Datei
nach jedem Lauf automatisch zurück ins Repo - so "merkt" sich das System den
Stand auch zwischen den einzelnen Cloud-Ausführungen.
"""

import json
import os
import sys
from datetime import datetime, timedelta

import requests

# ============================= CONFIG =============================

FILM_ID = "7268s2r"          # Odyssea
CINEMA_ID = 1052             # Cinema City Flora
CINEMA_NAME = "Flora"

REQUIRED_ATTR = "70-mm"      # nur IMAX-70mm-Vorstellungen zählen

TARGET_DATE_START = "2026-09-25"
TARGET_DATE_END = "2026-09-27"

STATE_FILE = "state/seen.json"

# ntfy-Thema wird NICHT hier im Code eingetragen, sondern als GitHub-Secret
# NTFY_TOPIC gesetzt und hier nur ausgelesen (siehe Anleitung).
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_SERVER = "https://ntfy.sh"

TENANT = "10101"
LANG = "cs_CZ"
API_BASE = f"https://www.cinemacity.cz/cz/data-api-service/v1/quickbook/{TENANT}"

# ====================================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def target_dates():
    start = datetime.strptime(TARGET_DATE_START, "%Y-%m-%d")
    end = datetime.strptime(TARGET_DATE_END, "%Y-%m-%d")
    days = []
    d = start
    while d <= end:
        days.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return days


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_state(event_keys):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(event_keys), f, ensure_ascii=False, indent=2)


def get_film_events(date):
    url = f"{API_BASE}/film-events/in-cinema/{CINEMA_ID}/at-date/{date}?attr=&lang={LANG}"
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    return response.json().get("body", {}).get("events", [])


def event_key(date, e):
    """Eindeutiger Schlüssel für eine konkrete Vorstellung (Datum+Uhrzeit+Saal)."""
    return f"{date}_{e.get('eventDateTime', '')}_{e.get('auditorium', '')}"


def get_matching_events():
    """Holt alle aktuell existierenden Odyssea-70mm-Vorstellungen in den Zieltagen."""
    found = {}
    for date in target_dates():
        events = get_film_events(date)
        for e in events:
            if e.get("filmId") == FILM_ID and REQUIRED_ATTR in e.get("attributeIds", []):
                found[event_key(date, e)] = (date, e)
    return found


def send_phone_push(title, message, url):
    if not NTFY_TOPIC:
        print("⚠️  NTFY_TOPIC ist nicht gesetzt - Push wird übersprungen.")
        return
    try:
        r = requests.post(
            f"{NTFY_SERVER}/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": title.encode("utf-8"),
                "Priority": "urgent",
                "Tags": "tickets,movie_camera",
                "Click": url,
            },
            timeout=15,
        )
        r.raise_for_status()
        print("Push-Benachrichtigung verschickt.")
    except requests.RequestException as e:
        print(f"⚠️  ntfy-Push fehlgeschlagen: {e}")


def alert(date, e):
    t = e.get("eventDateTime", "")
    time_part = t.split("T")[1][:5] if "T" in t else t
    hall = e.get("auditorium", "")
    sold_out = " (AUSVERKAUFT)" if e.get("soldOut") else ""
    showtime = f"{time_part} Uhr – Saal {hall}{sold_out}"

    print(f"🚨 ODYSSEA IMAX 70MM VERFÜGBAR: {date}, {showtime} 🚨")

    booking_url = f"https://www.cinemacity.cz/films/film/{FILM_ID}"
    send_phone_push(
        title="🎟️ Odyssea IMAX 70mm verfügbar!",
        message=f"Flora, {date}:\n{showtime}",
        url=booking_url,
    )


def main():
    print(f"Beobachte Zieltage: {', '.join(target_dates())}")
    known_keys = load_state()

    if not known_keys:
        # Erster Lauf überhaupt: NUR Ausgangszustand speichern, kein Alarm.
        current = get_matching_events()
        save_state(set(current.keys()))
        print(f"Erststart: {len(current)} bereits bekannte passende Vorstellung(en) gespeichert (kein Alarm).")
        return

    current = get_matching_events()
    new_keys = set(current.keys()) - known_keys

    for key in sorted(new_keys):
        date, e = current[key]
        alert(date, e)

    if not new_keys:
        print("Keine neuen passenden Vorstellungen.")

    save_state(set(current.keys()))
    print("Check abgeschlossen.")


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        print(f"⚠️  Fehler bei der API-Abfrage: {e}")
        sys.exit(1)  # Workflow-Schritt schlägt sichtbar fehl, State wird NICHT committet
