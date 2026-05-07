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
    python displacement_extractor.py --file results.h5 --nodes 101 102 103
"""

import argparse
import math
import os
from typing import Dict, List


def _read_op2(filepath: str, node_ids: List[int]) -> Dict:
    """OP2 dosyasından displacement verisi okur."""
    try:
        from pyNastran.op2.op2 import OP2
    except ImportError:
        raise ImportError(
            "pyNastran kurulu değil. Kurmak için: pip install pyNastran"
        )

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
                resultant = math.sqrt(t1**2 + t2**2 + t3**2)
                subcase_results[nid] = {
                    "T1": t1,
                    "T2": t2,
                    "T3": t3,
                    "Resultant": resultant,
                }

        missing = node_set - set(subcase_results.keys())
        if missing:
            print(f"  [Uyarı] Subcase {subcase_id}: şu node'lar bulunamadı: {sorted(missing)}")

        results[subcase_id] = subcase_results

    return results


def _read_h5(filepath: str, node_ids: List[int]) -> Dict:
    """NASTRAN HDF5 dosyasından displacement verisi okur.

    Beklenen HDF5 yapısı (MSC/NX Nastran HDF5 çıktısı):
        /NASTRAN/RESULT/NODAL/DISPLACEMENT/
            ID        -> node ID dizisi
            T1, T2, T3 -> displacement bileşenleri
            DOMAIN_ID -> her kaydın hangi domain'e ait olduğu

        /NASTRAN/RESULT/DOMAINS/
            ID      -> domain ID
            SUBCASE -> subcase numarası
    """
    try:
        import h5py
        import numpy as np
    except ImportError:
        raise ImportError(
            "h5py veya numpy kurulu değil. Kurmak için: pip install h5py numpy"
        )

    node_set = set(node_ids)
    results = {}

    with h5py.File(filepath, "r") as f:
        # Domain → Subcase eşlemesini oluştur
        domains_path = "/NASTRAN/RESULT/DOMAINS"
        if domains_path not in f:
            raise ValueError(
                "HDF5 dosyasında /NASTRAN/RESULT/DOMAINS bulunamadı. "
                "Dosyanın NASTRAN HDF5 formatında olduğundan emin olun."
            )

        domain_ids = f[domains_path]["ID"][:]
        subcases = f[domains_path]["SUBCASE"][:]
        domain_to_subcase = dict(zip(domain_ids.tolist(), subcases.tolist()))

        # Displacement verisini oku
        disp_path = "/NASTRAN/RESULT/NODAL/DISPLACEMENT"
        if disp_path not in f:
            raise ValueError(
                "HDF5 dosyasında displacement sonucu bulunamadı. "
                f"Beklenen yol: {disp_path}"
            )

        disp_grp = f[disp_path]
        file_node_ids = disp_grp["ID"][:]
        domain_id_arr = disp_grp["DOMAIN_ID"][:]
        t1_arr = disp_grp["T1"][:]
        t2_arr = disp_grp["T2"][:]
        t3_arr = disp_grp["T3"][:]

        # Her unique domain (= subcase) için filtrele
        unique_domains = np.unique(domain_id_arr)
        for domain_id in unique_domains:
            subcase_id = domain_to_subcase.get(int(domain_id), int(domain_id))
            mask = domain_id_arr == domain_id

            d_nodes = file_node_ids[mask]
            d_t1 = t1_arr[mask]
            d_t2 = t2_arr[mask]
            d_t3 = t3_arr[mask]

            subcase_results = {}
            for i, nid in enumerate(d_nodes.tolist()):
                if nid in node_set:
                    t1 = float(d_t1[i])
                    t2 = float(d_t2[i])
                    t3 = float(d_t3[i])
                    resultant = math.sqrt(t1**2 + t2**2 + t3**2)
                    subcase_results[nid] = {
                        "T1": t1,
                        "T2": t2,
                        "T3": t3,
                        "Resultant": resultant,
                    }

            missing = node_set - set(subcase_results.keys())
            if missing:
                print(f"  [Uyarı] Subcase {subcase_id}: şu node'lar bulunamadı: {sorted(missing)}")

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
        raise ValueError(
            f"Desteklenmeyen dosya uzantısı: '{ext}'. "
            "Lütfen .op2 veya .h5/.hdf5 dosyası kullanın."
        )


def print_results(results: Dict) -> None:
    """Displacement sonuçlarını tablo formatında ekrana basar."""
    if not results:
        print("Sonuç bulunamadı.")
        return

    col_w = 14
    header = (
        f"  {'Node':>8}  "
        f"{'T1':>{col_w}}  "
        f"{'T2':>{col_w}}  "
        f"{'T3':>{col_w}}  "
        f"{'Resultant':>{col_w}}"
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
                f"{d['T1']:>{col_w}.6e}  "
                f"{d['T2']:>{col_w}.6e}  "
                f"{d['T3']:>{col_w}.6e}  "
                f"{d['Resultant']:>{col_w}.6e}"
            )


def _parse_args():
    parser = argparse.ArgumentParser(
        description="NASTRAN OP2/H5 dosyasından displacement sonuçlarını çeker."
    )
    parser.add_argument(
        "--file", "-f",
        required=True,
        help="Sonuç dosyası yolu (.op2 veya .h5/.hdf5)",
    )
    parser.add_argument(
        "--nodes", "-n",
        nargs="+",
        type=int,
        required=True,
        help="Sorgulanacak node ID listesi (boşlukla ayrılmış)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    print(f"Dosya okunuyor: {args.file}")
    print(f"Sorgulanan node'lar: {args.nodes}")

    results = extract_displacements(args.file, args.nodes)
    print_results(results)
