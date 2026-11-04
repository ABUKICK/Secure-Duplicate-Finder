"""
Duplikat-Finder & Manager (überarbeitete Version)

Verbesserungen gegenüber der ersten Version:
- Thread-sicheres GUI: Der Worker-Thread spricht nur über eine Queue mit dem GUI.
- Dreistufige Prüfung: Dateigröße -> Schnell-Hash (Anfang + Ende) -> vollständiger SHA-256.
  Dadurch werden große Dateien, die sich nur scheinbar ähneln, nicht komplett gelesen.
- Deterministisches "Original": älteste Datei, bei Gleichstand kürzester Pfad.
- Ergebnis-Fenster: Gruppen können einzeln abgewählt oder ein anderes Original gewählt werden.
- Verschobene Dateien behalten ihre Ordnerstruktur, Namenskollisionen werden vermieden.
- Protokoll "verschoben.csv" + Funktion "Rückgängig machen".
- Symlinks und Hardlinks werden übersetzt, der Ziel-Ordner wird sauber ausgeschlossen.
- Warnung bei Laufwerks- und Systemordnern.
- Abbrechen-Button, try/finally, Fehler werden protokolliert statt verschluckt.
"""

import csv
import hashlib
import os
import queue
import shutil
import stat
import threading
import time
import tkinter as tk
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from tkinter import filedialog, messagebox, scrolledtext, ttk

BACKUP_NAME = "Duplikate_verschoben"
LOG_NAME = "verschoben.csv"
BLOCK_SIZE = 1024 * 1024        # 1 MB pro Lese-Block beim vollständigen Hash
QUICK_SIZE = 64 * 1024          # 64 KB am Anfang und am Ende für den Schnell-Hash


class Cancelled(Exception):
    """Wird geworfen, wenn der Benutzer abbricht."""


# ----------------------------------------------------------------------------
# Hilfsfunktionen
# ----------------------------------------------------------------------------
def fmt_size(num):
    num = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024


