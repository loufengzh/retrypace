# Einstieg in retrypace

Standardwerte gelten nur, wenn `--config` weggelassen wird. Ein ausdrücklich leerer Pfad (`--config ""` oder `--config=`), auch durch eine leere Shell-Variable, gilt als nicht lesbare Konfiguration: Exit-Code 1, ohne Bericht. Strategieüberschreibungen und Schwellwertprüfungen umgehen diese Validierung nicht.

[English](../README.md) · [中文](zh-CN.md) · [Русский](ru.md)

retrypace ist ein Offline-Werkzeug zur Prüfung von Wiederholungsplänen in Architekturgesprächen und CI. Es zeigt, wie viele vollständige Versuche in ein Zeitbudget passen, wie viele Anfragen gleichzeitig laufen und wie groß Spitzen innerhalb eines gleitenden Zeitfensters werden.

Voraussetzung: Python 3.10 oder neuer. Es gibt keine Laufzeitabhängigkeiten, Netzwerkanfragen, Telemetrie oder echten Wartezeiten.

## Start

```sh
git clone https://github.com/loufengzh/retrypace.git
cd retrypace
python -m retrypace --config examples/burst.json --compare
python -m retrypace --config examples/staggered.json --format csv > attempts.csv
python -m unittest discover -s tests -v
```

Im Quellverzeichnis ist keine Installation nötig. Optional installiert `python -m pip install .` den Befehl `retrypace`; dafür müssen eventuell Build-Werkzeuge heruntergeladen werden. Das Projekt ist derzeit nicht auf PyPI veröffentlicht. Ein gleichnamiges Paket dort ist nicht automatisch dieses Projekt.

## Konfiguration

Erstelle eine JSON-Datei. Fehlende Felder erhalten die folgenden Standardwerte. Alle Zeitangaben sind ganzzahlige Millisekunden.

```json
{
  "clients": 100,
  "max_attempts": 5,
  "base_ms": 100,
  "cap_ms": 2000,
  "attempt_ms": 50,
  "deadline_ms": 3000,
  "stagger_ms": 0,
  "window_ms": 100,
  "concurrency_limit": 20,
  "seed": 1,
  "strategy": "full-jitter"
}
```

- `clients`: Anzahl der Clients.
- `max_attempts`: Gesamtzahl erlaubter Versuche einschließlich der ersten Anfrage.
- `base_ms`, `cap_ms`: Basiswartezeit und Obergrenze; die Obergrenze muss mindestens der Basis entsprechen.
- `attempt_ms`: feste, positive Dauer eines Versuchs.
- `deadline_ms`: Zeitbudget relativ zum Start jedes Clients. Nur ein vollständig passender Versuch wird gestartet. Ein Abschluss genau an der Frist ist erlaubt. Bei null werden keine Anfragen ausgeführt.
- `stagger_ms`: Abstand zwischen den Startzeiten benachbarter Clients; null bedeutet gleichzeitigen Start.
- `window_ms`: Breite des Fensters zum Zählen der Anfragestarts.
- `concurrency_limit`: Referenzwert für Überschreitungen, kein durchgesetztes Parallelitätslimit. Er erzeugt weder Warteschlangen noch verworfene Anfragen.
- `seed`: reproduzierbarer Startwert von 0 bis 2³²−1.
- `strategy`: `fixed`, `exponential`, `full-jitter`, `equal-jitter` oder `decorrelated`.

Außer Frist, Startabstand und Seed müssen alle Zahlen positive Ganzzahlen sein. Boolesche Werte sind kein Ersatz für Ganzzahlen. Andere Zahlen sind auf 1.000.000.000 begrenzt. Unbekannte Felder verursachen einen Fehler. `clients × max_attempts` darf 1.000.000 nicht überschreiten; große Berichte können trotzdem viel Speicher benötigen.

`--config` akzeptiert ein UTF-8-JSON-Objekt ohne BOM mit höchstens 64 KiB (65.536 Bytes), einschließlich Leerraum. Doppelte JSON-Schlüssel werden abgelehnt, auch bei gleichen Werten oder unterschiedlichen JSON-Escape-Schreibweisen desselben Schlüssels; der letzte Wert überschreibt den vorherigen nicht. NaN und Infinity werden ebenfalls abgelehnt. Ungültige, zu große oder übermäßig verschachtelte Eingaben beenden den Befehl mit Exitcode 1 ohne Bericht, bevor Strategieüberschreibungen oder CI-Grenzprüfungen angewendet werden. Die Bytegrenze gilt für das Einlesen von CLI-Dateien; `Config.from_dict` prüft ein bereits eingelesenes Mapping und kann keine Duplikate erkennen, die ein anderer JSON-Parser verworfen hat.

## Modell und Strategien

Jeder zugelassene Versuch gilt als fehlgeschlagen. Die Wartezeit beginnt nach seinem Ende. Jeder Client wiederholt nacheinander und beeinflusst die anderen nicht. Die exponentielle Obergrenze der ersten Wiederholung entspricht der Basis, verdoppelt sich anschließend und wird bei `cap_ms` begrenzt.

- `fixed`: immer die Basiswartezeit.
- `exponential`: die aktuelle exponentielle Obergrenze.
- `full-jitter`: eine Ganzzahl zwischen null und dieser Obergrenze.
- `equal-jitter`: eine Ganzzahl zwischen der aufgerundeten Hälfte und der vollen Obergrenze.
- `decorrelated`: eine Ganzzahl zwischen Basis und dreifacher vorheriger Wartezeit; erst danach wird die Obergrenze angewendet. Die anfängliche vorherige Wartezeit entspricht der Basis.

