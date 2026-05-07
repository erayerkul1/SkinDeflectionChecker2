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
import math
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List


# ---------------------------------------------------------------------------
# Çekirdek okuma fonksiyonları
# ---------------------------------------------------------------------------

def _read_op2(filepath: str, node_ids: List[int]) -> Dict:
    """OP2 dosyasından displacement verisi okur."""
    try:
        from pyNastran.op2.op2 import OP2
    except ImportError:
        raise ImportError("pyNastran kurulu değil. Kurmak için: pip install pyNastran")

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
    try:
        import h5py
        import numpy as np
    except ImportError:
        raise ImportError("h5py veya numpy kurulu değil. Kurmak için: pip install h5py numpy")

    node_set = set(node_ids)
    results = {}

    with h5py.File(filepath, "r") as f:
        domains_path = "/NASTRAN/RESULT/DOMAINS"
        if domains_path not in f:
            raise ValueError("HDF5 dosyasında /NASTRAN/RESULT/DOMAINS bulunamadı.")

        domain_ids = f[domains_path]["ID"][:]
        subcases = f[domains_path]["SUBCASE"][:]
        domain_to_subcase = dict(zip(domain_ids.tolist(), subcases.tolist()))

        disp_path = "/NASTRAN/RESULT/NODAL/DISPLACEMENT"
        if disp_path not in f:
            raise ValueError(f"HDF5 dosyasında displacement sonucu bulunamadı. Beklenen: {disp_path}")

        disp_grp = f[disp_path]
        file_node_ids = disp_grp["ID"][:]
        domain_id_arr = disp_grp["DOMAIN_ID"][:]
        t1_arr = disp_grp["T1"][:]
        t2_arr = disp_grp["T2"][:]
        t3_arr = disp_grp["T3"][:]

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
                f"{d['T1']:>{col_w}.6e}  {d['T2']:>{col_w}.6e}  "
                f"{d['T3']:>{col_w}.6e}  {d['Resultant']:>{col_w}.6e}"
            )


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

        # --- Node ID girişi ---
        node_frame = ttk.LabelFrame(self.root, text="Node ID Listesi")
        node_frame.pack(fill="x", **pad)

        ttk.Label(
            node_frame,
            text="Boşluk veya virgülle ayrılmış node ID'leri girin (örn: 101 102 103)",
            foreground="gray",
        ).pack(anchor="w", padx=8, pady=(4, 0))

        self.node_var = tk.StringVar()
        ttk.Entry(node_frame, textvariable=self.node_var, width=80).pack(
            fill="x", padx=8, pady=(2, 8)
        )

        # --- Çalıştır butonu + durum ---
        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(fill="x", padx=10, pady=4)

        self.run_btn = ttk.Button(ctrl_frame, text="Çalıştır", command=self._run)
        self.run_btn.pack(side="left")

        self.status_var = tk.StringVar(value="Hazır.")
        ttk.Label(ctrl_frame, textvariable=self.status_var, foreground="gray").pack(
            side="left", padx=12
        )

        # --- Sonuç tablosu ---
        result_frame = ttk.LabelFrame(self.root, text="Sonuçlar")
        result_frame.pack(fill="both", expand=True, **pad)

        columns = ("Subcase", "Node", "T1", "T2", "T3", "Resultant")
        self.tree = ttk.Treeview(result_frame, columns=columns, show="headings")

        col_widths = {"Subcase": 70, "Node": 80, "T1": 130, "T2": 130, "T3": 130, "Resultant": 130}
        for col in columns:
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

    def _run(self):
        filepath = self.file_var.get().strip()
        raw_nodes = self.node_var.get().strip()

        if not filepath:
            messagebox.showwarning("Eksik Bilgi", "Lütfen bir sonuç dosyası seçin.")
            return

        if not raw_nodes:
            messagebox.showwarning("Eksik Bilgi", "Lütfen en az bir node ID girin.")
            return

        try:
            node_ids = [int(x) for x in raw_nodes.replace(",", " ").split()]
        except ValueError:
            messagebox.showerror("Hata", "Node ID'leri geçersiz. Lütfen sadece tam sayı girin.")
            return

        self.run_btn.config(state="disabled")
        self.status_var.set("Okunuyor...")
        self._clear_table()

        threading.Thread(target=self._run_worker, args=(filepath, node_ids), daemon=True).start()

    def _run_worker(self, filepath: str, node_ids: List[int]):
        try:
            results = extract_displacements(filepath, node_ids)
            self.root.after(0, self._populate_table, results)
        except Exception as e:
            self.root.after(0, self._show_error, str(e))

    def _clear_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

    def _populate_table(self, results: Dict):
        self._clear_table()

        if not results:
            self.status_var.set("Sonuç bulunamadı.")
            self.run_btn.config(state="normal")
            return

        row_count = 0
        warnings = []

        for subcase_id in sorted(results):
            node_data = results[subcase_id]
            if not node_data:
                warnings.append(f"Subcase {subcase_id}: hiç node bulunamadı.")
                continue

            for nid in sorted(node_data):
                d = node_data[nid]
                tag = "odd" if row_count % 2 else "even"
                self.tree.insert(
                    "",
                    "end",
                    values=(
                        subcase_id,
                        nid,
                        f"{d['T1']:.6e}",
                        f"{d['T2']:.6e}",
                        f"{d['T3']:.6e}",
                        f"{d['Resultant']:.6e}",
                    ),
                    tags=(tag,),
                )
                row_count += 1

        status = f"{row_count} satır gösteriliyor."
        if warnings:
            status += "  Uyarı: " + " | ".join(warnings)
        self.status_var.set(status)
        self.run_btn.config(state="normal")

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