def fmt_date(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def quick_hash(path, size, cancel):
    """Hash über die ersten und letzten QUICK_SIZE Bytes (Vorfilter)."""
    if cancel.is_set():
        return path, None
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            h.update(f.read(QUICK_SIZE))
            if size > QUICK_SIZE:
                f.seek(max(QUICK_SIZE, size - QUICK_SIZE))
                h.update(f.read(QUICK_SIZE))
        return path, h.hexdigest()
    except OSError:
        return path, None


def full_hash(path, cancel):
    """Vollständiger SHA-256, blockweise, abbrechbar."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(BLOCK_SIZE):
                if cancel.is_set():
                    return path, None
                h.update(chunk)
        return path, h.hexdigest()
    except OSError:
        return path, None


def unique_destination(dest):
    """Hängt einen Zähler an, falls das Ziel schon existiert."""
    if not os.path.exists(dest):
        return dest
    base, ext = os.path.splitext(dest)
    n = 1
    while os.path.exists(f"{base}_{n}{ext}"):
        n += 1
    return f"{base}_{n}{ext}"


def risky_reason(folder):
    """Gibt einen Warntext zurück, wenn der Ordner ein Laufwerk oder Systemordner ist."""
    p = os.path.abspath(folder)
    if os.path.dirname(p) == p:
        return "Du hast ein ganzes Laufwerk bzw. das Wurzelverzeichnis gewählt."

    if os.name == "nt":
        candidates = []
        for var in ("WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
            value = os.environ.get(var)
            if value:
                candidates.append(value)
    else:
        candidates = ["/usr", "/bin", "/sbin", "/lib", "/etc", "/var", "/opt",
                      "/System", "/Library", "/Applications"]

    for c in candidates:
        c = os.path.abspath(c)
        try:
            common = os.path.commonpath([p, c])
        except ValueError:  # z. B. anderes Laufwerk unter Windows
            continue
        if os.path.normcase(common) == os.path.normcase(c):
            return f"Der Ordner liegt in einem Systembereich ({c})."
    return None


# ----------------------------------------------------------------------------
# Anwendung
# ----------------------------------------------------------------------------
class DuplicateFinderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Duplikat-Finder & Manager")
        self.root.geometry("820x660")

        self.q = queue.Queue()
        self.cancel = threading.Event()
        self.target_folder = ""
        self.meta = {}  # Pfad -> (Größe, Änderungszeit)

        # --- Ordner-Auswahl ---
        frame_top = tk.Frame(root, padx=15, pady=15)
        frame_top.pack(fill=tk.X)

        self.btn_select = tk.Button(frame_top, text="Ordner auswählen...", command=self.select_folder,
                                    font=("Arial", 10, "bold"), padx=10, pady=5)
        self.btn_select.pack(side=tk.LEFT)

        self.lbl_path = tk.Label(frame_top, text="Noch kein Ordner ausgewählt", fg="gray",
                                 font=("Arial", 10), anchor="w")
        self.lbl_path.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)

        # --- Aktionen ---
        frame_mid = tk.Frame(root, padx=15)
        frame_mid.pack(fill=tk.X)

        self.btn_start = tk.Button(frame_mid, text="Scan starten", command=self.start_scan,
                                   bg="#4CAF50", fg="white", font=("Arial", 11, "bold"), padx=15, pady=8)
        self.btn_start.pack(side=tk.LEFT, pady=10)

        self.btn_cancel = tk.Button(frame_mid, text="Abbrechen", command=self.cancel.set,
                                    state=tk.DISABLED, font=("Arial", 10), padx=10, pady=8)
        self.btn_cancel.pack(side=tk.LEFT, padx=10, pady=10)

        self.btn_undo = tk.Button(frame_mid, text="Verschiebung rückgängig machen...",
                                  command=self.start_undo, font=("Arial", 10), padx=10, pady=8)
        self.btn_undo.pack(side=tk.RIGHT, pady=10)

        # --- Fortschritt ---
        frame_progress = tk.Frame(root, padx=15, pady=5)
        frame_progress.pack(fill=tk.X)

        self.lbl_status = tk.Label(frame_progress, text="Bereit.", font=("Arial", 9, "italic"))
        self.lbl_status.pack(anchor=tk.W, pady=2)

        self.progress = ttk.Progressbar(frame_progress, orient="horizontal", length=100, mode="determinate")
        self.progress.pack(fill=tk.X, pady=2)

        # --- Protokoll ---
        frame_bottom = tk.Frame(root, padx=15, pady=10)
        frame_bottom.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame_bottom, text="Protokoll:", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        self.txt_log = scrolledtext.ScrolledText(frame_bottom, wrap=tk.WORD, font=("Consolas", 9))
        self.txt_log.pack(fill=tk.BOTH, expand=True, pady=5)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.show_startup_disclaimer)
        self.root.after(50, self.poll_queue)

    # ------------------------------------------------------------------
    # Queue-Verarbeitung (läuft ausschließlich im Hauptthread)
    # ------------------------------------------------------------------
    def poll_queue(self):
        try:
            for _ in range(200):
                self.handle(self.q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(50, self.poll_queue)

    def handle(self, msg):
        kind = msg[0]
        if kind == "log":
            self.txt_log.insert(tk.END, msg[1] + "\n")
            self.txt_log.see(tk.END)
        elif kind == "status":
            self.lbl_status.config(text=msg[1])
        elif kind == "progress":
            self.set_progress(msg[1], msg[2])
        elif kind == "groups":
            self.open_review(msg[1], msg[2], msg[3])
        elif kind == "idle":
            self.set_busy(False)
        elif kind == "info":
            messagebox.showinfo(msg[1], msg[2])

    def set_progress(self, value, maximum):
        if maximum == 0:  # unbestimmte Dauer
            if str(self.progress["mode"]) != "indeterminate":
                self.progress.config(mode="indeterminate")
                self.progress.start(15)
        else:
            if str(self.progress["mode"]) != "determinate":
                self.progress.stop()
                self.progress.config(mode="determinate")
            self.progress["maximum"] = maximum
            self.progress["value"] = value

    def set_busy(self, busy):
        self.btn_start.config(state=tk.DISABLED if busy else tk.NORMAL, bg="gray" if busy else "#4CAF50")
        self.btn_select.config(state=tk.DISABLED if busy else tk.NORMAL)
        self.btn_undo.config(state=tk.DISABLED if busy else tk.NORMAL)
        self.btn_cancel.config(state=tk.NORMAL if busy else tk.DISABLED)
        if not busy:
            self.set_progress(0, 1)
            self.progress["value"] = 0

    def post(self, *msg):
        self.q.put(msg)

    # ------------------------------------------------------------------
    # GUI-Aktionen
    # ------------------------------------------------------------------
    def show_startup_disclaimer(self):
        text = (
            "WICHTIGER HINWEIS & HAFTUNGSAUSSCHLUSS:\n\n"
            "Dieses Programm sucht nach doppelten Dateien und kann diese auf Wunsch in einen "
            "Unterordner verschieben. Es wird nichts gelöscht, und alle Verschiebungen werden in "
            f"einer Protokolldatei ({LOG_NAME}) festgehalten und lassen sich rückgängig machen.\n\n"
            "Die Nutzung erfolgt dennoch auf eigene Gefahr. Der Entwickler übernimmt keinerlei Haftung "
            "für Datenverluste, Systemfehler oder fehlerhafte Zuordnungen.\n\n"
            "Wähle nur Ordner mit eigenen Daten (keine Programm- oder Systemordner) und sichere "
            "wichtige Daten vorher.\n\n"
            "Möchtest du fortfahren?"
        )
        if not messagebox.askyesno("Sicherheitshinweis & Disclaimer", text, icon="warning"):
            self.root.destroy()

    def on_close(self):
        self.cancel.set()
        self.root.destroy()

    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.target_folder = os.path.abspath(folder)
            self.lbl_path.config(text=self.target_folder, fg="black")

    def log(self, text):
        self.post("log", text)

    def start_scan(self):
        if not self.target_folder or not os.path.isdir(self.target_folder):
            messagebox.showerror("Fehler", "Bitte wähle zuerst einen gültigen Ordner aus!")
            return

        reason = risky_reason(self.target_folder)
        if reason:
            ok = messagebox.askyesno(
                "Achtung: riskanter Ordner",
                f"{reason}\n\nDuplikate in Programm- und Systemordnern (z. B. DLL-Dateien) "
                "können Programme beschädigen, wenn sie verschoben werden.\n\n"
                "Möchtest du trotzdem fortfahren?",
                icon="warning", default="no")
            if not ok:
                return

        self.cancel.clear()
        self.txt_log.delete("1.0", tk.END)
        self.set_busy(True)
        backup = os.path.join(self.target_folder, BACKUP_NAME)
        threading.Thread(target=self.scan_worker, args=(self.target_folder, backup), daemon=True).start()

    # ------------------------------------------------------------------
    # Scan (Worker-Thread, kein direkter GUI-Zugriff!)
    # ------------------------------------------------------------------
    def scan_worker(self, folder, backup):
        try:
            self.post("status", "Schritt 1/3: Durchsuche Ordner...")
            self.post("progress", 0, 0)
            self.log(f"Starte Scan in: {folder}\n")

            by_size = defaultdict(list)
            meta = {}
            seen_ids = set()
            total, skipped_links, errors = 0, 0, 0

            for root, dirs, files in os.walk(folder):
                if self.cancel.is_set():
                    raise Cancelled
                # Ziel-Ordner exakt ausschließen (kein Substring-Vergleich)
                dirs[:] = [d for d in dirs if os.path.join(root, d) != backup]

                for name in files:
                    path = os.path.join(root, name)
                    try:
                        st = os.lstat(path)
                    except OSError:
                        errors += 1
                        continue
                    if not stat.S_ISREG(st.st_mode):   # Symlinks, Geräte etc. überspringen
                        skipped_links += 1
                        continue
                    if st.st_size == 0:
                        continue
                    if st.st_ino:                      # Hardlinks sind dieselbe Datei
                        file_id = (st.st_dev, st.st_ino)
                        if file_id in seen_ids:
                            skipped_links += 1
                            continue
                        seen_ids.add(file_id)

                    by_size[st.st_size].append(path)
                    meta[path] = (st.st_size, st.st_mtime)
                    total += 1
                    if total % 1000 == 0:
                        self.post("status", f"Schritt 1/3: {total} Dateien erfasst...")

            self.log(f"Gesamt erfasste Dateien: {total}")
            if skipped_links:
                self.log(f"Übersprungen (Symlinks/Hardlinks/Sonderdateien): {skipped_links}")
            if errors:
                self.log(f"Nicht lesbar beim Durchsuchen: {errors}")

            candidates = [p for paths in by_size.values() if len(paths) > 1 for p in paths]
            self.log(f"Kandidaten mit gleicher Dateigröße: {len(candidates)}\n")

            # Schritt 2: Schnell-Hash
            quick = self.hash_stage(
                candidates, lambda p: quick_hash(p, meta[p][0], self.cancel),
                "Schritt 2/3: Schnellprüfung")
            buckets = defaultdict(list)
            for path, h in quick.items():
                if h:
                    buckets[(meta[path][0], h)].append(path)
            candidates = [p for paths in buckets.values() if len(paths) > 1 for p in paths]
            self.log(f"Kandidaten nach Schnellprüfung: {len(candidates)}\n")

            # Schritt 3: vollständiger Hash
            full = self.hash_stage(
                candidates, lambda p: full_hash(p, self.cancel),
                "Schritt 3/3: Vollständige Prüfung")
            final = defaultdict(list)
            for path, h in full.items():
                if h:
                    final[(meta[path][0], h)].append(path)

            groups = []
            for paths in final.values():
                if len(paths) > 1:
                    # Deterministisch: älteste Datei zuerst, dann kürzester Pfad, dann alphabetisch
                    paths.sort(key=lambda p: (meta[p][1], len(p), p))
                    groups.append(paths)
            groups.sort(key=lambda g: -(meta[g[0]][0] * (len(g) - 1)))  # größte Ersparnis zuerst

            if not groups:
                self.log("Fertig! Keine doppelten Dateien gefunden.")
                self.post("status", "Fertig. Keine Duplikate gefunden.")
                self.post("idle")
                self.post("info", "Ergebnis", "Keine doppelten Dateien gefunden!")
                return

            extra = sum(len(g) - 1 for g in groups)
            wasted = sum(meta[g[0]][0] * (len(g) - 1) for g in groups)
            self.log(f"Gefundene Duplikat-Gruppen: {len(groups)}")
            self.log(f"Überflüssige Kopien: {extra} ({fmt_size(wasted)})")
            self.post("status", "Warte auf deine Auswahl...")
            self.post("idle")
            self.post("groups", groups, meta, (folder, backup))

        except Cancelled:
            self.log("\nScan vom Benutzer abgebrochen. Es wurde nichts verändert.")
            self.post("status", "Abgebrochen.")
            self.post("idle")
        except Exception as e:
            self.log(f"\nUnerwarteter Fehler: {e!r}")
            self.post("status", "Fehler.")
            self.post("idle")

    def hash_stage(self, paths, func, label):
        """Hasht Dateien parallel und meldet den Fortschritt. Gibt {pfad: hash|None} zurück."""
        results = {}
        total = len(paths)
        if total == 0:
            return results

        self.post("progress", 0, total)
        workers = min(8, os.cpu_count() or 4)  # mehr Threads bremsen vor allem bei HDDs
        failed = 0

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(func, p) for p in paths]
            try:
                for done, fut in enumerate(as_completed(futures), 1):
                    if self.cancel.is_set():
                        raise Cancelled
                    path, h = fut.result()
                    results[path] = h
                    if h is None:
                        failed += 1
                        if not self.cancel.is_set():
                            self.log(f"  Nicht lesbar (übersprungen): {path}")
                    if done % 10 == 0 or done == total:
                        self.post("progress", done, total)
                        self.post("status", f"{label}... ({done}/{total}, {int(done / total * 100)}%)")
            finally:
                for f in futures:
                    f.cancel()
        if failed:
            self.log(f"{failed} Datei(en) konnten nicht gelesen werden.")
        return results

    # ------------------------------------------------------------------
    # Ergebnis-Fenster
    # ------------------------------------------------------------------
    def open_review(self, groups, meta, folders):
        folder, backup = folders
        win = tk.Toplevel(self.root)
        win.title("Duplikate auswählen")
        win.geometry("980x600")
        win.transient(self.root)
        win.grab_set()

        tk.Label(win, text="Klicke in der Spalte 'Verschieben?' auf ☑ / ☐ (oder wähle eine Zeile und drücke "
                           "die Leertaste), um eine Datei an- oder abzuwählen. Nur ☑-Dateien werden verschoben. "
                           "Pro Gruppe bleibt mindestens eine Datei erhalten.",
                 anchor="w", justify="left", wraplength=940, padx=10, pady=8).pack(fill=tk.X)

        frame = tk.Frame(win)
        frame.pack(fill=tk.BOTH, expand=True, padx=10)

        cols = ("aktion", "groesse", "datum")
        tree = ttk.Treeview(frame, columns=cols, selectmode="browse")
        tree.heading("#0", text="Datei")
        tree.heading("aktion", text="Verschieben?")
        tree.heading("groesse", text="Größe")
        tree.heading("datum", text="Geändert")
        tree.column("#0", width=600)
        tree.column("aktion", width=110, anchor="center")
        tree.column("groesse", width=90, anchor="e")
        tree.column("datum", width=130, anchor="center")
        tree.tag_configure("move", foreground="#b23b3b")
        tree.tag_configure("keep", foreground="#2e7d32")

        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        move = {}       # iid -> True (verschieben) / False (behalten)
        group_of = {}   # iid -> Gruppen-iid
        paths = {}      # iid -> Pfad

        def refresh(iid):
            tree.set(iid, "aktion", "☑ Verschieben" if move[iid] else "☐ Behalten")
            tree.item(iid, tags=("move" if move[iid] else "keep",))

        def set_default():
            for gid in tree.get_children():
                for j, iid in enumerate(tree.get_children(gid)):
                    move[iid] = j > 0
                    refresh(iid)
            update_summary()

        lbl_summary = tk.Label(win, anchor="w", padx=10, pady=6, font=("Arial", 10, "bold"))

        def update_summary():
            sel = [i for i, m in move.items() if m]
            size = sum(meta[paths[i]][0] for i in sel)
            lbl_summary.config(text=f"{len(sel)} Dateien zum Verschieben markiert ({fmt_size(size)})")

        for n, group in enumerate(groups, 1):
            size = meta[group[0]][0]
            gid = tree.insert("", "end", open=True,
                              text=f"Gruppe {n} – {len(group)} identische Dateien",
                              values=("", fmt_size(size), ""))
            for p in group:
                iid = tree.insert(gid, "end", text=p,
                                  values=("", fmt_size(size), fmt_date(meta[p][1])))
                group_of[iid] = gid
                paths[iid] = p

        def toggle_iid(iid):
            if iid not in move:
                return
            siblings = tree.get_children(group_of[iid])
            if not move[iid]:  # Behalten -> Verschieben: nur wenn noch eine andere Datei bleibt
                if sum(1 for s in siblings if not move[s]) <= 1:
                    messagebox.showinfo("Nicht möglich",
                                        "Pro Gruppe muss mindestens eine Datei erhalten bleiben.\n\n"
                                        "Wähle zuerst eine andere Datei als Original "
                                        "('Als Original behalten').", parent=win)
                    return
            move[iid] = not move[iid]
            refresh(iid)
            update_summary()

        def on_click(event):
            # Einzelklick auf die Spalte "Verschieben?" schaltet die Datei um
            if tree.identify_region(event.x, event.y) != "cell":
                return
            if tree.identify_column(event.x) != "#1":
                return
            toggle_iid(tree.identify_row(event.y))

        def toggle_selected(event=None):
            sel = tree.selection()
            if not sel:
                return
            iid = sel[0]
            if iid in move:
                toggle_iid(iid)
            else:  # Gruppenzeile: ganze Gruppe abwählen bzw. wieder standardmäßig markieren
                children = tree.get_children(iid)
                if any(move[c] for c in children):
                    for c in children:
                        move[c] = False
                        refresh(c)
                else:
                    for j, c in enumerate(children):
                        move[c] = j > 0
                        refresh(c)
                update_summary()

        def make_original():
            sel = tree.selection()
            if not sel or sel[0] not in move:
                return
            for s in tree.get_children(group_of[sel[0]]):
                move[s] = (s != sel[0])
                refresh(s)
            update_summary()

        def keep_all():
            for iid in move:
                move[iid] = False
                refresh(iid)
            update_summary()

        def start_move():
            selected = [paths[i] for i, m in move.items() if m]
            if not selected:
                messagebox.showinfo("Nichts ausgewählt", "Es ist keine Datei zum Verschieben markiert.", parent=win)
                return
            if not messagebox.askyesno(
                    "Bestätigung",
                    f"{len(selected)} Dateien nach\n'{backup}'\nverschieben?\n\n"
                    "Du kannst das später rückgängig machen.", parent=win):
                return
            win.destroy()
            self.cancel.clear()
            self.set_busy(True)
            threading.Thread(target=self.move_worker, args=(selected, folder, backup), daemon=True).start()

        tree.bind("<Button-1>", on_click)
        tree.bind("<space>", toggle_selected)

        lbl_summary.pack(fill=tk.X)
        bar = tk.Frame(win, padx=10, pady=10)
        bar.pack(fill=tk.X)
        tk.Button(bar, text="Auswahl an/aus", command=toggle_selected, padx=8).pack(side=tk.LEFT)
        tk.Button(bar, text="Als Original behalten", command=make_original, padx=8).pack(side=tk.LEFT, padx=6)
        tk.Button(bar, text="Alle markieren", command=set_default, padx=8).pack(side=tk.LEFT)
        tk.Button(bar, text="Alle abwählen", command=keep_all, padx=8).pack(side=tk.LEFT, padx=6)
        tk.Button(bar, text="Schließen", command=win.destroy, padx=8).pack(side=tk.RIGHT)
        tk.Button(bar, text="Markierte verschieben", command=start_move, bg="#4CAF50", fg="white",
                  font=("Arial", 10, "bold"), padx=12).pack(side=tk.RIGHT, padx=8)

        set_default()

    # ------------------------------------------------------------------
    # Verschieben (Worker-Thread)
    # ------------------------------------------------------------------
    def move_worker(self, selected, folder, backup):
        moved, failed = 0, 0
        try:
            os.makedirs(backup, exist_ok=True)
            log_path = os.path.join(backup, LOG_NAME)
            is_new = not os.path.exists(log_path)
            total = len(selected)
            self.log(f"\nVerschiebe {total} Dateien nach: {backup}")
            self.post("status", "Verschiebe Dateien...")
            self.post("progress", 0, total)

            with open(log_path, "a", newline="", encoding="utf-8-sig") as logfile:
                writer = csv.writer(logfile, delimiter=";")
                if is_new:
                    writer.writerow(["zeitpunkt", "original_pfad", "neuer_pfad", "groesse_bytes"])
                    logfile.flush()

                for i, src in enumerate(selected, 1):
                    if self.cancel.is_set():
                        raise Cancelled
                    try:
                        size = os.path.getsize(src)
                        rel = os.path.relpath(src, folder)
                        dest = unique_destination(os.path.join(backup, rel))
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        shutil.move(src, dest)
                        writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), src, dest, size])
                        logfile.flush()
                        moved += 1
                    except Exception as e:
                        failed += 1
                        self.log(f"Fehler beim Verschieben von {src}: {e}")
                    if i % 10 == 0 or i == total:
                        self.post("progress", i, total)

            self.log(f"Fertig: {moved} verschoben, {failed} Fehler. Protokoll: {log_path}")
            self.post("status", "Fertig!")
            self.post("idle")
            self.post("info", "Fertig", f"{moved} Dateien wurden verschoben ({failed} Fehler).\n\n"
                                        f"Protokoll: {log_path}")
        except Cancelled:
            self.log(f"\nVerschieben abgebrochen. Bereits verschoben: {moved} (siehe {LOG_NAME}).")
            self.post("status", "Abgebrochen.")
            self.post("idle")
        except Exception as e:
            self.log(f"\nKritischer Fehler: {e!r}")
            self.post("status", "Fehler.")
            self.post("idle")

    # ------------------------------------------------------------------
    # Rückgängig machen
    # ------------------------------------------------------------------
    def start_undo(self):
        initial = os.path.join(self.target_folder, BACKUP_NAME) if self.target_folder else None
        if initial and not os.path.isdir(initial):
            initial = self.target_folder or None
        backup = filedialog.askdirectory(title=f"Ordner '{BACKUP_NAME}' auswählen", initialdir=initial)
        if not backup:
            return
        log_path = os.path.join(backup, LOG_NAME)
        if not os.path.isfile(log_path):
            messagebox.showerror("Fehler", f"In diesem Ordner liegt keine '{LOG_NAME}'.")
            return
        if not messagebox.askyesno("Rückgängig machen",
                                   "Alle im Protokoll verzeichneten Dateien an ihren "
                                   "ursprünglichen Ort zurückverschieben?"):
            return
        self.cancel.clear()
        self.set_busy(True)
        threading.Thread(target=self.undo_worker, args=(backup, log_path), daemon=True).start()

    def undo_worker(self, backup, log_path):
        restored, skipped = 0, 0
        try:
            with open(log_path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f, delimiter=";"))
            total = len(rows)
            self.log(f"\nStelle {total} Dateien wieder her...")
            self.post("progress", 0, max(total, 1))

            for i, row in enumerate(rows, 1):
                if self.cancel.is_set():
                    raise Cancelled
                orig, current = row["original_pfad"], row["neuer_pfad"]
                try:
                    if not os.path.exists(current):
                        self.log(f"Übersprungen (nicht mehr vorhanden): {current}")
                        skipped += 1
                    elif os.path.exists(orig):
                        self.log(f"Übersprungen (am Ursprungsort existiert bereits eine Datei): {orig}")
                        skipped += 1
                    else:
                        os.makedirs(os.path.dirname(orig), exist_ok=True)
                        shutil.move(current, orig)
                        restored += 1
                except Exception as e:
                    skipped += 1
                    self.log(f"Fehler bei {current}: {e}")
                if i % 10 == 0 or i == total:
                    self.post("progress", i, max(total, 1))

            # Leere Unterordner im Duplikat-Ordner aufräumen (Wurzel bleibt)
            for dirpath, _, _ in os.walk(backup, topdown=False):
                if dirpath != backup:
                    try:
                        os.rmdir(dirpath)
                    except OSError:
                        pass

            self.log(f"Fertig: {restored} wiederhergestellt, {skipped} übersprungen.")
            self.post("status", "Fertig!")
            self.post("idle")
            self.post("info", "Fertig", f"{restored} Dateien wiederhergestellt, {skipped} übersprungen.")
        except Cancelled:
            self.log("\nWiederherstellung abgebrochen.")
            self.post("status", "Abgebrochen.")
            self.post("idle")
        except Exception as e:
            self.log(f"\nFehler bei der Wiederherstellung: {e!r}")
            self.post("status", "Fehler.")
            self.post("idle")


if __name__ == "__main__":
    root = tk.Tk()
    app = DuplicateFinderApp(root)
    root.mainloop()
