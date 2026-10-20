<p align="center"><img src="docs/assets/shapediff-wordmark.svg" width="360" alt="ShapeDiff"></p>

<p align="center"><a href="README.md"><img src="docs/assets/readme-language-en.svg" height="40" alt="Read this README in English"></a></p>

<p align="center">
  <a href="https://github.com/IamAngusU/shapediff/releases/tag/v0.1.0a4"><img src="docs/assets/readme/repo-release.svg" height="40" alt="Preview 0.1.0a4"></a>
  <a href="pyproject.toml"><img src="docs/assets/readme/repo-runtime.svg" height="40" alt="Python 3.10 or newer"></a>
  <a href="LICENSE"><img src="docs/assets/readme/repo-license.svg" height="40" alt="MIT license"></a>
</p>


# JSON-Antworten vergleichen, ohne ein Schema zu pflegen

ShapeDiff erkennt strukturelle Änderungen zwischen beobachteten API-Antworten. Geänderte Werte wie IDs, Namen oder Zeitstempel lösen keinen Befund aus, solange ihre JSON-Typen gleich bleiben. Fehlende Felder, Typwechsel und neue `null`-Werte können dagegen bestehende Clients beeinträchtigen.

**Lokal, ohne Account, ohne Telemetrie, ohne Laufzeit-Abhängigkeiten.** Benötigt Python ab 3.10.

![ShapeDiff compares the included production and staging responses](docs/assets/terminal.png)

## Direkt starten

