"""
Displacement Extraction Tool
-----------------------------
NASTRAN sonuç dosyalarından (.op2 veya .h5/.hdf5) belirli node ID'leri için
displacement sonuçlarını (T1, T2, T3, Resultant) tüm subcaseler için çeker.

Kullanım (modül olarak):
    from displacement_extractor import extract_displacements, print_results
    results = extract_displacements("results.op2", [101, 102, 103])
    print_results(results)

Kullanım (CLI):
    python displacement_extractor.py --file results.op2 --nodes 101 102 103
"""

import argparse
import csv
import math
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List

# Üçüncü taraf kütüphaneleri kontrol et
_missing = []
try:
    import h5py
except ImportError:
    _missing.append("h5py")
try:
    import numpy as np
    # numpy 2.x'te np.float kaldırıldı; eski openpyxl sürümleri bunu kullanıyor
    if not hasattr(np, "float"):
        np.float = float
    if not hasattr(np, "int"):
        np.int = int
    if not hasattr(np, "complex"):
        np.complex = complex
    if not hasattr(np, "bool"):
        np.bool = bool
except ImportError:
    _missing.append("numpy")
try:
    import openpyxl
except ImportError:
    _missing.append("openpyxl")
try:
    from pyNastran.op2.op2 import OP2
except ImportError:
    _missing.append("pyNastran")