Zufallsintervalle schließen beide Endpunkte ein. Gleiche Konfiguration und gleicher Seed ergeben dasselbe Ergebnis. Der Generator ist nicht kryptografisch sicher und keine unmittelbare Empfehlung für produktive Retry-Implementierungen.

## Bericht lesen

JSON enthält `schema_version`, `model`, `config`, `summary`, `buckets` und optional `events`.

- `attempts` / `retries`: alle zugelassenen Anfragen / nur Wiederholungen.
- `clients_stopped_by_deadline`: Clients, deren nächster vollständiger Versuch nicht mehr in das Budget passt.
- `clients_stopped_by_attempt_limit`: Clients, die ihre erlaubte Anzahl erreicht haben.
- `peak_concurrency`: höchster gleichzeitiger Bestand. Anfragen belegen halboffene Intervalle `[Start, Ende)`: eine endende und eine zum gleichen Zeitpunkt beginnende Anfrage überlappen nicht.
- `peak_window_starts`: größte Startanzahl in einem beliebigen halboffenen Fenster; erkennt auch Spitzen über feste Intervallgrenzen hinweg.
- `peak_aligned_bucket_starts`: Spitzenwert in festen, am globalen Nullpunkt ausgerichteten Intervallen. Leere Intervalle werden weggelassen.
- `retry_peak_concurrency` / `retry_peak_window_starts`: entsprechende Spitzen ohne die ersten Anfragen.
- `time_over_concurrency_limit_ms`: Gesamtdauer mit strikt überschrittenem Referenzwert.
- `excess_concurrency_ms`: zeitliches Integral der Überschreitung, in Anfrage-Millisekunden.
- `max_client_elapsed_ms`: längste Dauer vom Clientstart bis zum Ende seines letzten zugelassenen Versuchs.
- `min_client_budget_remaining_ms`: kleinster Budgetrest nach dem letzten zugelassenen Versuch.
- `schedule_end_ms`: letzter globaler Abschluss einschließlich versetzter Starts.

Im Beispiel `examples/burst.json` senkt Full Jitter die maximale Zahl paralleler Wiederholungen von 100 auf 51, erhöht aber die Wiederholungsstarts im stärksten 100-ms-Fenster von 100 auf 109. Kürzere Wartezeiten lassen mehr Wiederholungen zu. Der anfängliche gleichzeitige Start von 100 Anfragen bleibt bei allen Strategien erhalten. Ein einzelner Seed ist kein statistischer Nachweis für eine allgemein bessere Strategie.

## CLI und CI

```sh
python -m retrypace --config examples/burst.json --summary-only > report.json
python -m retrypace --config examples/burst.json --strategy exponential
python -m retrypace --config examples/staggered.json \
  --max-peak-concurrency 50 --max-window-starts 200 > report.json
```

Grenzprüfungen berücksichtigen auch die ersten Anfragen. Gleichheit besteht die Prüfung; nur ein größerer Wert verletzt sie. Bei `--compare` genügt eine verletzende Strategie für einen Fehlerstatus. Der Bericht bleibt auch dann auf stdout verfügbar; Hinweise erscheinen auf stderr. CSV enthält `client,attempt,start_ms,end_ms` und lässt sich nicht mit `--compare` oder `--summary-only` kombinieren.

Exitcodes: 0 bedeutet Erfolg, 1 bedeutet unlesbare oder ungültige Konfiguration, 2 bedeutet Grenzverletzung oder falsche CLI-Verwendung. `--help` und `--version` sind verfügbar. `--summary-only` verkleinert die Ausgabe, nicht den Speicherbedarf der Berechnung.

## Python-Bibliothek

```python
from retrypace import Config, compare, simulate

config = Config(clients=30, max_attempts=4, deadline_ms=1000, seed=42)
report = simulate(config)
print(report["summary"]["retry_peak_concurrency"])
policies = compare(config)
```

`Config` ist unveränderlich und prüft die Eingaben. `Config.from_dict(mapping)` übernimmt JSON-artige Konfigurationen. `simulate(config, include_events=False)` lässt einzelne Ereignisse im Bericht weg. `compare` ordnet jeder Strategie ihren Bericht zu.

## Grenzen

Das Werkzeug prüft ein vorgegebenes Szenario. Es ist keine Wiederherstellungsprognose, Warteschlangentheorie oder Lastprüfung. Erfolg, Diensterholung, variable Latenzen, echte Ratenbegrenzung, Retry-After, verschachtelte Wiederholungen, Abbruch und Idempotenz werden nicht modelliert. Der Parallelitätsschwellenwert beeinflusst die Planung nicht. Produktive Einstellungen müssen mit repräsentativen Lasttests und Telemetrie überprüft werden.

[Retry Lab](https://github.com/kyan9400/retry-lab) simuliert Wiederherstellung interaktiv im Browser; retrypace konzentriert sich auf Offline-Prüfungen von Fristen und Anfragedruck. Die Strategien sind im [AWS-Artikel](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/) beschrieben; fremder Projektcode wurde nicht kopiert. [Genaue Modellbeschreibung auf Englisch](model.md). Lizenz: [MIT](../LICENSE).
