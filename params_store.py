#!/usr/bin/env python3
"""
params_store.py — editierbare Suchkriterien (Scanner A + TJL-Regeln).

Defaults stehen hier im SCHEMA. Geänderte Werte liegen in scanner_params.json
(nur Abweichungen werden gespeichert). Jeder Scanner-Lauf liest die Datei neu,
d. h. Änderungen im Cockpit gelten ab dem NÄCHSTEN Lauf.

Ungültige/kaputte Datei -> Defaults (ein Tippfehler legt nie den Scanner lahm).
"""
import json, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "scanner_params.json")

# key: (gruppe, label, typ, default, min, max, choices, hilfe)
SCHEMA = {
    # --- Scanner A ---
    "MIN_GAP":        ("scanner_a", "Min. Gap", "float", 5.0, 0.5, 100, None, "% Gap zum Vortagesschluss"),
    "MIN_PRICE":      ("scanner_a", "Min. Kurs", "float", 3.0, 0.1, 1000, None, "$ — filtert Pennystocks"),
    "MIN_VOLUME":     ("scanner_a", "Min. Premarket-Volumen", "int", 50000, 0, 50_000_000, None, "Stück"),
    "TOP_N":          ("scanner_a", "Anzahl Gapper", "int", 10, 1, 30, None, "Top-N für Scanner B"),
    # --- Scanner B: Einstieg ---
    "FILTER_MODE":    ("entry", "Filter-Modus", "choice", "observe", None, None, ["observe", "enforce"],
                       "observe = nur anzeigen, enforce = blockiert Signale"),
    "MIN_RVOL":       ("entry", "Min. relatives Volumen", "float", 2.0, 0.5, 20, None, "x des Ø-Volumens bis jetzt"),
    "MAX_EXT_ATR":    ("entry", "Max. Abstand über VWAP", "float", 1.0, 0.1, 5, None, "in ATR"),
    # --- Ausstieg ---
    "INIT_STOP_ATR":  ("exit", "Anfangs-Stop", "float", 0.75, 0.1, 5, None, "ATR unter Einstieg"),
    "PARTIAL_ATR":    ("exit", "Teilgewinn-Ziel", "float", 1.0, 0.1, 10, None, "ATR über Einstieg"),
    "PARTIAL_PCT":    ("exit", "Teilgewinn-Größe", "int", 50, 0, 100, None, "% der Position"),
    "TRAIL_ATR":      ("exit", "Trailing-Abstand", "float", 0.75, 0.1, 5, None, "ATR unter Hoch (nach Teilgewinn)"),
    "VWAP_EXIT_MODE": ("exit", "VWAP-Exit", "choice", "observe", None, None, ["observe", "enforce"],
                       "5-Min-Schluss unter VWAP: nur melden / aussteigen"),
    "EOD_ET":         ("exit", "Zwangsschluss (ET)", "time", "15:45", "15:00", "15:59", None, "New-York-Zeit"),
    "ATR_PERIOD":     ("exit", "ATR-Periode", "int", 14, 2, 50, None, "Tage"),
}


def defaults(group=None):
    return {k: s[3] for k, s in SCHEMA.items() if group is None or s[0] == group}


def validate(key, value):
    """Gibt den bereinigten Wert zurück oder wirft ValueError."""
    if key not in SCHEMA:
        raise ValueError(f"unbekannter Parameter {key}")
    _, label, typ, _, lo, hi, choices, _ = SCHEMA[key]
    if typ in ("float", "int"):
        v = float(value)
        if typ == "int":
            if v != int(v):
                raise ValueError(f"{label}: ganze Zahl erwartet")
            v = int(v)
        if not (lo <= v <= hi):
            raise ValueError(f"{label}: erlaubt {lo} – {hi}")
        return v
    if typ == "choice":
        if value not in choices:
            raise ValueError(f"{label}: erlaubt {', '.join(choices)}")
        return value
    if typ == "time":
        h, m = map(int, str(value).split(":"))
        v = f"{h:02d}:{m:02d}"
        if not (lo <= v <= hi):
            raise ValueError(f"{label}: erlaubt {lo} – {hi}")
        return v
    raise ValueError(f"{label}: unbekannter Typ")


def _overrides():
    try:
        with open(PATH) as f:
            raw = json.load(f)
    except Exception:
        return {}
    out = {}
    for k, v in (raw or {}).items():
        try:
            out[k] = validate(k, v)
        except Exception:
            pass  # ungültiger Eintrag -> Default
    return out


def load(group=None):
    vals = defaults()
    vals.update(_overrides())
    return {k: v for k, v in vals.items() if group is None or SCHEMA[k][0] == group}


def save(updates):
    """Validiert alle Werte (alles-oder-nichts) und schreibt nur Abweichungen vom Default."""
    clean = {k: validate(k, v) for k, v in updates.items()}
    merged = load()
    merged.update(clean)
    diff = {k: v for k, v in merged.items() if v != SCHEMA[k][3]}
    fd, tmp = tempfile.mkstemp(dir=HERE, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(diff, f, indent=2)
    os.replace(tmp, PATH)
    return merged


def schema_list():
    vals = load()
    return [{"key": k, "group": s[0], "label": s[1], "type": s[2], "default": s[3],
             "min": s[4], "max": s[5], "choices": s[6], "help": s[7], "value": vals[k]}
            for k, s in SCHEMA.items()]