if _missing:
    _root = tk.Tk()
    _root.withdraw()
    messagebox.showerror(
        "Eksik Kütüphaneler",
        "Şu paketler kurulu değil:\n"
        + ", ".join(_missing)
        + "\n\nKomut satırında şunu çalıştırın:\n"
        + "pip install " + " ".join(_missing)
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Treeview sütun sabitleri
# ---------------------------------------------------------------------------

_ALL_COLS = (
    "Subcase", "Prop", "Length", "Width", "Node",
    "T1", "T2", "T3", "Resultant",
    "Max T1", "Min T1", "Max T2", "Min T2",
    "Max T3", "Min T3", "Max Res", "Min Res",
    "Status",
)
_DISPLAY_ABS_NODE = ("Subcase", "Node", "T1", "T2", "T3", "Resultant")
_DISPLAY_ABS_PROP = ("Subcase", "Prop", "Length", "Width", "Node", "T1", "T2", "T3", "Resultant", "Status")
_DISPLAY_REL_PROP = (
    "Subcase", "Prop", "Length", "Width",
    "Max T1", "Min T1", "Max T2", "Min T2",
    "Max T3", "Min T3", "Max Res", "Min Res",
    "Status",
)

def _fail_pass(disp: float, length: float) -> str:
    """Panel uzunluğuna göre displacement limit kontrolü."""
    if length <= 0:
        return "-"
    if length < 508.0:
        return "FAIL" if disp / length > 0.015 else "PASS"
    else:
        return "FAIL" if disp > 7.62 else "PASS"


# ---------------------------------------------------------------------------
# Çekirdek okuma fonksiyonları
# ---------------------------------------------------------------------------

def _read_op2(filepath: str, node_ids: List[int]) -> Dict:
    """OP2 dosyasından displacement verisi okur."""
    op2 = OP2(debug=False)
    op2.read_op2(filepath)

    if not op2.displacements:
        raise ValueError("OP2 dosyasında displacement sonucu bulunamadı.")

    node_set = set(node_ids)
    results = {}

    for subcase_id, disp in op2.displacements.items():
        file_node_ids = disp.node_gridtype[:, 0].tolist()
        data = disp.data  # shape: [n_time_steps, n_nodes, 6]

        subcase_results = {}
        for i, nid in enumerate(file_node_ids):
            if nid in node_set:
                t1 = float(data[0, i, 0])
                t2 = float(data[0, i, 1])
                t3 = float(data[0, i, 2])
                subcase_results[nid] = {
                    "T1": t1,
                    "T2": t2,
                    "T3": t3,
                    "Resultant": math.sqrt(t1**2 + t2**2 + t3**2),
                }

        results[subcase_id] = subcase_results

    return results


def _read_h5(filepath: str, node_ids: List[int]) -> Dict:
    """NASTRAN HDF5 dosyasından displacement verisi okur."""
    node_set = set(node_ids)
    results = {}

    with h5py.File(filepath, "r") as f:
        domains_path = "/NASTRAN/RESULT/DOMAINS"
        if domains_path not in f:
            raise ValueError("HDF5 dosyasında /NASTRAN/RESULT/DOMAINS bulunamadı.")

        domains_ds = f[domains_path]
        if hasattr(domains_ds, "dtype") and domains_ds.dtype.names:
            domains_data = domains_ds[:]
            domain_ids = domains_data["ID"]
            subcases = domains_data["SUBCASE"]
        else:
            domain_ids = domains_ds["ID"][:]
            subcases = domains_ds["SUBCASE"][:]
        domain_to_subcase = dict(zip(domain_ids.tolist(), subcases.tolist()))

        disp_path = "/NASTRAN/RESULT/NODAL/DISPLACEMENT"
        if disp_path not in f:
            raise ValueError(f"HDF5 dosyasında displacement sonucu bulunamadı. Beklenen: {disp_path}")

        disp_ds = f[disp_path]

        def _pick(names, candidates):
            for c in candidates:
                if c in names:
                    return c
            raise ValueError(
                f"HDF5 displacement dataset'inde beklenen alan bulunamadı.\n"
                f"Denenen: {candidates}\nMevcut: {list(names)}"
            )

        # MSC Nastran HDF5: tek compound dataset (sütunlar: ID, T1, T2, T3, DOMAIN_ID ...)
        # NX Nastran HDF5:  ayrı alt-dataset'ler
        if hasattr(disp_ds, "dtype") and disp_ds.dtype.names:
            # Compound dataset
            disp_data = disp_ds[:]
            names = disp_data.dtype.names
            id_f  = _pick(names, ["ID", "GRID_ID", "NID"])
            dom_f = _pick(names, ["DOMAIN_ID", "DOMAIN"])
            t1_f  = _pick(names, ["T1", "DX", "X1", "X"])
            t2_f  = _pick(names, ["T2", "DY", "X2", "Y"])
            t3_f  = _pick(names, ["T3", "DZ", "X3", "Z"])
            file_node_ids = disp_data[id_f]
            domain_id_arr = disp_data[dom_f]
            t1_arr = disp_data[t1_f]
            t2_arr = disp_data[t2_f]
            t3_arr = disp_data[t3_f]
        else:
            # Alt-dataset yapısı
            keys = list(disp_ds.keys())
            id_f  = _pick(keys, ["ID", "GRID_ID", "NID"])
            dom_f = _pick(keys, ["DOMAIN_ID", "DOMAIN"])
            t1_f  = _pick(keys, ["T1", "DX", "X1", "X"])
            t2_f  = _pick(keys, ["T2", "DY", "X2", "Y"])
            t3_f  = _pick(keys, ["T3", "DZ", "X3", "Z"])
            file_node_ids = disp_ds[id_f][:]
            domain_id_arr = disp_ds[dom_f][:]
            t1_arr = disp_ds[t1_f][:]
            t2_arr = disp_ds[t2_f][:]
            t3_arr = disp_ds[t3_f][:]

        unique_domains = np.unique(domain_id_arr)
        for domain_id in unique_domains:
            subcase_id = domain_to_subcase.get(int(domain_id), int(domain_id))
            mask = domain_id_arr == domain_id

            subcase_results = {}
            for i, nid in enumerate(file_node_ids[mask].tolist()):
                if nid in node_set:
                    t1 = float(t1_arr[mask][i])
                    t2 = float(t2_arr[mask][i])
                    t3 = float(t3_arr[mask][i])
                    subcase_results[nid] = {
                        "T1": t1,
                        "T2": t2,
                        "T3": t3,
                        "Resultant": math.sqrt(t1**2 + t2**2 + t3**2),
                    }

            results[subcase_id] = subcase_results

    return results


def extract_displacements(filepath: str, node_ids: List[int]) -> Dict:
    """
    NASTRAN sonuç dosyasından verilen node ID'leri için displacement değerlerini çeker.

    Parametreler
    ------------
    filepath : str
        .op2 veya .h5 / .hdf5 dosya yolu
    node_ids : list[int]
        Sorgulanacak node ID listesi

    Dönüş
    ------
    dict
        {subcase_id: {node_id: {"T1": float, "T2": float, "T3": float, "Resultant": float}}}
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Dosya bulunamadı: {filepath}")

    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".op2":
        return _read_op2(filepath, node_ids)
    elif ext in (".h5", ".hdf5"):
        return _read_h5(filepath, node_ids)
    else:
        raise ValueError(f"Desteklenmeyen dosya uzantısı: '{ext}'. Lütfen .op2 veya .h5/.hdf5 kullanın.")


def print_results(results: Dict) -> None:
    """Displacement sonuçlarını tablo formatında ekrana basar."""
    if not results:
        print("Sonuç bulunamadı.")
        return

    col_w = 14
    header = (
        f"  {'Node':>8}  "
        f"{'T1':>{col_w}}  {'T2':>{col_w}}  "
        f"{'T3':>{col_w}}  {'Resultant':>{col_w}}"
    )
    separator = "  " + "-" * (8 + 4 * (col_w + 2))

    for subcase_id in sorted(results):
        print(f"\nSubcase {subcase_id}:")
        print(header)
        print(separator)
        node_data = results[subcase_id]
        if not node_data:
            print("    (Bu subcase'de istenen node'lar bulunamadı)")
            continue
        for nid in sorted(node_data):
            d = node_data[nid]
            print(
                f"  {nid:>8}  "
                f"{d['T1']:>{col_w}.3f}  {d['T2']:>{col_w}.3f}  "
                f"{d['T3']:>{col_w}.3f}  {d['Resultant']:>{col_w}.3f}"
            )


# ---------------------------------------------------------------------------
# Node ID dosya okuyucusu (Excel / CSV)
# ---------------------------------------------------------------------------

def _read_node_ids_from_file(filepath: str) -> List[int]:
    """Excel (.xlsx, .xlsm) veya CSV dosyasının ilk sütunundan node ID listesi okur.

    Sayı olmayan hücreler (başlık satırı dahil) ve boş hücreler atlanır.
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        return _read_node_ids_xlsx(filepath)
    elif ext == ".csv":
        return _read_node_ids_csv(filepath)
    else:
        raise ValueError(f"Desteklenmeyen dosya türü: '{ext}'. Lütfen .xlsx, .xlsm veya .csv kullanın.")


def _read_node_ids_xlsx(filepath: str) -> List[int]:
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active
    node_ids = []
    for row in ws.iter_rows(min_col=1, max_col=1, values_only=True):
        val = row[0]
        if val is None:
            continue
        try:
            node_ids.append(int(val))
        except (TypeError, ValueError):
            pass
    wb.close()

    if not node_ids:
        raise ValueError("Excel dosyasının A sütununda geçerli node ID bulunamadı.")
    return node_ids


def _read_node_ids_csv(filepath: str) -> List[int]:
    node_ids = []
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            try:
                node_ids.append(int(row[0].strip()))
            except (ValueError, IndexError):
                pass  # başlık veya sayı olmayan satır — atla

    if not node_ids:
        raise ValueError("CSV dosyasının ilk sütununda geçerli node ID bulunamadı.")
    return node_ids


def _get_nodes_from_props(bdf_filepath: str, prop_ids: List[int]):
    """BDF dosyasından verilen prop ID'lerine bağlı tüm node ID'lerini döndürür.

    Returns (sorted_node_ids, node_to_prop_dict, prop_dims_dict).
    prop_dims_dict: {prop_id: (length, width)} — global koordinat bounding box,
                    length = X-aralığı, width = Y-aralığı.
    """
    from pyNastran.bdf.bdf import BDF
    bdf = BDF(debug=False)
    bdf.read_bdf(bdf_filepath)
    prop_set = set(prop_ids)
    node_to_prop: dict = {}
    prop_nodes: dict = {pid: [] for pid in prop_set}
    for elem in bdf.elements.values():
        if hasattr(elem, "pid") and elem.pid in prop_set:
            for nid in elem.nodes:
                node_to_prop[nid] = elem.pid
                prop_nodes[elem.pid].append(nid)
    if not node_to_prop:
        raise ValueError(
            f"Verilen prop ID'lere ({sorted(prop_set)}) bağlı hiç node bulunamadı."
        )

    prop_dims: dict = {}
    for pid, nids in prop_nodes.items():
        if not nids:
            prop_dims[pid] = (0.0, 0.0)
            continue
        coords = [bdf.nodes[nid].get_position() for nid in set(nids)]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        prop_dims[pid] = (max(xs) - min(xs), max(ys) - min(ys))

    return sorted(node_to_prop.keys()), node_to_prop, prop_dims


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class LoadExtractionApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("NASTRAN Displacement Extractor")
        self.root.resizable(True, True)
        self.root.minsize(750, 520)

        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}

        # --- Dosya seçimi ---
        file_frame = ttk.LabelFrame(self.root, text="Sonuç Dosyası")
        file_frame.pack(fill="x", **pad)

        self.file_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.file_var, width=70).pack(
            side="left", fill="x", expand=True, padx=(8, 4), pady=6
        )
        ttk.Button(file_frame, text="Gözat...", command=self._browse_file).pack(
            side="left", padx=(0, 8), pady=6
        )

        # --- Giriş türü seçimi ---
        type_frame = ttk.LabelFrame(self.root, text="Giriş Türü")
        type_frame.pack(fill="x", **pad)

        self.input_type = tk.StringVar(value="node")
        ttk.Radiobutton(
            type_frame, text="Node ID", variable=self.input_type,
            value="node", command=self._on_input_type_change
        ).pack(side="left", padx=12, pady=6)
        ttk.Radiobutton(
            type_frame, text="Prop ID", variable=self.input_type,
            value="prop", command=self._on_input_type_change
        ).pack(side="left", padx=4, pady=6)

        # --- BDF dosyası (sadece Prop ID modunda görünür) ---
        self.bdf_frame = ttk.LabelFrame(self.root, text="BDF Dosyası")
        self.bdf_var = tk.StringVar()
        bdf_row = ttk.Frame(self.bdf_frame)
        bdf_row.pack(fill="x", padx=8, pady=6)
        ttk.Entry(bdf_row, textvariable=self.bdf_var, width=60).pack(
            side="left", fill="x", expand=True, padx=(0, 4)
        )
        ttk.Button(bdf_row, text="Gözat...", command=self._browse_bdf).pack(side="left")

        # --- ID listesi (Excel / CSV) ---
        self.node_frame = ttk.LabelFrame(self.root, text="Node ID Listesi (Excel / CSV)")
        self.node_frame.pack(fill="x", **pad)

        ttk.Label(
            self.node_frame,
            text=".xlsx, .xlsm, .csv — ilk sütun, başlık varsa otomatik atlanır",
            foreground="gray",
        ).pack(anchor="w", padx=8, pady=(4, 0))

        excel_row = ttk.Frame(self.node_frame)
        excel_row.pack(fill="x", padx=8, pady=(2, 4))

        self.excel_var = tk.StringVar()
        ttk.Entry(excel_row, textvariable=self.excel_var, width=60).pack(
            side="left", fill="x", expand=True, padx=(0, 4)
        )
        ttk.Button(excel_row, text="Gözat...", command=self._browse_excel).pack(side="left")

        self.node_info_var = tk.StringVar(value="Henüz dosya seçilmedi.")
        ttk.Label(self.node_frame, textvariable=self.node_info_var, foreground="gray").pack(
            anchor="w", padx=8, pady=(0, 6)
        )

        self._node_ids: List[int] = []
        self._node_to_prop: dict = {}
        self._base_prop_dims: dict = {}
        self._last_results: Dict = {}

        # --- Çalıştır butonu + durum ---
        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(fill="x", padx=10, pady=4)

        self.run_btn = ttk.Button(ctrl_frame, text="Çalıştır", command=self._run)
        self.run_btn.pack(side="left")

        self.export_btn = ttk.Button(ctrl_frame, text="Excel'e Aktar", command=self._export_excel)
        self.export_btn.pack(side="left", padx=6)

        # Sonuç türü (sadece Prop ID modunda görünür)
        self.result_type = tk.StringVar(value="absolute")
        self.result_type_frame = ttk.Frame(ctrl_frame)
        ttk.Label(self.result_type_frame, text="Sonuç:").pack(side="left")
        ttk.Radiobutton(
            self.result_type_frame, text="Mutlak", variable=self.result_type,
            value="absolute"
        ).pack(side="left", padx=(4, 0))
        ttk.Radiobutton(
            self.result_type_frame, text="Relative", variable=self.result_type,
            value="relative"
        ).pack(side="left", padx=4)

        self.add100_var = tk.BooleanVar(value=False)
        self.add100_cb = ttk.Checkbutton(
            ctrl_frame, text="+100mm Panel Length & Width",
            variable=self.add100_var, command=self._on_add100_toggle,
        )
        self.add100_cb.pack(side="left", padx=10)

        self.status_var = tk.StringVar(value="Hazır.")
        ttk.Label(ctrl_frame, textvariable=self.status_var, foreground="gray").pack(
            side="left", padx=12
        )

        # --- Sonuç tablosu ---
        result_frame = ttk.LabelFrame(self.root, text="Sonuçlar")
        result_frame.pack(fill="both", expand=True, **pad)

        self.tree = ttk.Treeview(result_frame, columns=_ALL_COLS, show="headings")
        self.tree["displaycolumns"] = _DISPLAY_ABS_NODE

        col_widths = {
            "Subcase": 70, "Prop": 80, "Length": 100, "Width": 100,
            "Node": 80, "T1": 110, "T2": 110, "T3": 110, "Resultant": 110,
            "Max T1": 100, "Min T1": 100, "Max T2": 100, "Min T2": 100,
            "Max T3": 100, "Min T3": 100, "Max Res": 100, "Min Res": 100,
            "Status": 70,
        }
        for col in _ALL_COLS:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=col_widths[col], anchor="center")

        vsb = ttk.Scrollbar(result_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(result_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        result_frame.grid_rowconfigure(0, weight=1)
        result_frame.grid_columnconfigure(0, weight=1)

        # Subcase grupları için renk etiketleri
        self.tree.tag_configure("odd", background="#f5f5f5")
        self.tree.tag_configure("even", background="#ffffff")
        self.tree.tag_configure("fail_odd", background="#ffcccc")
        self.tree.tag_configure("fail_even", background="#ffdddd")

    def _on_input_type_change(self):
        if self.input_type.get() == "prop":
            self.bdf_frame.pack(fill="x", padx=10, pady=5, before=self.node_frame)
            self.node_frame.configure(text="Prop ID Listesi (Excel / CSV)")
            self.result_type_frame.pack(side="left", padx=12)
            self.tree["displaycolumns"] = _DISPLAY_ABS_PROP
        else:
            self.bdf_frame.pack_forget()
            self.node_frame.configure(text="Node ID Listesi (Excel / CSV)")
            self.result_type_frame.pack_forget()
            self.result_type.set("absolute")
            self.tree["displaycolumns"] = _DISPLAY_ABS_NODE
        self._node_ids = []
        self._node_to_prop = {}
        self._base_prop_dims = {}
        self._last_results = {}
        self.add100_var.set(False)
        self.node_info_var.set("Henüz dosya seçilmedi.")
        self.excel_var.set("")

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Sonuç dosyası seç",
            filetypes=[
                ("NASTRAN Sonuç Dosyaları", "*.op2 *.h5 *.hdf5"),
                ("OP2 Dosyaları", "*.op2"),
                ("HDF5 Dosyaları", "*.h5 *.hdf5"),
                ("Tüm Dosyalar", "*.*"),
            ],
        )
        if path:
            self.file_var.set(path)

    def _browse_bdf(self):
        path = filedialog.askopenfilename(
            title="BDF dosyası seç",
            filetypes=[
                ("BDF Dosyaları", "*.bdf *.dat *.nas"),
                ("Tüm Dosyalar", "*.*"),
            ],
        )
        if path:
            self.bdf_var.set(path)

    def _browse_excel(self):
        path = filedialog.askopenfilename(
            title="Node ID listesi içeren dosyayı seç",
            filetypes=[
                ("Desteklenen Dosyalar", "*.xlsx *.xlsm *.csv"),
                ("Excel Dosyaları", "*.xlsx *.xlsm"),
                ("CSV Dosyaları", "*.csv"),
                ("Tüm Dosyalar", "*.*"),
            ],
        )
        if not path:
            return
        self.excel_var.set(path)
        try:
            self._node_ids = _read_node_ids_from_file(path)
            kind = "prop" if self.input_type.get() == "prop" else "node"
            self.node_info_var.set(f"{len(self._node_ids)} {kind} ID yüklendi.")
        except Exception as e:
            self._node_ids = []
            self.node_info_var.set("Yükleme hatası!")
            messagebox.showerror("Dosya Okuma Hatası", str(e))

    def _run(self):
        filepath = self.file_var.get().strip()

        if not filepath:
            messagebox.showwarning("Eksik Bilgi", "Lütfen bir sonuç dosyası seçin.")
            return

        if not self._node_ids:
            kind = "prop" if self.input_type.get() == "prop" else "node"
            messagebox.showwarning("Eksik Bilgi", f"Lütfen {kind} ID listesi içeren bir Excel/CSV dosyası seçin.")
            return

        if self.input_type.get() == "prop":
            bdf_path = self.bdf_var.get().strip()
            if not bdf_path:
                messagebox.showwarning("Eksik Bilgi", "Lütfen BDF dosyasını seçin.")
                return

        self.run_btn.config(state="disabled")
        self.status_var.set("Okunuyor...")
        self._clear_table()

        if self.input_type.get() == "prop":
            threading.Thread(
                target=self._run_worker_prop,
                args=(filepath, self.bdf_var.get().strip(), list(self._node_ids)),
                daemon=True,
            ).start()
        else:
            threading.Thread(
                target=self._run_worker,
                args=(filepath, list(self._node_ids)),
                daemon=True,
            ).start()

    def _run_worker(self, filepath: str, node_ids: List[int]):
        try:
            results = extract_displacements(filepath, node_ids)
            self.root.after(0, self._populate_table, results)
        except Exception as e:
            self.root.after(0, self._show_error, str(e))

    def _run_worker_prop(self, filepath: str, bdf_path: str, prop_ids: List[int]):
        try:
            self.root.after(0, lambda: self.status_var.set("BDF okunuyor..."))
            node_ids, node_to_prop, prop_dims = _get_nodes_from_props(bdf_path, prop_ids)
            self._node_to_prop = node_to_prop
            self._base_prop_dims = prop_dims
            self.root.after(0, lambda: self.status_var.set(f"{len(node_ids)} node bulundu, sonuçlar okunuyor..."))
            results = extract_displacements(filepath, node_ids)
            self.root.after(0, self._populate_table, results)
        except Exception as e:
            self.root.after(0, self._show_error, str(e))

    def _clear_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

    def _compute_relative(self, results: Dict) -> Dict:
        """Her prop için rölatif displacement özetini hesaplar.

        Referans: prop içindeki min Resultant'lı node.
        Dönüş: {subcase_id: {prop_id: {MaxT1, MinT1, MaxT2, MinT2, MaxT3, MinT3, MaxRes, MinRes}}}
        """
        rel: Dict = {}
        for subcase_id, node_data in results.items():
            prop_groups: Dict = {}
            for nid, d in node_data.items():
                pid = self._node_to_prop.get(nid)
                if pid is None:
                    continue
                prop_groups.setdefault(pid, []).append(d)

            rel[subcase_id] = {}
            for pid, entries in prop_groups.items():
                ref = min(entries, key=lambda e: e["Resultant"])
                rels = []
                for e in entries:
                    rt1 = e["T1"] - ref["T1"]
                    rt2 = e["T2"] - ref["T2"]
                    rt3 = e["T3"] - ref["T3"]
                    rels.append({
                        "T1": rt1, "T2": rt2, "T3": rt3,
                        "Res": math.sqrt(rt1**2 + rt2**2 + rt3**2),
                    })
                rel[subcase_id][pid] = {
                    "MaxT1":  max(r["T1"]  for r in rels),
                    "MinT1":  min(r["T1"]  for r in rels),
                    "MaxT2":  max(r["T2"]  for r in rels),
                    "MinT2":  min(r["T2"]  for r in rels),
                    "MaxT3":  max(r["T3"]  for r in rels),
                    "MinT3":  min(r["T3"]  for r in rels),
                    "MaxRes": max(r["Res"] for r in rels),
                    "MinRes": min(r["Res"] for r in rels),
                }
        return rel

    def _effective_dims(self) -> dict:
        if self.add100_var.get():
            return {pid: (l + 100.0, w + 100.0) for pid, (l, w) in self._base_prop_dims.items()}
        return self._base_prop_dims

    def _on_add100_toggle(self):
        if not self._base_prop_dims or not self._last_results:
            return
        self._populate_table(self._last_results)

    def _populate_table(self, results: Dict):
        self._clear_table()
        if results:
            self._last_results = results

        if not results:
            self.status_var.set("Sonuç bulunamadı.")
            self.run_btn.config(state="normal")
            return

        row_count = 0
        warnings = []
        is_prop = self.input_type.get() == "prop"
        is_rel = is_prop and self.result_type.get() == "relative"

        if is_rel:
            self.tree["displaycolumns"] = _DISPLAY_REL_PROP
            rel = self._compute_relative(results)
            for subcase_id in sorted(rel):
                for pid in sorted(rel[subcase_id]):
                    d = rel[subcase_id][pid]
                    length_val, width_val = self._effective_dims().get(pid, ("", ""))
                    length_str = f"{length_val:.3f}" if isinstance(length_val, float) else ""
                    width_str = f"{width_val:.3f}" if isinstance(width_val, float) else ""
                    status = _fail_pass(d["MaxRes"], length_val) if isinstance(length_val, float) else "-"
                    tag = ("fail_odd" if row_count % 2 else "fail_even") if status == "FAIL" else ("odd" if row_count % 2 else "even")
                    self.tree.insert(
                        "", "end",
                        values=(
                            subcase_id, pid, length_str, width_str, "",
                            "", "", "", "",
                            f"{d['MaxT1']:.3f}", f"{d['MinT1']:.3f}",
                            f"{d['MaxT2']:.3f}", f"{d['MinT2']:.3f}",
                            f"{d['MaxT3']:.3f}", f"{d['MinT3']:.3f}",
                            f"{d['MaxRes']:.3f}", f"{d['MinRes']:.3f}",
                            status,
                        ),
                        tags=(tag,),
                    )
                    row_count += 1
        else:
            self.tree["displaycolumns"] = _DISPLAY_ABS_PROP if is_prop else _DISPLAY_ABS_NODE
            for subcase_id in sorted(results):
                node_data = results[subcase_id]
                if not node_data:
                    warnings.append(f"Subcase {subcase_id}: hiç node bulunamadı.")
                    continue
                for nid in sorted(node_data):
                    d = node_data[nid]
                    if is_prop:
                        prop_val = self._node_to_prop.get(nid, "")
                        length_val, width_val = self._effective_dims().get(prop_val, ("", ""))
                        length_str = f"{length_val:.3f}" if isinstance(length_val, float) else ""
                        width_str = f"{width_val:.3f}" if isinstance(width_val, float) else ""
                        status = _fail_pass(d["Resultant"], length_val) if isinstance(length_val, float) else "-"
                    else:
                        prop_val = length_str = width_str = status = ""
                    tag = ("fail_odd" if row_count % 2 else "fail_even") if status == "FAIL" else ("odd" if row_count % 2 else "even")
                    self.tree.insert(
                        "", "end",
                        values=(
                            subcase_id, prop_val, length_str, width_str, nid,
                            f"{d['T1']:.3f}", f"{d['T2']:.3f}", f"{d['T3']:.3f}",
                            f"{d['Resultant']:.3f}",
                            "", "", "", "", "", "", "", "",
                            status,
                        ),
                        tags=(tag,),
                    )
                    row_count += 1

        status = f"{row_count} satır gösteriliyor."
        if warnings:
            status += "  Uyarı: " + " | ".join(warnings)
        self.status_var.set(status)
        self.run_btn.config(state="normal")

    def _export_excel(self):
        rows = [self.tree.item(iid)["values"] for iid in self.tree.get_children()]
        if not rows:
            messagebox.showwarning("Dışa Aktar", "Aktarılacak sonuç yok.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel Dosyası", "*.xlsx"), ("Tüm Dosyalar", "*.*")],
            title="Sonuçları kaydet",
        )
        if not path:
            return
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Displacement"
        headers = list(self.tree["displaycolumns"])
        all_cols = list(self.tree["columns"])
        col_indices = [all_cols.index(c) for c in headers]
        ws.append(headers)
        for row in rows:
            ws.append([row[i] for i in col_indices])
        wb.save(path)
        messagebox.showinfo("Dışa Aktar", f"Kaydedildi:\n{path}")

    def _show_error(self, message: str):
        self.status_var.set("Hata oluştu.")
        self.run_btn.config(state="normal")
        messagebox.showerror("Hata", message)


# ---------------------------------------------------------------------------
# CLI yardımcısı
# ---------------------------------------------------------------------------

def _parse_args():
    parser = argparse.ArgumentParser(
        description="NASTRAN OP2/H5 dosyasından displacement sonuçlarını çeker."
    )
    parser.add_argument("--file", "-f", required=True, help="Sonuç dosyası yolu (.op2 veya .h5/.hdf5)")
    parser.add_argument("--nodes", "-n", nargs="+", type=int, required=True,
                        help="Sorgulanacak node ID listesi")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Giriş noktası
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    root = tk.Tk()
    app = LoadExtractionApp(root)
    root.mainloop()
