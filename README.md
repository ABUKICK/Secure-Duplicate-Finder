# Duplikat-Entferner & Manager (in Entwicklung)

[🇩🇪 Deutsch](#-deutsch) | [🇬🇧 English](#-english)

---

## 🇩🇪 Deutsch

⚠️ **WICHTIGER WARNHINWEIS:** Dieses Tool befindet sich aktuell in einem **unvollständigen Entwicklungsstadium**. Es handelt sich um ein privates, experimentelles Skript zur Erkennung von doppelten Dateien. Es gibt **keinerlei** Garantie für die fehlerfreie Funktionsweise.

### 💡 Warum ich dieses Tool entwickelt habe (Motivation)

Jeder kennt das Problem: Man sucht im Internet nach einem einfachen Tool, um doppelte Dateien zu finden, und stößt fast nur auf aufgeblähte Programme voller Werbung, versteckter Adware, Abofallen oder intransparenter `.exe`-Dateien, bei denen man nie genau weiß, was sie im Hintergrund installieren oder mit den eigenen Daten anstellen.

Als Content Creator und Streamer sammelten sich auf meinen Festplatten Gigabytes an Videomaterial an. Ich wollte eine **100 % reine, saubere und transparente Lösung** ohne Müll-Software.

Deshalb habe ich diesen **Duplikat-Entferner** entwickelt:

* **Keine Werbung, keine Bloatware, kein Datenabfluss.**

* **Vollständige Transparenz:** Ein offenes Python-Skript, bei dem du genau siehst, was mit deinen Dateien passiert.

* **Volle Kontrolle:** Kein automatisches Löschen im Hintergrund – der Nutzer entscheidet jederzeit selbst.

### ⚠️ Haftungsausschluss & Risiko von Datenverlust

**Die Nutzung dieses Programms erfolgt ausdrücklich auf eigene Gefahr und Verantwortung!**

* **Keine Haftung für Schäden:** Der Entwickler übernimmt keinerlei Haftung für Datenverluste, beschädigte Dateien, Systemfehler oder fehlerhafte Zuordnungen.

* **Risiko von Datenverlust:** Auch wenn das Tool standardmäßig versucht, Duplikate in einen Backup-Ordner zu verschieben statt sie direkt zu löschen, kann es durch Fehlbedienung, falsche Pfade oder unvorhergesehene Fehler zu Datenverlust kommen.

* **Vorheriges Backup Pflicht:** Nutze dieses Tool **niemals** mit deinen echten Original- oder Produktivdaten, ohne vorher ein separates, manuelles Backup erstellt zu haben. Teste das Programm grundsätzlich nur mit Test-Ordnern.

### 🛠️ Funktionen

* **Mehrstufige Prüfung:** Kombiniert Dateigröße, einen schnellen Vor-Hash (Anfang und Ende) und einen vollständigen SHA-256-Hash.

* **Grafische Benutzeroberfläche (GUI):** Entwickelt mit `tkinter`, mit Hintergrund-Threads (`threading` und `queue`), damit das Fenster nicht einfriert.

* **Manuelle Auswahl:** Keine blinde Automatisierung – im Ergebnis-Fenster entscheidest du selbst, was verschoben wird.

* **Backup & Undo:** Verschobene Dateien landen in einem separaten Backup-Ordner (unter Beibehaltung der Ordnerstruktur). Eine CSV-Protokolldatei (`verschoben.csv`) ermöglicht im Idealfall die Wiederherstellung.

### 🚀 Verwendung

* **Voraussetzungen:** Python 3 (nur Standardbibliotheken erforderlich).

* **Start:** `python duplikat_finder_gui.py`

---

## 🇬🇧 English

⚠️ **IMPORTANT WARNING:** This tool is currently in an **incomplete state of development**. It is a private, experimental script designed to find duplicate files. There is **no guarantee** whatsoever for error-free operation.

### 💡 Why I Built This (Motivation)

We all know the struggle: You search the internet for a simple duplicate file finder and mostly end up finding bloated software filled with ads, hidden adware, subscription traps, or sketchy `.exe` files where you never truly know what they are doing to your PC in the background.

As a content creator and streamer, gigabytes of video recordings quickly accumulated on my drives. I wanted a **100% clean, transparent, and pure solution** without any junk software attached.

That is why I created this **Duplicate Finder**:

* **Zero ads, zero bloatware, zero tracking.**

* **Complete Transparency:** Open Python code where you can inspect exactly how your files are being handled.

* **Full Control:** No background auto-deletions—the user always stays in full command.

### ⚠️ Disclaimer & Risk of Data Loss

**The use of this program is strictly at your own risk and responsibility!**

* **No Liability:** The developer assumes no liability for data loss, damaged files, system errors, or incorrect assignments.

* **Risk of Data Loss:** Although the tool is designed to move duplicates to a backup folder rather than deleting them directly, human error, incorrect paths, or unforeseen bugs can still lead to data loss.

* **Backup Mandatory:** **Never** use this tool on your actual original or production data without making a separate, manual backup first. Always test the program using test folders.

### 🛠️ Features

* **Multi-tier verification:** Combines file size, a fast quick-hash (start and end), and a full SHA-256 hash.

* **Graphical User Interface (GUI):** Built with `tkinter`, using background threads (`threading` and `queue`) to keep the UI responsive.

* **Manual Review:** No blind automation—you have full review and control over what gets moved.

* **Backup & Undo:** Moved files are stored in a designated backup folder preserving the directory structure. A CSV log file (`verschoben.csv`) allows for potential restoration.

### 🚀 Usage

* **Requirements:** Python 3 (standard libraries only).

* **Run:** `python duplikat_finder_gui.py`

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
