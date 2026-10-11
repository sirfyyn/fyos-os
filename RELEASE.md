# Eine Version veröffentlichen

Anleitung für Maintainer. Eine FYOS-Version besteht aus zwei Repos mit demselben Tag: `fyos-agent` (Bild `openclaw`) und
`fyos-os` (Bilder `web` und `hub`, PyPI-Pakete `fyos-hub` und `fyos-installer`). Der Installer zieht das Agent-Bild mit
dem Tag seiner eigenen Version (`AGENT_TAG` in `installer/fyos_installer/erzeugen.py`). Deshalb bekommt `fyos-agent`
den Tag zuerst. Die Beispiele nennen Version 0.1.1; setze deine Version ein.

Halte die Reihenfolge ein und gehe erst weiter, wenn der Schritt davor stimmt. Ein veröffentlichter PyPI-Eintrag
und ein Tag auf GitHub lassen sich nicht zurücknehmen.

## Vorher: die Version steht überall

Ein Pull Request im Git-Server bereitet die Version vor und ist gemergt, bevor es losgeht:

- `fyos-hub` (`hub/pyproject.toml`, `hub/mcp_hub/__init__.py`), `fyos-installer` (`installer/pyproject.toml`,
  `installer/fyos_installer/__init__.py`) und `web/package.json` samt `web/package-lock.json` tragen die Version.
- `AGENT_TAG` im Installer zeigt auf den Tag der Version (`v0.1.1`); der Test `installer/tests/test_erzeugen.py` prüft das.
- `CHANGELOG.md` hat einen Abschnitt für die Version (in beiden Repos). Setze beim Veröffentlichen „unveröffentlicht“
  durch das Datum.

## Ablauf

1. **Hauptzweig des Git-Servers ist grün.** In beiden Repos ist der letzte Lauf auf `main` fehlerfrei, auch der
   Zeitplan-Lauf. Ein roter Lauf wird behoben, nicht übergangen.
2. **Sauberkeit der Historie prüfen**, zuerst in `fyos-agent`, dann in `fyos-os`:

   ```sh
   python3 tools/sauber.py --historie
   ```

   Der Befehl muss still bleiben und mit Exitcode 0 enden. Er prüft Namen und Adressen von Autor und Committer sowie
   alle Commit-Texte. Ein Befund heißt: nichts veröffentlichen, erst die Ursache beseitigen.
3. **Abzug nach GitHub**, zuerst `fyos-agent`, dann `fyos-os`. Der Abzug ist ein sauberer Stand des Hauptzweigs ohne
   die Historie des Git-Servers, der Commit trägt den Stempel „FYOS 0.1.1“. Prüfe nach dem Schieben, dass der
   Hauptzweig auf GitHub den erwarteten Stand hat und die Dateien aus diesem Repo übereinstimmen.
4. **Tag `v0.1.1` setzen**, zuerst in `fyos-agent`, dann in `fyos-os`, jeweils auf den Abzug auf GitHub. Der Tag löst die
   Läufe aus: in `fyos-agent` das Bild `openclaw`, in `fyos-os` die Läufe `tests`, `pypi` und `bilder`. Warte nach dem
   ersten Tag, bis das Agent-Bild liegt, bevor du den zweiten setzt.
5. **Prüfen**, dass alles angekommen ist:
   - Die Läufe `tests`, `pypi` und `bilder` (und in `fyos-agent` `tests` und `bilder`) sind grün.
   - Auf PyPI liegen `fyos-hub` und `fyos-installer` in Version 0.1.1.
   - In der Registry `ghcr.io/sirfyyn` liegen die Tags `v0.1.1` und `latest` für `fyos-os/web`, `fyos-os/hub` und <!-- sauber: ok -->
     `fyos-agent/openclaw`.
   - Der Installer läuft im Trockenlauf mit der veröffentlichten Version durch und nennt die Bilder mit dem Tag
     `v0.1.1`:

     ```sh
     pipx run --spec fyos-installer==0.1.1 fyos-install --auswahl kern,agent --ziel compose --trocken
     ```

     Der Plan muss die Bilder `web`, `hub` und `openclaw` mit dem Tag `v0.1.1` nennen. Statt `pipx` taugt auch eine
     frische virtuelle Umgebung mit `pip install fyos-installer==0.1.1`.
6. **Erst dann der Release-Text auf GitHub**, je Repo aus dem Abschnitt der Version in `CHANGELOG.md`. Den Text nimmst
   du wörtlich aus dem Abschnitt und ergänzt höchstens die Links auf die Pakete und Bilder.

## Wenn etwas schiefgeht

- **Ein Lauf ist rot, bevor etwas veröffentlicht wurde** (PyPI-Prüfung, Bildbau): Ursache beheben, in beiden Repos einen
  neuen Stand über einen Pull Request nachziehen, den Abzug wiederholen und den Tag neu setzen. Einen Tag, der keinen
  veröffentlichten Stand trägt, darfst du löschen und neu setzen.
- **PyPI hat die Pakete schon:** Eine Version lässt sich dort nicht überschreiben. Behebe den Fehler in einer neuen
  Patch-Version (zum Beispiel 0.1.2) und markiere 0.1.1 bei Bedarf auf PyPI als „yanked“.
- **Ein Bild-Tag fehlt:** Den Lauf `bilder` von Hand für den Tag starten (Actions, `bilder`, „Run workflow“).
