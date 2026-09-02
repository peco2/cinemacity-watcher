"""
Cinema City Ticket-Alert (Cloud-Version für GitHub Actions)
=============================================================
Läuft NICHT lokal, sondern automatisch alle paar Minuten in der GitHub-
Cloud (siehe .github/workflows/watch.yml). Da niemand vor dem Cloud-Rechner
sitzt, gibt es keinen Sound/Popup/Browser mehr - stattdessen wird bei einem
Treffer eine Push-Benachrichtigung übers Handy verschickt (ntfy.sh, wie
bisher).

Der erkannte Zustand (welche Tage schon bekannt sind) wird in
state/seen.json gespeichert. Die GitHub Action committet diese Datei nach
jedem Lauf automatisch zurück ins Repo - so "merkt" sich das System den
Stand auch zwischen den einzelnen Cloud-Ausführungen, obwohl jeder Lauf auf
einer frischen, leeren virtuellen Maschine startet.
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

HORIZON_DAYS = 30

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


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_state(dates):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(dates), f, ensure_ascii=False, indent=2)


def get_open_dates():
    until = (datetime.now() + timedelta(days=HORIZON_DAYS)).strftime("%Y-%m-%d")
    url = f"{API_BASE}/dates/in-cinema/{CINEMA_ID}/until/{until}?attr=&lang={LANG}"
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    return set(response.json().get("body", {}).get("dates", []))


def get_film_events(date):
    url = f"{API_BASE}/film-events/in-cinema/{CINEMA_ID}/at-date/{date}?attr=&lang={LANG}"
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    return response.json().get("body", {}).get("events", [])


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


def alert(date, events):
    showtimes = []
    for e in events:
        t = e.get("eventDateTime", "")
        time_part = t.split("T")[1][:5] if "T" in t else t
        hall = e.get("auditorium", "")
        sold_out = " (AUSVERKAUFT)" if e.get("soldOut") else ""
        showtimes.append(f"{time_part} Uhr – Saal {hall}{sold_out}")

    print(f"🚨 ODYSSEA IMAX 70MM VERFÜGBAR: {date} 🚨")
    for s in showtimes:
        print(f"    {s}")

    booking_url = f"https://www.cinemacity.cz/films/film/{FILM_ID}"
    send_phone_push(
        title="🎟️ Odyssea IMAX 70mm verfügbar!",
        message=f"Flora, {date}:\n" + "\n".join(showtimes),
        url=booking_url,
    )


def main():
    known_dates = load_state()

    if not known_dates:
        # Erster Lauf überhaupt: NUR Ausgangszustand speichern, kein Alarm.
        # (Sonst würden alle bereits länger verfügbaren Tage fälschlich
        # als "neu" gewertet.)
        current_dates = get_open_dates()
        save_state(current_dates)
        print(f"Erststart: {len(current_dates)} bereits bekannte Tage gespeichert (kein Alarm).")
        return

    current_dates = get_open_dates()
    new_dates = current_dates - known_dates

    relevant_new_dates = sorted(d for d in new_dates if TARGET_DATE_START <= d <= TARGET_DATE_END)
    ignored_new_dates = sorted(new_dates - set(relevant_new_dates))

    for date in relevant_new_dates:
        events = get_film_events(date)
        matching = [
            e for e in events
            if e.get("filmId") == FILM_ID and REQUIRED_ATTR in e.get("attributeIds", [])
        ]
        if matching:
            alert(date, matching)
        else:
            print(f"Neuer Tag {date} freigeschaltet (im Zielzeitraum), aber keine passende Vorstellung dabei.")

    if ignored_new_dates:
        print(f"{len(ignored_new_dates)} neue(r) Tag(e) außerhalb Zielzeitraum ignoriert: {', '.join(ignored_new_dates)}")

    save_state(current_dates)
    print("Check abgeschlossen.")


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        print(f"⚠️  Fehler bei der API-Abfrage: {e}")
        sys.exit(1)  # Workflow-Schritt schlägt sichtbar fehl, State wird NICHT committet