Installiere ShapeDiff direkt von [PyPI](https://pypi.org/project/shapediff/0.1.0a4/). Mit [pipx](https://pipx.pypa.io/stable/installation/) landet der Befehl in einer eigenen Umgebung:

```sh
pipx install shapediff==0.1.0a4
shapediff production.json staging.json
```

Für eine Projektumgebung funktioniert `python -m pip install shapediff==0.1.0a4`. Es werden keine Laufzeitpakete nachgeladen. Dies ist eine Alpha-Version; die feste Versionsangabe macht auch CI-Installationen reproduzierbar. Das [GitHub-Release](https://github.com/IamAngusU/shapediff/releases/tag/v0.1.0a4) enthält dasselbe Wheel und Quellarchiv, SHA-256-Prüfsummen und die einzelne Datei `shapediff.py`. [Veröffentlichung und Prüfung](docs/registry.md).

Alternativ kannst du die einzelne Quelldatei ohne Paketinstallation starten:

```sh
python3 shapediff.py examples/production.json examples/staging.json
```

```text
ERROR  user.email   missing
ERROR  user.id      number -> string
INFO   user.avatar  added
```

Für einen Download als Einzeiler:

```sh
curl -fsSL https://github.com/IamAngusU/shapediff/releases/download/v0.1.0a4/shapediff.py -o shapediff.py && python3 shapediff.py production.json staging.json
```

Unter Windows PowerShell:

```powershell
Invoke-WebRequest -ErrorAction Stop 'https://github.com/IamAngusU/shapediff/releases/download/v0.1.0a4/shapediff.py' -OutFile shapediff.py; py -3 shapediff.py production.json staging.json
```

Der Download speichert lesbaren Python-Code, ohne fremden Code direkt in die Shell zu leiten. Für CI bleibt die Version durch den Release-Link festgelegt.

## Dauerhafte Baseline ohne gespeicherte Antwortwerte

Mit `profile` erzeugt ShapeDiff eine versionierte Datei, die nur beobachtete Typen, Feldhäufigkeiten und verschachtelte Strukturen enthält. Die ursprünglichen Werte bleiben nicht erhalten.

```sh
# Eine Baseline erstellen
python3 shapediff.py profile production.json -o production.sdshape

# Eine spätere Antwort direkt gegen die Baseline testen
python3 shapediff.py production.sdshape staging.json --breaking-only

# Neue Beobachtung zu der vorhandenen Baseline hinzufügen
curl -fsS https://api.example.test/users/1 | python3 shapediff.py profile - --update production.sdshape

# Bei Bedarf zwei gespeicherte Profile vergleichen
python3 shapediff.py old.sdshape new.sdshape
```

Auch JSONL und ganze Sample-Verzeichnisse können direkt in ein Profil einfließen. `--update` führt die Beobachtungszähler zusammen und aktualisiert die Profildatei atomar. Bei einem Fehler bleibt die vorherige Datei erhalten. Zum bewussten kompletten Ersetzen verwendest du `--force`.

Vergleichsregeln wie `--map`, `--ignore`, `--formats` und `--strict-integers` werden aus dem Profil automatisch übernommen. Unterschiedliche Profilregeln verursachen einen Fehler statt einen irreführenden Vergleich.

**Datenschutzgrenze:** Objekt-Keys werden als Feldnamen gespeichert. Wenn ein Key selbst eine E-Mail-Adresse, UUID oder Kennung ist, kann das sensible Informationen enthalten. Offensichtliche Kennungen dieser Art werden beim Erstellen standardmäßig blockiert. Nutze `--map` für dynamische Keys oder bewusst `--allow-identifier-keys`. Die Erkennung ist heuristisch und ersetzt keine Kontrolle vor der Weitergabe.

## Mehrere Antworten statt einer Stichprobe

```sh
python3 shapediff.py examples/baseline/ examples/current/ --evidence
```

JSON, JSONL, NDJSON, Verzeichnisse mit Samples sowie `-` für stdin werden unterstützt. Jede Seite muss denselben Endpoint beziehungsweise Antwortvertrag repräsentieren. JSONL wird zeilenweise verarbeitet.

ShapeDiff zählt, wie häufig ein Feld in beobachteten Objekten vorkommt. **Diese Häufigkeit beweist keine Pflichtfelder.** Wenn ein Feld in einer von drei alten Antworten vorhanden war und in keiner neuen vorkommt, erhält es ein `WARN`. Ein durchgängig beobachtetes Feld, das komplett verschwindet, erhält `ERROR`, bleibt aber eine Beobachtung statt eines Beweises für `required`.

Neue Ausgabetypen können bestehende Empfänger brechen. Deshalb wird `string` zu `string|null` als `ERROR` behandelt. Eine ausschließlich `null`-haltige Baseline liefert dagegen keine verlässliche Aussage zum zugrundeliegenden Datentyp und führt beim ersten beobachteten Nicht-Null-Wert zu `WARN`.

## Für echte Arbeitsabläufe

```sh
# Nur potenziell inkompatible Änderungen anzeigen
python3 shapediff.py production.json staging.json --breaking-only

# Strukturiertes Ergebnis in eine Datei schreiben
python3 shapediff.py production.json staging.json --format json --output report.json

# Dynamische Objekt-Keys ausdrücklich als Map behandeln
python3 shapediff.py production.json staging.json --map /usersById

# Feld und Unterbaum vollständig ausnehmen
python3 shapediff.py production.json staging.json --ignore /debug

# Warnungen ebenfalls CI-blockierend behandeln
python3 shapediff.py baseline/ current/ --fail-on warning
```

Exitcodes: `0` kein Befund an der gewählten Fehlerschwelle, `1` blockierender Befund, `2` ungültige CLI-Parameter, `3` ungültige Daten beziehungsweise Ein-/Ausgabefehler, `130` Abbruch.

Dynamische Keys werden absichtlich **nicht automatisch geraten**. Das könnte echte entfernte Felder verbergen. Formaterkennung ist mit `--formats` optional; leere Arrays auf nur einer Seite erzeugen einen Hinweis auf fehlende Evidenz.

## Mehrere Endpunkte getrennt prüfen

Mit `suite` vergleichst du benannte Antwortverträge, ohne JSON-Antworten verschiedener Endpunkte zu vermischen. Pro Fall prüft ShapeDiff den HTTP-Status, ausdrücklich ausgewählte Header und die Struktur des Bodys.

```sh
python3 shapediff.py suite examples/baseline.sdsuite examples/current.sdsuite
python3 shapediff.py suite vorher.sdsuite nachher.sdsuite --format json --output report.json
```

Eine `.sdsuite`-Datei enthält ein `responses`-Array mit eindeutigen `id`-Werten, `status` und `body`. `body` ist ein relativer Pfad zu JSON, JSONL, einem Sample-Verzeichnis oder einem `.sdshape`-Profil; für Antworten ohne Body steht dort `null`. Eine vollständige Vorlage findest du in [`examples/baseline.sdsuite`](examples/baseline.sdsuite). Die Pfade bleiben innerhalb des Verzeichnisses der Suite-Datei.

Nur in `headers` aufgeführte Header werden verglichen. Namen sind unabhängig von Groß-/Kleinschreibung; Werte werden exakt verglichen. Nimm daher nur stabile Werte auf. Geänderte Statuscodes, fehlende Endpunkte sowie fehlende oder geänderte ausgewählte Header sind `ERROR`. Die Werte erscheinen nicht im Bericht, stehen aber im Manifest selbst. Speichere dort keine Zugangsdaten oder vertraulichen Headerwerte. `--max-samples` und `--max-shape-nodes` gelten je Fall.

## Qualität und Grenzen

```sh
python3 -m unittest discover -s tests -v
python3 scripts/benchmark.py --documents 5000 --repetitions 5
python3 scripts/benchmark_suite.py --cases 100 --documents 100 --repetitions 8
```

Die [Messübersicht](docs/metrics.md) nennt 115 bestandene Tests, lokale Laufzeiten und die Grenzen dieser Messungen. Die Rohdaten stehen in `docs/` als JSON. Weitere Details zu [Kompatibilität](docs/compatibility.md), [Sicherheit](docs/security.md) und [Benchmarkmethodik](docs/benchmark.md) sind in der englischen Dokumentation beschrieben.

[English README](README.md) · [MIT-Lizenz](LICENSE) · © 2026 Angus Uelsmann

## Warum nicht Optic, oasdiff oder Pact?

[oasdiff](https://github.com/oasdiff/oasdiff) vergleicht OpenAPI-Verträge. [Optic](https://github.com/opticdev/optic) bietet OpenAPI-Linting, Diffing und Tests. Nutze sie, wenn dein Vertrag in OpenAPI liegt. [Pact](https://docs.pact.io/) prüft explizite Verbraucher-/Anbieter-Verträge mit passenden Tests.

ShapeDiff braucht stattdessen beobachtete JSON-Antworten. Es passt zu undokumentierten Endpunkten, alten APIs und schnellen CI-Regressionschecks. Es kennt keine nicht beobachteten Antworten und keine Anforderungen deiner Clients. Ein unauffälliger Diff beweist deshalb keine Vertragskompatibilität; die Werkzeuge können sich ergänzen.

[Build evidence](docs/metrics.md) · [Registry publication](docs/registry.md)

<p align="center"><a href="https://github.com/IamAngusU/icon-marquee"><img src="docs/assets/stack-marquee.svg" width="760" alt="Python, JSON, GitHub and Linux"></a></p>
