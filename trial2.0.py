#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ensayo Triaxial CD / CU  -  Aplicación GUI (Tkinter)

Novedades:
  * Interfaz redimensionable (se adapta a la pantalla) con pestañas.
  * Módulo de elasticidad secante E50 / tangente (inicial y al 50 %).
  * Módulo de corte G y relación de Poisson ν.
  * Tipo de material según SUCS (Norma Técnica E.050, Perú).
  * Reporte PDF profesional con memoria de cálculo manual paso a paso,
    fórmulas desglosadas, referencias normativas y gráficas de alta resolución.

Requisitos:
    pip install -r requirements.txt
"""
import os
import re
import time
import tempfile
import unicodedata
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk


# ======================================================================
#  TABLA SUCS (Norma E.050 - Suelos y Cimentaciones, Perú)
#  código: (descripción, φ mínimo referencial, φ máximo referencial)
# ======================================================================
SUCS = {
    "GW": ("Grava bien graduada, con pocos o ningún fino", 33, 40),
    "GP": ("Grava mal graduada, con pocos o ningún fino", 32, 38),
    "GM": ("Grava limosa", 30, 36),
    "GC": ("Grava arcillosa", 28, 34),
    "SW": ("Arena bien graduada, con pocos o ningún fino", 31, 38),
    "SP": ("Arena mal graduada, con pocos o ningún fino", 30, 36),
    "SM": ("Arena limosa", 28, 34),
    "SC": ("Arena arcillosa", 26, 32),
    "ML": ("Limo de baja plasticidad", 25, 32),
    "CL": ("Arcilla de baja plasticidad", 20, 28),
    "OL": ("Limo / arcilla orgánica de baja plasticidad", 18, 25),
    "MH": ("Limo de alta plasticidad", 20, 26),
    "CH": ("Arcilla de alta plasticidad", 17, 25),
    "OH": ("Arcilla / limo orgánico de alta plasticidad", 15, 22),
    "Pt": ("Turba y suelos altamente orgánicos", None, None),
}
SUCS_ITEMS = ["(sin especificar)"] + [f"{k} – {v[0]}" for k, v in SUCS.items()]

MODES = {"Secante al 50 % (E50)": "sec",
         "Tangente inicial (Ei)": "ini",
         "Tangente al 50 % (Et50)": "tan"}
MODE_NAME = {"sec": "secante al 50 % de la carga máxima (E50)",
             "ini": "tangente inicial (Ei)",
             "tan": "tangente al 50 % de la carga máxima (Et50)"}


def sucs_key(txt):
    k = str(txt).split(" – ")[0].strip()
    return k if k in SUCS else None


# ======================================================================
#  LECTURA ROBUSTA DE DATOS
# ======================================================================
GREEK = {"ε": "e", "σ": "s", "Δ": "d", "δ": "d", "φ": "phi"}

SYN = {
    "e1": ["e1", "e1%", "ea", "eaxial", "epsilon1", "epsilona", "def", "deformacion",
           "deformacionaxial", "deformaxial", "defaxial", "strain", "axialstrain",
           "eps1", "epsilon"],
    "desv": ["desv", "desviador", "esfuerzodesviador", "esfdesviador", "deviator",
             "deviatorstress", "sigma1sigma3", "s1s3", "qdesv", "ds", "dsigma",
             "ds13", "s1s3kpa", "sd"],
    "u": ["u", "uw", "pwp", "pp", "porepressure", "presionporos", "presiondeporos",
          "presionporo", "presiondeporo", "ucorr", "udelta", "deltau", "du", "pporos",
          "presionagua", "presiondeagua"],
    "pc": ["pc", "s3", "sigma3", "confinamiento", "presionconfinante",
           "presiondeconfinamiento", "cellpressure", "confining", "cp", "sc",
           "esfuerzoconfinante"],
    # deformación volumétrica (% , contracción positiva)
    "ev": ["ev", "evol", "epsilonv", "epsv", "deformacionvolumetrica", "defvol",
           "defvolumetrica", "volumetricstrain", "volstrain", "dvv", "dvv0",
           "cambiovolumetrico"],
}


def norm(txt):
    t = str(txt).strip()
    for g, r in GREEK.items():
        t = t.replace(g, r)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9%]", "", t)


def strip_units(txt):
    t = re.sub(r"[\(\[\{].*?[\)\]\}]", "", str(txt))
    return norm(t)


def match_column(header):
    full, base = norm(header), strip_units(header)
    for key, names in SYN.items():
        if full in names or base in names:
            return key
    # heurísticas (volumétrica ANTES que deformación)
    for key, frag in (("ev", "volum"), ("desv", "desv"), ("e1", "deform"), ("u", "poro")):
        if frag in full:
            return key
    return None


def to_num(series):
    if not pd.api.types.is_numeric_dtype(series):
        series = series.astype(str).str.replace(",", ".", regex=False).str.strip()
    return pd.to_numeric(series, errors="coerce")


def find_header_row(raw, max_scan=25):
    best, best_hits = 0, -1
    for i in range(min(max_scan, len(raw))):
        hits = len({match_column(v) for v in raw.iloc[i].tolist()
                    if pd.notna(v) and match_column(v)})
        if hits > best_hits:
            best, best_hits = i, hits
        if hits >= 3:
            break
    return best, best_hits


def clean_table(raw):
    raw = raw.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    if raw.empty:
        return None, "hoja vacía"
    hrow, hits = find_header_row(raw)
    if hits < 2:
        return None, "no se encontraron encabezados reconocibles"
    headers = raw.iloc[hrow].tolist()
    body = raw.iloc[hrow + 1:].reset_index(drop=True)

    cols = {}
    for idx, h in enumerate(headers):
        if pd.isna(h):
            continue
        key = match_column(h)
        if key and key not in cols:
            cols[key] = idx
    if "e1" not in cols or "desv" not in cols:
        faltan = [k for k in ("e1", "desv") if k not in cols]
        return None, f"faltan columnas: {', '.join(faltan)}"

    out = pd.DataFrame({k: to_num(body.iloc[:, i]) for k, i in cols.items()})
    out = out.dropna(subset=["e1", "desv"])
    sub = ["e1", "pc"] if "pc" in out.columns else ["e1"]
    out = out.sort_values("e1", kind="stable").drop_duplicates(sub, keep="last")
    out = out.reset_index(drop=True)
    if len(out) < 2:
        return None, "muy pocos datos numéricos"
    return out, None


def guess_pc(text):
    nums = re.findall(r"\d+(?:[.,]\d+)?", str(text))
    return float(nums[-1].replace(",", ".")) if nums else None


def guess_type(text):
    t = norm(text)
    if re.search(r"cu|isotropico|undrained|nodren", t) and "cd" not in t:
        return "CU"
    if "cd" in t or "drenado" in t:
        return "CD"
    return None


def read_csv_smart(path):
    best, best_score = None, -1
    for sep in (";", "\t", ",", "|"):
        try:
            raw = pd.read_csv(path, header=None, sep=sep, dtype=str, engine="python",
                              encoding_errors="replace", skip_blank_lines=True)
        except Exception:
            continue
        r, hits = find_header_row(raw)
        score = hits * 100 + raw.shape[1]
        if hits >= 2 and score > best_score:
            best, best_score = raw, score
    if best is None:
        raise ValueError("No se pudo interpretar el CSV (separador/encabezados).")
    return best


def read_tests(path):
    ext = os.path.splitext(path)[1].lower()
    fname = os.path.splitext(os.path.basename(path))[0]
    tests, warns = [], []
    tipo = guess_type(fname)

    if ext in (".xlsx", ".xlsm", ".xls"):
        sheets = pd.read_excel(path, sheet_name=None, header=None)
        sources = list(sheets.items())
    elif ext in (".csv", ".txt"):
        sources = [(fname, read_csv_smart(path))]
    else:
        raise ValueError(f"Formato no soportado: {ext}")

    for name, raw in sources:
        df, err = clean_table(raw)
        if df is None:
            warns.append(f"Hoja '{name}' ignorada: {err}.")
            continue
        tipo = tipo or guess_type(name)
        if "pc" in df.columns and df["pc"].notna().any():
            for pc, g in df.groupby("pc"):
                g = g.drop(columns="pc").sort_values("e1").reset_index(drop=True)
                tests.append({"name": f"{name} [σ3={pc:g}]", "pc": float(pc), "df": g})
            continue
        tests.append({"name": str(name), "pc": guess_pc(name), "df": df})

    if not tests:
        raise ValueError("No se pudo leer ningún ensayo válido del archivo.\n" +
                         "\n".join(warns))
    return tests, warns, tipo


# ======================================================================
#  CÁLCULO
# ======================================================================
def _first_cross(e, s, level):
    """Deformación (%) donde la curva pre-pico alcanza 'level' (interpolado)."""
    for i in range(len(s)):
        if s[i] >= level:
            if i == 0:
                return float(e[0])
            s0, s1 = s[i - 1], s[i]
            if s1 == s0:
                return float(e[i])
            return float(e[i - 1] + (level - s0) * (e[i] - e[i - 1]) / (s1 - s0))
    return float("nan")


def calc_moduli(df, tipo, mode, nu_assumed):
    """E secante / tangente, ν y G.  e1 y ev vienen en %, desv en kPa.
       E = Δσd / Δε1  (ε1 en fracción)."""
    nan = float("nan")
    e = df["e1"].values.astype(float)
    s = df["desv"].values.astype(float)
    imax = int(np.argmax(s))
    smax = float(s[imax])
    s50 = 0.5 * smax
    pe, ps = e[:imax + 1], s[:imax + 1]
    e50 = _first_cross(pe, ps, s50)
    cross_idx = next((i for i, value in enumerate(ps) if value >= s50), None)
    if cross_idx is None:
        half_bracket = None
    elif cross_idx == 0:
        half_bracket = (float(pe[0]), float(ps[0]), float(pe[0]), float(ps[0]))
    else:
        half_bracket = (
            float(pe[cross_idx - 1]), float(ps[cross_idx - 1]),
            float(pe[cross_idx]), float(ps[cross_idx]),
        )

    def idx_window(lo, hi):
        m = np.where((ps >= lo * smax) & (ps <= hi * smax))[0]
        if len(m) < 2:                                   # respaldo: 2 puntos más cercanos
            mid = 0.5 * (lo + hi) * smax
            m = np.sort(np.argsort(np.abs(ps - mid))[:2])
        return m

    def slope(idx, y):
        if len(idx) < 2 or np.ptp(pe[idx]) == 0:
            return nan
        return float(np.polyfit(pe[idx], y[idx], 1)[0])

    i_ini, i_tan = idx_window(0.0, 0.2), idx_window(0.4, 0.6)
    fallback_ini = int(np.sum((ps >= 0.0 * smax) & (ps <= 0.2 * smax))) < 2
    fallback_tan = int(np.sum((ps >= 0.4 * smax) & (ps <= 0.6 * smax))) < 2
    E_sec = s50 / (e50 / 100) if e50 and e50 > 0 else nan
    E_ini = slope(i_ini, ps) * 100
    E_tan = slope(i_tan, ps) * 100

    has_ev = tipo == "CD" and "ev" in df.columns and df["ev"].notna().any()
    if tipo == "CU":
        nus = {k: 0.5 for k in ("sec", "ini", "tan")}
        src = "no drenado (εv = 0)"
    elif has_ev:
        ev = df["ev"].values.astype(float)[:imax + 1]
        ev50 = float(np.interp(e50, pe, ev)) if e50 > 0 else nan
        nus = {"sec": 0.5 * (1 - ev50 / e50) if e50 > 0 else nan,
               "ini": 0.5 * (1 - slope(i_ini, ev)),
               "tan": 0.5 * (1 - slope(i_tan, ev))}
        src = "calculado con εv medido"
    else:
        nus = {k: nu_assumed for k in ("sec", "ini", "tan")}
        src = "asumido (no hay columna εv)"

    Es = {"sec": E_sec, "ini": E_ini, "tan": E_tan}
    Gs = {k: Es[k] / (2 * (1 + nus[k])) for k in Es}
    def fit_details(indices, values):
        selected_e = pe[indices]
        selected_y = values[indices]
        if len(selected_e) < 2 or np.ptp(selected_e) == 0:
            return {"indices": indices.tolist(), "e": selected_e.tolist(),
                    "y": selected_y.tolist(), "slope": nan, "intercept": nan}
        fit_slope, fit_intercept = np.polyfit(selected_e, selected_y, 1)
        return {"indices": indices.tolist(), "e": selected_e.tolist(),
                "y": selected_y.tolist(), "slope": float(fit_slope),
                "intercept": float(fit_intercept)}

    out = {"smax": smax, "s50": s50, "e50": e50, "e_peak": float(e[imax]),
           "E_sec": E_sec, "E_ini": E_ini, "E_tan": E_tan,
           "nu_all": nus, "G_all": Gs, "nu_src": src, "has_ev": has_ev,
           "mode": mode, "E": Es[mode], "nu": nus[mode], "G": Gs[mode],
           "peak_index": imax, "half_bracket": half_bracket,
           "ini_fit": fit_details(i_ini, ps),
           "tan_fit": fit_details(i_tan, ps),
           "ini_fallback": fallback_ini, "tan_fallback": fallback_tan}
    if has_ev:
        out["ev50"] = ev50
        out["ini_ev_fit"] = fit_details(i_ini, ev)
        out["tan_ev_fit"] = fit_details(i_tan, ev)
    return out


def compute(tests, tipo, deform, only_phi, mode="sec", nu_assumed=0.30):
    warns = []
    p_list, q_list = [], []
    for t in tests:
        df = t["df"].copy()
        s3 = t["pc"]
        df["σ3"] = s3
        df["σ1"] = s3 + df["desv"]
        df["p"] = (df["σ1"] + df["σ3"]) / 2
        df["q"] = (df["σ1"] - df["σ3"]) / 2
        if "ev" in df.columns and df["ev"].notna().any():
            df["ev"] = df["ev"].interpolate().bfill().ffill()
        if tipo == "CD":
            df["σ'3"], df["σ'1"], df["p'"] = df["σ3"], df["σ1"], df["p"]
        else:
            if "u" not in df.columns or df["u"].isna().all():
                raise ValueError(f"El ensayo '{t['name']}' no tiene columna de "
                                 f"presión de poros (u) y se pidió tipo CU.")
            df["u"] = df["u"].interpolate().bfill().ffill()
            df["σ'3"] = df["σ3"] - df["u"]
            df["σ'1"] = df["σ1"] - df["u"]
            df["p'"] = df["p"] - df["u"]
        df["q'"] = df["q"]
        t["calc"] = df

        emin, emax = df["e1"].min(), df["e1"].max()
        d = deform
        if d > emax or d < emin:
            d = min(max(d, emin), emax)
            warns.append(f"'{t['name']}': e1={deform:g}% fuera de rango "
                         f"[{emin:g}, {emax:g}]; se usó {d:g}%.")
        t["d_used"] = d
        t["p_def"] = float(np.interp(d, df["e1"], df["p'"]))
        t["q_def"] = float(np.interp(d, df["e1"], df["q'"]))
        t["desv_def"] = float(np.interp(d, df["e1"], df["desv"]))
        t["mod"] = calc_moduli(df, tipo, mode, nu_assumed)
        if t["mod"]["nu"] > 0.5 or t["mod"]["nu"] < 0:
            warns.append(f"'{t['name']}': ν = {t['mod']['nu']:.2f} fuera de [0, 0.5]; "
                         f"revise signo de εv (contracción positiva).")
        p_list.append(t["p_def"])
        q_list.append(t["q_def"])

    if only_phi:
        p2, q2 = [0] * 10 + p_list, [0] * 10 + q_list
    else:
        p2, q2 = p_list, q_list
    if len(set(p2)) < 2:
        raise ValueError("Se necesitan al menos 2 ensayos con distinto p' para ajustar la envolvente.")
    coef = np.polyfit(p2, q2, 1)
    if abs(coef[0]) >= 1:
        warns.append("Pendiente ≥ 1: revise los datos (φ no definido).")
    phi = np.arcsin(np.clip(coef[0], -1, 1))
    c = 0.0 if only_phi else coef[1] / np.cos(phi)
    return {"phi": np.degrees(phi), "phi_rad": phi, "c": c, "coef": coef,
            "p": p_list, "q": q_list, "warns": warns, "mode": mode,
            "nu_assumed": nu_assumed, "only_phi": only_phi}


# ======================================================================
#  GRÁFICOS  (funciones reutilizadas por la GUI y por el reporte PDF)
# ======================================================================
def plot_curves(ax, tests, tipo):
    for t in tests:
        df, lab = t["calc"], f"Triaxial {tipo} - {t['pc']:g} kPa"
        ln, = ax.plot(df["e1"], df["desv"], marker="o", ms=3.5, mfc="w", lw=1, label=lab)
        m = t["mod"]
        if m["e50"] and m["e50"] > 0:
            ax.plot([0, m["e50"]], [0, m["s50"]], "--", lw=.9, color=ln.get_color())
            ax.plot(m["e50"], m["s50"], "D", ms=6, color=ln.get_color())
    ax.set(xlabel="Deformación axial ε1 (%)", ylabel="Esfuerzo desviador σd (kPa)")
    ax.grid(alpha=.5); ax.legend(framealpha=1, fontsize=8); ax.margins(0)
    ax.set_title("Esfuerzo desviador vs. deformación axial", fontsize=9)


def plot_pq(ax, tests, res, tipo):
    for t in tests:
        df = t["calc"]
        ax.plot(df["p'"], df["q'"], marker="o", ms=3.5, mfc="w", lw=1,
                label=f"Triaxial {tipo} - {t['pc']:g} kPa")
    coef = res["coef"]
    pmax = max(res["p"]) * 1.1
    ax.plot([0, pmax], [coef[1], coef[1] + pmax * coef[0]], "k", label="Envolvente Kf")
    ax.plot(res["p"], res["q"], "ks", mfc="w")
    ax.set(xlabel="p' (kPa)", ylabel="q (kPa)")
    ax.grid(alpha=.5); ax.legend(framealpha=1, fontsize=7); ax.margins(0)
    ax.set_title("Trayectoria de esfuerzos efectivos p prima vs. q", fontsize=9)


def plot_mohr(ax, tests, res):
    th = np.linspace(0, np.pi, 60)
    phi, c = res["phi_rad"], res["c"]
    for t in tests:
        ax.plot(t["p_def"] + t["q_def"] * np.cos(th), t["q_def"] * np.sin(th),
                color="LightSeaGreen")
    xmax = max(t["p_def"] + t["q_def"] for t in tests) * 1.1
    ax.plot([0, xmax], [c, c + xmax * np.tan(phi)], "k")
    ax.set_xlim(0, xmax); ax.set_ylim(bottom=0)
    ax.set(xlabel="σ' (kPa)", ylabel="τ (kPa)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(alpha=.5)
    ax.text(0.04, 0.95, f"c = {c:.1f} kPa\nφ = {res['phi']:.1f}°",
            transform=ax.transAxes, ha="left", va="top", weight="bold", fontsize=10,
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 1})
    ax.set_title("Círculos de Mohr y envolvente de falla", fontsize=9)


def plot_vol(ax, tests):
    for t in tests:
        df = t["calc"]
        if "ev" in df.columns and df["ev"].notna().any():
            ax.plot(df["e1"], df["ev"], marker="o", ms=3.5, mfc="w", lw=1,
                    label=f"σ3 = {t['pc']:g} kPa")
    ax.invert_yaxis()
    ax.set(xlabel="Deformación axial ε1 (%)",
           ylabel="Deformación volumétrica εv (%)  (+ contracción)")
    ax.grid(alpha=.5); ax.legend(framealpha=1, fontsize=8)
    ax.set_title("Deformación volumétrica vs. deformación axial", fontsize=9)


def draw(fig, tests, res, tipo):
    fig.clear()
    gs = fig.add_gridspec(2, 2)
    plot_curves(fig.add_subplot(gs[:, 0]), tests, tipo)
    plot_pq(fig.add_subplot(gs[0, 1]), tests, res, tipo)
    plot_mohr(fig.add_subplot(gs[1, 1]), tests, res)
    fig.suptitle(f"Ensayo triaxial {tipo}  –  e1 de falla = {res['deform']:g} %",
                 fontsize=11)


# ======================================================================
#  INTERPRETACIÓN (texto plano, usado en el PDF)
# ======================================================================
def rigidez(E_mpa):
    if E_mpa < 5:
        return "muy blando"
    if E_mpa < 15:
        return "blando"
    if E_mpa < 40:
        return "de rigidez media"
    if E_mpa < 100:
        return "rígido"
    return "muy rígido"


def interpret(res, tests, tipo, skey):
    phi, c = res["phi"], res["c"]
    out = []
    # resistencia
    if phi < 20:
        f = "baja"
    elif phi < 30:
        f = "moderada"
    elif phi < 36:
        f = "alta"
    else:
        f = "muy alta"
    cs = ("prácticamente nula" if c < 5 else "baja" if c < 25
          else "moderada" if c < 50 else "alta")
    ef = "efectivos " if tipo == "CU" else ""
    out.append(f"Resistencia al corte. Los parámetros {ef}obtenidos son "
               f"φ = {phi:.1f}° y c = {c:.1f} kPa. El ángulo de fricción indica una "
               f"resistencia friccionante {f} y la cohesión es {cs}. "
               + ("Se forzó c = 0 (solo φ), por lo que la envolvente pasa por el origen. "
                  if res["only_phi"] else ""))
    # SUCS
    if skey and SUCS[skey][1] is not None:
        d, lo, hi = SUCS[skey]
        if phi < lo:
            cmp = "por debajo"
        elif phi > hi:
            cmp = "por encima"
        else:
            cmp = "dentro"
        out.append(f"Material (SUCS, Norma E.050): {skey} - {d}. El rango referencial de φ "
                   f"para este grupo es {lo}° a {hi}°; el valor obtenido ({phi:.1f}°) está "
                   f"{cmp} de ese rango. Estos rangos son solo orientativos y no sustituyen "
                   f"el criterio del ingeniero ni la verificación con la norma.")
    elif skey == "Pt":
        out.append("Material: turba / suelo altamente orgánico (Pt). La E.050 lo considera "
                   "suelo no apto para cimentar sin tratamiento; los resultados del triaxial "
                   "deben usarse con mucha cautela.")
    else:
        out.append("No se especificó el tipo de material SUCS, por lo que no se comparó "
                   "el resultado con rangos típicos.")
    # rigidez
    m = res["mode"]
    Es = [t["mod"]["E"] / 1000 for t in tests]
    out.append(f"Rigidez. El módulo {MODE_NAME[m]} varía entre {min(Es):.1f} y {max(Es):.1f} MPa. "
               f"Según una escala referencial el suelo es {rigidez(float(np.mean(Es)))} "
               f"(promedio {np.mean(Es):.1f} MPa). El módulo crece con el confinamiento σ3, "
               f"por lo que debe usarse el valor que corresponda al nivel de esfuerzos de la obra.")
    # Poisson
    if tipo == "CU":
        out.append("Relación de Poisson. En el ensayo no drenado no hay cambio de volumen "
                   "(εv = 0), por lo que ν = 0.5 y G = E/3. Este E es un módulo no drenado "
                   "(Eu) y no debe usarse directamente para asentamientos drenados.")
    else:
        nus = [t["mod"]["nu"] for t in tests]
        src = tests[0]["mod"]["nu_src"]
        out.append(f"Relación de Poisson. ν varía entre {min(nus):.2f} y {max(nus):.2f} "
                   f"({src}). Valores bajos indican que la muestra se ensancha poco al "
                   f"comprimirla; valores cercanos a 0.5 indican comportamiento casi incompresible.")
    out.append("Módulo de corte. G = E / [2(1 + ν)] describe la resistencia del suelo "
               "a deformarse por esfuerzos cortantes a pequeñas y medianas deformaciones.")
    return out


# ======================================================================
#  REPORTE PDF (ReportLab - Python puro, sin dependencias de LaTeX)
# ======================================================================
def _get_report_fonts():
    """Registra fuentes TrueType (Arial de Windows) para soporte nativo de caracteres griegos y matemáticos."""
    font_names = {"reg": "Helvetica", "bold": "Helvetica-Bold", "italic": "Helvetica-Oblique"}
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        win_fonts = [
            os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
            r"C:\Windows\Fonts",
        ]
        for fdir in win_fonts:
            arial = os.path.join(fdir, "arial.ttf")
            arial_bd = os.path.join(fdir, "arialbd.ttf")
            arial_it = os.path.join(fdir, "ariali.ttf")
            if os.path.exists(arial):
                if "CustomArial" not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont("CustomArial", arial))
                    pdfmetrics.registerFont(TTFont("CustomArial-Bold", arial_bd if os.path.exists(arial_bd) else arial))
                    pdfmetrics.registerFont(TTFont("CustomArial-Italic", arial_it if os.path.exists(arial_it) else arial))
                font_names = {"reg": "CustomArial", "bold": "CustomArial-Bold", "italic": "CustomArial-Italic"}
                break
    except Exception:
        pass
    return font_names


def make_report_figs(tests, res, tipo, tmpdir):
    items = []

    def save(name, caption, fn):
        fig = Figure(figsize=(6.8, 3.8), dpi=200, layout="constrained")
        fn(fig.add_subplot(111))
        p = os.path.join(tmpdir, name + ".png").replace("\\", "/")
        fig.savefig(p, dpi=200)
        items.append((p, caption))

    save("curvas", "Figura 1. Esfuerzo desviador frente a deformación axial; se indica el módulo secante E50.",
         lambda ax: plot_curves(ax, tests, tipo))
    save("pq", "Figura 2. Trayectorias de esfuerzos efectivos p prima frente a q y envolvente de falla Kf.",
         lambda ax: plot_pq(ax, tests, res, tipo))
    save("mohr", "Figura 3. Círculos de Mohr a la falla y envolvente de resistencia de Mohr-Coulomb.",
         lambda ax: plot_mohr(ax, tests, res))
    if any("ev" in t["calc"].columns and t["calc"]["ev"].notna().any() for t in tests):
        save("vol", "Figura 4. Deformación volumétrica frente a deformación axial.",
             lambda ax: plot_vol(ax, tests))
    return items


def make_e50_figure(tests, path):
    """Guarda un esquema E50 sobre las curvas esfuerzo-deformación medidas."""
    fig = Figure(figsize=(7.2, 4.2), dpi=200, layout="constrained")
    ax = fig.add_subplot(111)
    for test in tests:
        df = test["calc"]
        mod = test["mod"]
        line, = ax.plot(
            df["e1"], df["desv"], marker="o", ms=2.5, lw=1.1,
            label=f"σ3 = {test['pc']:g} kPa",
        )
        ax.plot(
            [0, mod["e50"]], [0, mod["s50"]], "--", lw=1.2,
            color=line.get_color(),
        )
        ax.plot(
            mod["e50"], mod["s50"], "D", ms=5, color=line.get_color(),
            label=f"E50 = {mod['E_sec'] / 1000:.2f} MPa",
        )
    ax.set_title("Representación del módulo secante E50")
    ax.set_xlabel("Deformación axial ε1 (%)")
    ax.set_ylabel("Esfuerzo desviador σd (kPa)")
    ax.grid(alpha=0.35)
    ax.legend(fontsize=8, framealpha=1)
    fig.savefig(path, dpi=200)


def _build_report_reportlab(pdf_path, tests, res, tipo, info, skey):
    """
    Genera el reporte técnico y memoria de cálculo manual detallada en PDF
    usando ReportLab (sin necesidad de LaTeX, MiKTeX ni TeX Live).
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether, PageBreak, HRFlowable
    )
    from reportlab.pdfgen import canvas

    fonts = _get_report_fonts()
    is_unicode = (fonts["reg"] == "CustomArial")

    def S(txt):
        """Sanitiza texto en caso de usar fuentes estándar Latin-1 sin soporte Unicode extendido."""
        if not is_unicode:
            repl = {
                "φ": "phi", "σ": "sigma", "ε": "eps", "ν": "nu",
                "τ": "tau", "α": "alpha", "Δ": "Delta", "–": "-", "—": "-"
            }
            for k, v in repl.items():
                txt = txt.replace(k, v)
        return txt

    class NumberedCanvas(canvas.Canvas):
        header_font = fonts["reg"]

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            num_pages = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self.draw_decorations(num_pages)
                super().showPage()
            super().save()

        def draw_decorations(self, total_pages):
            self.saveState()
            self.setFont(self.header_font, 7.5)
            self.setFillColor(colors.HexColor("#4B5563"))
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.6)

            # Encabezado superior (a partir de la página 2)
            if self._pageNumber > 1:
                self.drawString(40, 805, S("MEMORIA DE CÁLCULO MANUAL — ENSAYO TRIAXIAL CD / CU"))
                self.drawRightString(555, 805, "ASTM D4767 / D7181 | NORMA TÉCNICA E.050")
                self.line(40, 798, 555, 798)

            # Pie de página (todas las páginas)
            self.line(40, 42, 555, 42)
            self.drawString(40, 30, S("Laboratorio de Mecánica de Suelos y Geotecnia — Cálculo Paso a Paso"))
            page_text = f"Página {self._pageNumber} de {total_pages}"
            self.drawRightString(555, 30, page_text)
            self.restoreState()

    # Formato de página y estilos
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=48,
        bottomMargin=48
    )

    styles = getSampleStyleSheet()
    f_reg, f_bold, f_it = fonts["reg"], fonts["bold"], fonts["italic"]

    style_title = ParagraphStyle(
        "ReportTitle",
        parent=styles["Normal"],
        fontName=f_bold,
        fontSize=15,
        leading=19,
        textColor=colors.HexColor("#0F2942"),
        alignment=1,
        spaceAfter=3,
    )
    style_subtitle = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontName=f_bold,
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#1E5F8A"),
        alignment=1,
        spaceAfter=10,
    )
    style_h1 = ParagraphStyle(
        "ReportH1",
        parent=styles["Normal"],
        fontName=f_bold,
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#0F2942"),
        spaceBefore=10,
        spaceAfter=5,
        keepWithNext=True,
    )
    style_h2 = ParagraphStyle(
        "ReportH2",
        parent=styles["Normal"],
        fontName=f_bold,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#1E5F8A"),
        spaceBefore=7,
        spaceAfter=3,
        keepWithNext=True,
    )
    style_body = ParagraphStyle(
        "ReportBody",
        parent=styles["Normal"],
        fontName=f_reg,
        fontSize=8,
        leading=11.2,
        textColor=colors.HexColor("#1F2937"),
        spaceAfter=4,
    )
    style_formula = ParagraphStyle(
        "ReportFormula",
        parent=styles["Normal"],
        fontName=f_reg,
        fontSize=8,
        leading=11.5,
        textColor=colors.HexColor("#0F2942"),
        leftIndent=10,
        spaceAfter=3,
    )
    style_step = ParagraphStyle(
        "ReportStep",
        parent=styles["Normal"],
        fontName=f_reg,
        fontSize=7.8,
        leading=10.8,
        textColor=colors.HexColor("#1F2937"),
        leftIndent=8,
        spaceAfter=2,
    )
    style_th = ParagraphStyle(
        "ReportTH",
        parent=styles["Normal"],
        fontName=f_bold,
        fontSize=7.5,
        leading=9.5,
        textColor=colors.white,
        alignment=1,
    )
    style_td = ParagraphStyle(
        "ReportTD",
        parent=styles["Normal"],
        fontName=f_reg,
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#1F2937"),
        alignment=1,
    )
    style_td_l = ParagraphStyle(
        "ReportTDL",
        parent=styles["Normal"],
        fontName=f_reg,
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#1F2937"),
        alignment=0,
    )
    style_td_bold = ParagraphStyle(
        "ReportTDBold",
        parent=styles["Normal"],
        fontName=f_bold,
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#0F2942"),
        alignment=1,
    )
    style_fig_cap = ParagraphStyle(
        "ReportFigCap",
        parent=styles["Normal"],
        fontName=f_bold,
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor("#1E5F8A"),
        alignment=1,
        spaceAfter=6,
    )
    style_ref = ParagraphStyle(
        "ReportRef",
        parent=styles["Normal"],
        fontName=f_reg,
        fontSize=7.5,
        leading=10.5,
        textColor=colors.HexColor("#374151"),
        leftIndent=14,
        firstLineIndent=-14,
        spaceAfter=3.5,
    )

    def box_table(paragraphs, bg_hex="#F8FAFC", border_hex="#CBD5E1"):
        t = Table([[p] for p in paragraphs], colWidths=[515])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg_hex)),
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor(border_hex)),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        return t

    story = []

    # ==================== ENCABEZADO Y TÍTULO ====================
    story.append(Paragraph(S("INFORME TÉCNICO Y MEMORIA DE CÁLCULO MANUAL"), style_title))
    ensayo_desc = "CONSOLIDADO DRENADO (CD)" if tipo == "CD" else "CONSOLIDADO NO DRENADO (CU) CON PRESIÓN DE POROS"
    story.append(Paragraph(
        S(f"ENSAYO DE COMPRESIÓN TRIAXIAL {ensayo_desc}<br/>"
          "Determinación Paso a Paso de Resistencia al Corte (φ, c) y Módulos Elásticos (E, ν, G)"),
        style_subtitle
    ))
    story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#1E5F8A"), spaceAfter=8))

    # ==================== 1. DATOS GENERALES ====================
    story.append(Paragraph(S("1. Datos Generales y Parámetros del Ensayo"), style_h1))
    suelo_nom = f"{skey} – {SUCS[skey][0]}" if skey else "No especificado"
    info_table_data = [
        [Paragraph(S("<b>Proyecto:</b>"), style_td_l), Paragraph(info.get("proyecto") or "–", style_td_l),
         Paragraph(S("<b>Ubicación / Calicata:</b>"), style_td_l), Paragraph(info.get("ubic") or "–", style_td_l)],
        [Paragraph(S("<b>Profundidad:</b>"), style_td_l), Paragraph(info.get("prof") or "–", style_td_l),
         Paragraph(S("<b>Responsable / Lab:</b>"), style_td_l), Paragraph(info.get("resp") or "Laboratorio de Geotecnia", style_td_l)],
        [Paragraph(S("<b>Tipo de Ensayo:</b>"), style_td_l), Paragraph(S(f"Triaxial {tipo} ({'Drenado' if tipo == 'CD' else 'No Drenado'})"), style_td_l),
         Paragraph(S("<b>Clasificación SUCS:</b>"), style_td_l), Paragraph(S(suelo_nom), style_td_l)],
        [Paragraph(S("<b>Criterio Falla (ε₁):</b>"), style_td_l), Paragraph(f"{res['deform']:g} %", style_td_l),
         Paragraph(S("<b>Módulo Evaluado:</b>"), style_td_l), Paragraph(S(MODE_NAME[res['mode']]), style_td_l)],
        [Paragraph(S("<b>N.° de Probetas:</b>"), style_td_l), Paragraph(str(len(tests)), style_td_l),
         Paragraph(S("<b>Normas Aplicables:</b>"), style_td_l), Paragraph(S("ASTM D4767 / D7181, Norma Técnica E.050"), style_td_l)],
    ]
    t_info = Table(info_table_data, colWidths=[105, 152, 105, 153])
    t_info.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 6))

    # ==================== 2. MARCO TEÓRICO Y FÓRMULAS ====================
    story.append(Paragraph(S("2. Fundamento Teórico y Metodología de Cálculo Manual"), style_h1))
    p_teoria = [
        Paragraph(S("<b>a) Principio de Esfuerzos Efectivos de Terzaghi:</b>"), style_formula),
        Paragraph(S("&nbsp;&nbsp;• Esfuerzo confinante efectivo: σ'₃ = σ₃ − u  (en ensayo CD drenado, u = 0 ⇒ σ'₃ = σ₃)"), style_formula),
        Paragraph(S("&nbsp;&nbsp;• Esfuerzo principal mayor efectivo: σ'₁ = σ₁ − u = σ₃ + σd − u"), style_formula),
        Paragraph(S("<b>b) Parámetros de Invariantes de Esfuerzo en el Plano Modificado (Lambe & Whitman, 1969):</b>"), style_formula),
        Paragraph(S("&nbsp;&nbsp;• Esfuerzo normal medio efectivo: p' = (σ'₁ + σ'₃) / 2"), style_formula),
        Paragraph(S("&nbsp;&nbsp;• Esfuerzo desviador medio: q = (σ'₁ − σ'₃) / 2 = σd / 2"), style_formula),
        Paragraph(S("<b>c) Envolvente de Falla Modificada (Línea Kf) y Parámetros de Mohr-Coulomb:</b>"), style_formula),
        Paragraph(S("&nbsp;&nbsp;• Ajuste por regresión lineal: q = a + p' · tan(α)"), style_formula),
        Paragraph(S("&nbsp;&nbsp;• Ángulo de fricción interna efectivo: sen(φ') = tan(α)  ⇒  φ' = arcsen(tan α)"), style_formula),
        Paragraph(S("&nbsp;&nbsp;• Cohesión efectiva: c' = a / cos(φ')   (si se asume suelo puramente friccionante, c' = 0)"), style_formula),
        Paragraph(S("<b>d) Módulos de Deformabilidad Elástica:</b>"), style_formula),
        Paragraph(S("&nbsp;&nbsp;• Módulo secante E₅₀ = (0.5 · σd,máx) / (ε₁,₅₀ / 100)"), style_formula),
        Paragraph(S("&nbsp;&nbsp;• Relación de Poisson ν: en CU ν = 0.50 (incompresible no drenado, εv = 0); en CD ν = 0.5·[1 − (εv / ε₁)]"), style_formula),
        Paragraph(S("&nbsp;&nbsp;• Módulo de elasticidad transversal o corte: G = E / [2 · (1 + ν)]"), style_formula),
    ]
    story.append(box_table(p_teoria, bg_hex="#F1F5F9", border_hex="#94A3B8"))
    story.append(Spacer(1, 6))

    # ==================== 3. MEMORIA DE CÁLCULO MANUAL ====================
    story.append(Paragraph(S("3. Memoria de Cálculo Manual Paso a Paso"), style_h1))

    # 3.1 Esfuerzos en Falla
    story.append(Paragraph(S("3.1. Determinación de Esfuerzos Principales y Parámetros (p', q) en Falla"), style_h2))
    story.append(Paragraph(
        S(f"Para cada probeta ensayada, se extrae el esfuerzo desviador σd y la presión de poros u "
          f"a la deformación axial de falla adoptada ε₁ = {res['deform']:g} %:"),
        style_body
    ))

    # Tabla de valores en falla
    headers_falla = [Paragraph(S("<b>Probeta</b>"), style_th),
                     Paragraph(S("<b>σ₃ (kPa)</b>"), style_th),
                     Paragraph(S("<b>σd (kPa)</b>"), style_th),
                     Paragraph(S("<b>u (kPa)</b>"), style_th),
                     Paragraph(S("<b>σ'₃ (kPa)</b>"), style_th),
                     Paragraph(S("<b>σ'₁ (kPa)</b>"), style_th),
                     Paragraph(S("<b>p' (kPa)</b>"), style_th),
                     Paragraph(S("<b>q (kPa)</b>"), style_th)]
    rows_falla = [headers_falla]
    for i, t in enumerate(tests, 1):
        s1p = t["p_def"] + t["q_def"]
        s3p = t["p_def"] - t["q_def"]
        u_val = t["pc"] - s3p if tipo == "CU" else 0.0
        rows_falla.append([
            Paragraph(f"#{i} ({t['name'][:10]})", style_td),
            Paragraph(f"{t['pc']:.1f}", style_td),
            Paragraph(f"{t['desv_def']:.1f}", style_td),
            Paragraph(f"{u_val:.1f}", style_td),
            Paragraph(f"{s3p:.1f}", style_td),
            Paragraph(f"{s1p:.1f}", style_td),
            Paragraph(f"{t['p_def']:.1f}", style_td_bold),
            Paragraph(f"{t['q_def']:.1f}", style_td_bold),
        ])
    t_falla = Table(rows_falla, colWidths=[65, 60, 60, 55, 65, 65, 70, 75])
    t_falla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F2942")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#FFFFFF"), colors.HexColor("#F8FAFC")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t_falla)
    story.append(Spacer(1, 4))

    # Desarrollo aritmético paso a paso por probeta
    pasos_esfuerzos = [Paragraph(S("<b>Desarrollo numérico paso a paso por probeta:</b>"), style_step)]
    for i, t in enumerate(tests, 1):
        s1p = t["p_def"] + t["q_def"]
        s3p = t["p_def"] - t["q_def"]
        u_val = t["pc"] - s3p if tipo == "CU" else 0.0
        s1_tot = t["pc"] + t["desv_def"]
        txt_u = f"u = {u_val:.1f} kPa (medida en condición CU)" if tipo == "CU" else "u = 0.0 kPa (ensayo drenado CD)"
        pasos_esfuerzos.append(Paragraph(
            S(f"• <b>Probeta #{i}</b> (confinamiento σ₃ = {t['pc']:.1f} kPa):<br/>"
              f"&nbsp;&nbsp;&nbsp;&nbsp;σd = {t['desv_def']:.1f} kPa  |  {txt_u}<br/>"
              f"&nbsp;&nbsp;&nbsp;&nbsp;σ₁ = σ₃ + σd = {t['pc']:.1f} + {t['desv_def']:.1f} = {s1_tot:.1f} kPa<br/>"
              f"&nbsp;&nbsp;&nbsp;&nbsp;σ'₃ = σ₃ − u = {t['pc']:.1f} − {u_val:.1f} = <b>{s3p:.1f} kPa</b><br/>"
              f"&nbsp;&nbsp;&nbsp;&nbsp;σ'₁ = σ₁ − u = {s1_tot:.1f} − {u_val:.1f} = <b>{s1p:.1f} kPa</b><br/>"
              f"&nbsp;&nbsp;&nbsp;&nbsp;p' = (σ'₁ + σ'₃) / 2 = ({s1p:.1f} + {s3p:.1f}) / 2 = <b>{t['p_def']:.1f} kPa</b><br/>"
              f"&nbsp;&nbsp;&nbsp;&nbsp;q = (σ'₁ − σ'₃) / 2 = ({s1p:.1f} − {s3p:.1f}) / 2 = <b>{t['q_def']:.1f} kPa</b>"),
            style_step
        ))
    story.append(box_table(pasos_esfuerzos, bg_hex="#F8FAFC", border_hex="#CBD5E1"))
    story.append(Spacer(1, 6))

    # 3.2 Regresión Lineal Manual (Línea Kf)
    story.append(Paragraph(S("3.2. Regresión Lineal Manual por Mínimos Cuadrados (Línea Kf)"), style_h2))
    p_vals = [float(t["p_def"]) for t in tests]
    q_vals = [float(t["q_def"]) for t in tests]
    n_pts = len(tests)
    p_mean = float(np.mean(p_vals))
    q_mean = float(np.mean(q_vals))
    dp_vals = [p - p_mean for p in p_vals]
    dq_vals = [q - q_mean for q in q_vals]
    dp2_vals = [dp ** 2 for dp in dp_vals]
    dpdq_vals = [dp * dq for dp, dq in zip(dp_vals, dq_vals)]
    sum_dp2 = float(np.sum(dp2_vals))
    sum_dpdq = float(np.sum(dpdq_vals))

    if res["only_phi"]:
        sum_pq = float(np.sum([p * q for p, q in zip(p_vals, q_vals)]))
        sum_p2 = float(np.sum([p ** 2 for p in p_vals]))
        tan_alpha = float(res["coef"][0])
        a_val = 0.0
    else:
        tan_alpha = float(sum_dpdq / sum_dp2) if sum_dp2 > 0 else float(res["coef"][0])
        a_val = float(q_mean - tan_alpha * p_mean)

    headers_reg = [Paragraph(S("<b>Probeta</b>"), style_th),
                   Paragraph(S("<b>p' (kPa)</b>"), style_th),
                   Paragraph(S("<b>q (kPa)</b>"), style_th),
                   Paragraph(S("<b>(p' − p̄')</b>"), style_th),
                   Paragraph(S("<b>(q − q̄)</b>"), style_th),
                   Paragraph(S("<b>(p' − p̄')²</b>"), style_th),
                   Paragraph(S("<b>(p'−p̄')(q−q̄)</b>"), style_th)]
    rows_reg = [headers_reg]
    for i, t in enumerate(tests, 1):
        rows_reg.append([
            Paragraph(f"#{i}", style_td),
            Paragraph(f"{p_vals[i-1]:.1f}", style_td),
            Paragraph(f"{q_vals[i-1]:.1f}", style_td),
            Paragraph(f"{dp_vals[i-1]:.2f}", style_td),
            Paragraph(f"{dq_vals[i-1]:.2f}", style_td),
            Paragraph(f"{dp2_vals[i-1]:.2f}", style_td),
            Paragraph(f"{dpdq_vals[i-1]:.2f}", style_td),
        ])
    rows_reg.append([
        Paragraph(S("<b>Σ Total</b>"), style_td_bold),
        Paragraph(f"<b>{sum(p_vals):.1f}</b>", style_td_bold),
        Paragraph(f"<b>{sum(q_vals):.1f}</b>", style_td_bold),
        Paragraph("<b>0.00</b>", style_td_bold),
        Paragraph("<b>0.00</b>", style_td_bold),
        Paragraph(f"<b>{sum_dp2:.2f}</b>", style_td_bold),
        Paragraph(f"<b>{sum_dpdq:.2f}</b>", style_td_bold),
    ])
    t_reg = Table(rows_reg, colWidths=[65, 75, 75, 75, 75, 75, 75])
    t_reg.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F2942")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t_reg)
    story.append(Spacer(1, 4))

    pasos_reg = [
        Paragraph(S(f"1. Medias muestrales: p̄' = {sum(p_vals):.1f} / {n_pts} = <b>{p_mean:.2f} kPa</b>  |  "
                    f"q̄ = {sum(q_vals):.1f} / {n_pts} = <b>{q_mean:.2f} kPa</b>"), style_step),
        Paragraph(S(f"2. Sumatorias de dispersión: S_pp = Σ(p' − p̄')² = <b>{sum_dp2:.2f} kPa²</b>  |  "
                    f"S_pq = Σ(p' − p̄')(q − q̄) = <b>{sum_dpdq:.2f} kPa²</b>"), style_step),
    ]
    if res["only_phi"]:
        pasos_reg.append(Paragraph(
            S(f"3. Ajuste forzado por el origen (Solo φ, c = 0):<br/>"
              f"&nbsp;&nbsp;&nbsp;&nbsp;tan(α) = Σ(p' · q) / Σ(p')² = <b>{tan_alpha:.4f}</b>  |  a = <b>0.00 kPa</b>"),
            style_step
        ))
    else:
        pasos_reg.append(Paragraph(
            S(f"3. Pendiente de la recta Kf: tan(α) = S_pq / S_pp = {sum_dpdq:.2f} / {sum_dp2:.2f} = <b>{tan_alpha:.4f}</b><br/>"
              f"4. Intercepto con el eje q: a = q̄ − tan(α) · p̄' = {q_mean:.2f} − ({tan_alpha:.4f} · {p_mean:.2f}) = <b>{a_val:.2f} kPa</b>"),
            style_step
        ))
    pasos_reg.append(Paragraph(
        S(f"<b>Ecuación de la recta Kf:</b> q = {a_val:.2f} + {tan_alpha:.4f} · p'  (kPa)"),
        style_step
    ))
    story.append(box_table(pasos_reg, bg_hex="#F8FAFC", border_hex="#CBD5E1"))
    story.append(Spacer(1, 6))

    # 3.3 Transformación a Mohr-Coulomb
    story.append(Paragraph(S("3.3. Transformación Trigonométrica a Parámetros de Mohr-Coulomb (φ', c')"), style_h2))
    phi_rad = float(res["phi_rad"])
    phi_deg = float(res["phi"])
    cos_phi = float(np.cos(phi_rad))
    c_val = float(res["c"])
    pasos_mc = [
        Paragraph(S(f"• <b>Ángulo de fricción interna efectivo (φ'):</b><br/>"
                    f"&nbsp;&nbsp;&nbsp;&nbsp;sen(φ') = tan(α) = {tan_alpha:.4f}<br/>"
                    f"&nbsp;&nbsp;&nbsp;&nbsp;φ' = arcsen({tan_alpha:.4f}) = {phi_rad:.4f} rad = <b>{phi_deg:.2f}°</b>"), style_step),
        Paragraph(S(f"• <b>Factor trigonométrico cos(φ'):</b><br/>"
                    f"&nbsp;&nbsp;&nbsp;&nbsp;cos({phi_deg:.2f}°) = <b>{cos_phi:.4f}</b>"), style_step),
        Paragraph(S(f"• <b>Cohesión efectiva (c'):</b><br/>"
                    f"&nbsp;&nbsp;&nbsp;&nbsp;c' = a / cos(φ') = {a_val:.2f} / {cos_phi:.4f} = <b>{c_val:.2f} kPa</b> "
                    f"{('(c forzado a 0.0 kPa)' if res['only_phi'] else '')}"), style_step),
        Paragraph(S(f"<b>Ecuación de rotura de Mohr-Coulomb:</b> τ = {c_val:.2f} + σ' · tan({phi_deg:.2f}°)  (kPa)"), style_step),
    ]
    story.append(box_table(pasos_mc, bg_hex="#F1F5F9", border_hex="#94A3B8"))
    story.append(Spacer(1, 6))

    # 3.4 Módulos Elásticos
    story.append(Paragraph(S("3.4. Cálculo Manual de Módulos Elásticos y Relación de Poisson"), style_h2))
    pasos_mod = []
    for i, t in enumerate(tests, 1):
        m = t["mod"]
        pasos_mod.append(Paragraph(
            S(f"• <b>Probeta #{i} (σ₃ = {t['pc']:.1f} kPa):</b><br/>"
              f"&nbsp;&nbsp;&nbsp;&nbsp;σd,máx = {m['smax']:.1f} kPa  ⇒  0.5 · σd,máx = {m['s50']:.1f} kPa<br/>"
              f"&nbsp;&nbsp;&nbsp;&nbsp;ε₁,₅₀ (interpolado al 50 %) = {m['e50']:.3f} %  (fracción = {m['e50']/100:.5f})<br/>"
              f"&nbsp;&nbsp;&nbsp;&nbsp;E₅₀ = (0.5 · σd,máx) / (ε₁,₅₀ / 100) = {m['s50']:.1f} / {m['e50']/100:.5f} = "
              f"<b>{m['E_sec']:.1f} kPa = {m['E_sec']/1000:.2f} MPa</b><br/>"
              f"&nbsp;&nbsp;&nbsp;&nbsp;Ei (tangente inicial) = <b>{m['E_ini']/1000:.2f} MPa</b>  |  "
              f"Et50 (tangente al 50 %) = <b>{m['E_tan']/1000:.2f} MPa</b><br/>"
              f"&nbsp;&nbsp;&nbsp;&nbsp;ν = <b>{m['nu']:.3f}</b> ({m['nu_src']})<br/>"
              f"&nbsp;&nbsp;&nbsp;&nbsp;G = E / [2 · (1 + ν)] = {m['E']/1000:.2f} / [2 · (1 + {m['nu']:.3f})] = "
              f"<b>{m['G']/1000:.2f} MPa</b>"),
            style_step
        ))
    story.append(box_table(pasos_mod, bg_hex="#F8FAFC", border_hex="#CBD5E1"))
    story.append(Spacer(1, 4))

    # Tabla resumen de módulos
    headers_mod = [Paragraph(S("<b>Probeta</b>"), style_th),
                   Paragraph(S("<b>σ₃ (kPa)</b>"), style_th),
                   Paragraph(S("<b>E₅₀ (MPa)</b>"), style_th),
                   Paragraph(S("<b>Ei (MPa)</b>"), style_th),
                   Paragraph(S("<b>Et50 (MPa)</b>"), style_th),
                   Paragraph(S("<b>ν (-)</b>"), style_th),
                   Paragraph(S("<b>G (MPa)</b>"), style_th),
                   Paragraph(S("<b>E Usado (MPa)</b>"), style_th)]
    rows_mod = [headers_mod]
    for i, t in enumerate(tests, 1):
        m = t["mod"]
        rows_mod.append([
            Paragraph(f"#{i}", style_td),
            Paragraph(f"{t['pc']:.1f}", style_td),
            Paragraph(f"{m['E_sec']/1000:.2f}", style_td),
            Paragraph(f"{m['E_ini']/1000:.2f}", style_td),
            Paragraph(f"{m['E_tan']/1000:.2f}", style_td),
            Paragraph(f"{m['nu']:.3f}", style_td),
            Paragraph(f"{m['G']/1000:.2f}", style_td),
            Paragraph(f"{m['E']/1000:.2f}", style_td_bold),
        ])
    t_mod = Table(rows_mod, colWidths=[65, 55, 65, 65, 65, 55, 70, 75])
    t_mod.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F2942")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#FFFFFF"), colors.HexColor("#F8FAFC")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t_mod)
    # ==================== 4. GRÁFICAS ====================
    story.append(PageBreak())
    story.append(Paragraph(S("4. Gráficas del Ensayo Triaxial"), style_h1))
    story.append(Paragraph(
        S("Curvas de esfuerzo-deformación, trayectorias en el plano p'–q y círculos de Mohr con envolvente de rotura:"),
        style_body
    ))

    # ABRIMOS EL DIRECTORIO TEMPORAL
    with tempfile.TemporaryDirectory() as tmpdir:
        figs = make_report_figs(tests, res, tipo, tmpdir)
        for path_fig, cap in figs:
            fig_flowables = [
                Image(path_fig, width=490, height=225),
                Paragraph(S(cap), style_fig_cap),
                Spacer(1, 4)
            ]
            story.append(KeepTogether(fig_flowables))

        # ¡IMPORTANTE! A partir de aquí, todo debe llevar una indentación extra 
        # para que quede dentro del bloque `with`.

        # ==================== 5. RESULTADOS E INTERPRETACIÓN ====================
        story.append(Paragraph(S("5. Resumen de Resultados Finales e Interpretación Geotécnica"), style_h1))

        # Tabla destacada de resultados de diseño
        res_summary_data = [
            [Paragraph(S("<b>Parámetro Geotécnico de Resistencia / Deformabilidad</b>"), style_th),
             Paragraph(S("<b>Valor de Cálculo Obtenido</b>"), style_th)],
            [Paragraph(S("Ángulo de Fricción Interna Efectivo (φ')"), style_td_l),
             Paragraph(f"<b>{res['phi']:.2f} °</b>", style_td_bold)],
            [Paragraph(S("Cohesión Efectiva (c')"), style_td_l),
             Paragraph(f"<b>{res['c']:.2f} kPa</b>", style_td_bold)],
            [Paragraph(S(f"Módulo de Elasticidad Promedio ({MODE_NAME[res['mode']]})"), style_td_l),
             Paragraph(f"<b>{np.mean([t['mod']['E'] for t in tests])/1000:.2f} MPa</b>", style_td_bold)],
            [Paragraph(S("Módulo de Corte Elástico Promedio (G)"), style_td_l),
             Paragraph(f"<b>{np.mean([t['mod']['G'] for t in tests])/1000:.2f} MPa</b>", style_td_bold)],
            [Paragraph(S("Relación de Poisson Promedio (ν)"), style_td_l),
             Paragraph(f"<b>{np.mean([t['mod']['nu'] for t in tests]):.3f}</b>", style_td_bold)],
        ]
        t_res_sum = Table(res_summary_data, colWidths=[240, 275])
        t_res_sum.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F2942")),
            ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#CBD5E1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F8FAFC"), colors.HexColor("#FFFFFF")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(t_res_sum)
        story.append(Spacer(1, 6))

        # Párrafos de interpretación
        story.append(Paragraph(S("<b>Evaluación e Interpretación Geotécnica:</b>"), style_h2))
        for p_txt in interpret(res, tests, tipo, skey):
            story.append(Paragraph(S(f"• {p_txt}"), style_body))

        story.append(Spacer(1, 4))
        story.append(Paragraph(
            S("<b>Observaciones de Diseño y Confiabilidad:</b><br/>"
              "Los parámetros geotécnicos obtenidos dependen del confinamiento de cámara, de la calidad del remoldeo o "
              "indisturbación de la muestra y del criterio de rotura adoptado. De conformidad con la <b>Norma Técnica E.050 "
              "(Suelos y Cimentaciones)</b>, los valores reportados deben ser ponderados por el ingeniero especialista "
              "considerando los factores de seguridad pertinentes para el diseño de cimentaciones, estabilidad de taludes "
              "y empujes de tierras."),
            style_body
        ))
        story.append(Spacer(1, 6))

        # ==================== 6. REFERENCIAS NORMATIVAS Y BIBLIOGRÁFICAS ====================
        story.append(Paragraph(S("6. Referencias Normativas y Bibliográficas"), style_h1))
        referencias = [
            "1. <b>ASTM D4767-11(2020)</b>: Standard Test Method for Consolidated Undrained Triaxial Compression Test for Cohesive Soils.",
            "2. <b>ASTM D7181-20</b>: Standard Test Method for Consolidated Drained Triaxial Compression Test for Soils.",
            "3. <b>Norma Técnica E.050 'Suelos y Cimentaciones'</b>: Reglamento Nacional de Edificaciones (RNE), Perú.",
            "4. <b>Lambe, T. W., & Whitman, R. V. (1969)</b>: <i>Soil Mechanics</i>.",
            "5. <b>Bowles, J. E. (1996)</b>: <i>Foundation Analysis and Design</i>.",
            "6. <b>Das, B. M., & Sobhan, K. (2018)</b>: <i>Principles of Geotechnical Engineering</i>.",
            "7. <b>Holtz, R. D., Kovacs, W. D., & Sheahan, T. C. (2011)</b>: <i>An Introduction to Geotechnical Engineering</i>.",
            "8. <b>Head, K. H., & Epps, R. J. (2014)</b>: <i>Manual of Soil Laboratory Testing, Volume 3</i>."
        ]
        for ref in referencias:
            story.append(Paragraph(S(ref), style_ref))

        # Construir documento (AHORA DENTRO DEL WITH)
        doc.build(story, canvasmaker=NumberedCanvas)


# ======================================================================
#  IMPLEMENTACIÓN ANTERIOR DE REPORTE PDF CON PyLaTeX
# ======================================================================
def build_report(pdf_path, tests, res, tipo, info, skey):
    """Genera la memoria triaxial en LaTeX y la compila con pdflatex."""
    from pylatex import Document, Section, Subsection, Tabular, Itemize
    from pylatex.package import Package
    from pylatex.utils import NoEscape, escape_latex

    def tex(value):
        replacements = {
            "φ": "phi", "σ": "sigma", "ε": "eps", "ν": "nu",
            "τ": "tau", "α": "alpha", "Δ": "Delta", "–": "-",
            "—": "-", "◆": "rombo", "²": "^2", "₃": "3", "₁": "1",
        }
        text = str(value)
        for source, replacement in replacements.items():
            text = text.replace(source, replacement)
        return escape_latex(text)

    def tex_cell(value):
        return value if isinstance(value, NoEscape) else NoEscape(tex(value))

    def add_step(title, equations, note=None):
        doc.append(NoEscape(
            r"\par\medskip\noindent\textbf{" + tex(title) + r"}\par"
        ))
        if equations:
            doc.append(NoEscape(
                r"\begin{equation*}\begin{aligned}"
                + r"\\[3pt]".join(
                    r"&\displaystyle " + equation for equation in equations
                )
                + r"\end{aligned}\end{equation*}"
            ))
        if note:
            doc.append(NoEscape(r"\noindent\small " + tex(note) + r"\normalsize\par"))

    def add_table(headers, rows, spec):
        doc.append(NoEscape(
            r"\begin{center}\scriptsize\setlength{\tabcolsep}{3pt}"
            r"\resizebox{\textwidth}{!}{%"
        ))
        with doc.create(Tabular(spec, booktabs=True)) as table:
            table.add_row(
                [NoEscape(r"\textbf{" + tex(header) + "}") for header in headers],
                escape=False,
            )
            table.add_hline()
            for row in rows:
                table.add_row([tex_cell(value) for value in row], escape=False)
        doc.append(NoEscape(r"}\end{center}\normalsize"))

    doc = Document(
        documentclass="article",
        document_options=["11pt", "a4paper"],
        geometry_options={"top": "2.2cm", "bottom": "2.2cm",
                          "left": "2cm", "right": "2cm"},
    )
    report_tmpdir = tempfile.TemporaryDirectory(prefix="triaxial_report_")
    for package, options in (
        ("inputenc", ["utf8"]),
        ("fontenc", ["T1"]),
        ("amsmath", None),
        ("graphicx", None),
        ("float", None),
        ("booktabs", None),
        ("array", None),
        ("xcolor", None),
        ("fancyhdr", None),
        ("hyperref", ["colorlinks=true", "linkcolor=blue", "urlcolor=blue"]),
    ):
        doc.packages.append(Package(package, options=options))

    doc.preamble.append(NoEscape(r"\definecolor{triaxialblue}{HTML}{0F2942}"))
    doc.preamble.append(NoEscape(r"\definecolor{triaxialgray}{HTML}{64748B}"))
    doc.preamble.append(NoEscape(r"\pagestyle{fancy}"))
    doc.preamble.append(NoEscape(r"\fancyhf{}"))
    doc.preamble.append(NoEscape(
        r"\fancyhead[L]{\small\color{triaxialgray}MEMORIA DE CÁLCULO -- ENSAYO TRIAXIAL CD / CU}"
    ))
    doc.preamble.append(NoEscape(
        r"\fancyfoot[L]{\small\color{triaxialgray}Ing. A. Milkenson | Mecánica de Suelos}"
    ))
    doc.preamble.append(NoEscape(r"\fancyfoot[R]{\small Copyright \copyright\ 2026 | Página \thepage}"))
    doc.preamble.append(NoEscape(r"\setlength{\headheight}{14pt}"))
    doc.preamble.append(NoEscape(r"\setlength{\parskip}{4pt}"))

    ensayo = ("CONSOLIDADO DRENADO (CD)" if tipo == "CD"
              else "CONSOLIDADO NO DRENADO (CU) CON PRESIÓN DE POROS")
    doc.append(NoEscape(r"\begin{center}"))
    doc.append(NoEscape(
        r"{\LARGE\bfseries\color{triaxialblue}"
        r"INFORME TÉCNICO Y MEMORIA DE CÁLCULO MANUAL\par}"
    ))
    doc.append(NoEscape(r"\vspace{4pt}"))
    doc.append(NoEscape(
        r"{\large\bfseries ENSAYO DE COMPRESIÓN TRIAXIAL "
        + tex(ensayo) + NoEscape(r"\par}")
    ))
    doc.append(NoEscape(
        r"\textcolor{triaxialgray}{Resistencia al corte ($\phi'$, $c'$) "
        r"y módulos elásticos ($E$, $\nu$, $G$)}"
    ))
    doc.append(NoEscape(r"\end{center}\vspace{4pt}\hrule"))

    with doc.create(Section("Datos generales del ensayo")):
        suelo = f"{skey} - {SUCS[skey][0]}" if skey else "No especificado"
        info_rows = [
            ("Proyecto", info.get("proyecto") or "-"),
            ("Ubicación / Calicata", info.get("ubic") or "-"),
            ("Profundidad", info.get("prof") or "-"),
            ("Responsable / Laboratorio", info.get("resp") or "Laboratorio de Geotecnia"),
            ("Tipo de ensayo", f"Triaxial {tipo}"),
            ("Clasificación SUCS", suelo),
            ("Deformación axial adoptada", f"{res['deform']:g} %"),
            ("Módulo evaluado", MODE_NAME[res["mode"]]),
            ("Número de probetas", str(len(tests))),
            ("Normativa de referencia", "ASTM D4767 / D7181; Norma Técnica E.050"),
        ]
        add_table(["Dato", "Descripción"], info_rows, "|p{4.2cm}|p{11.5cm}|")

    with doc.create(Section("Fundamento y metodología")):
        formulas = [
            r"Esfuerzo efectivo: $\sigma'_3=\sigma_3-u$; "
            r"$\sigma'_1=\sigma_3+\sigma_d-u$.",
            r"Invariantes: $p'=(\sigma'_1+\sigma'_3)/2$; "
            r"$q=(\sigma'_1-\sigma'_3)/2=\sigma_d/2$.",
            r"Envolvente Kf: $q=a+p'\tan(\alpha)$.",
            r"Parámetros de resistencia: $\phi'=\arcsin(\tan\alpha)$; "
            r"$c'=a/\cos(\phi')$ (o $c'=0$ cuando se ajusta solo $\phi'$).",
            r"Módulo secante: $E_{50}=(0.5\,\sigma_{d,\max})/"
            r"(\epsilon_{1,50}/100)$.",
            r"Módulo de corte: $G=E/[2(1+\nu)]$.",
        ]
        with doc.create(Itemize()) as items:
            for formula in formulas:
                items.add_item(NoEscape(formula))
        doc.append(
            "En CU, la interpretación emplea esfuerzos efectivos considerando la presión "
            "de poros; en CD se toma u = 0 para este cálculo."
        )

    with doc.create(Section("Memoria de cálculo")):
        with doc.create(Subsection("Esfuerzos e invariantes en la falla")):
            doc.append(
                NoEscape(r"Valores interpolados a la deformación axial adoptada "
                         r"$\epsilon_1=" + tex(f"{res['deform']:g}") + r"\%$.")
            )
            failure_rows = []
            for i, test in enumerate(tests, 1):
                sigma1_eff = test["p_def"] + test["q_def"]
                sigma3_eff = test["p_def"] - test["q_def"]
                u_value = test["pc"] - sigma3_eff if tipo == "CU" else 0.0
                failure_rows.append((
                    f"#{i} {test['name'][:12]}",
                    f"{test['pc']:.1f}",
                    f"{test['desv_def']:.1f}",
                    f"{u_value:.1f}",
                    f"{sigma3_eff:.1f}",
                    f"{sigma1_eff:.1f}",
                    f"{test['p_def']:.1f}",
                    f"{test['q_def']:.1f}",
                ))
            add_table(
                ["Probeta", "Confinamiento σ3 (kPa)", "Desviador σd (kPa)", "u (kPa)",
                 "σ'3 efectivo (kPa)", "σ'1 efectivo (kPa)",
                 "Esfuerzo medio p' (kPa)", "Esfuerzo q (kPa)"],
                failure_rows,
                "|l|r|r|r|r|r|r|r|",
            )
            for i, test in enumerate(tests, 1):
                sigma1_eff = test["p_def"] + test["q_def"]
                sigma3_eff = test["p_def"] - test["q_def"]
                u_value = test["pc"] - sigma3_eff if tipo == "CU" else 0.0
                doc.append(NoEscape(
                    r"\par\medskip\noindent\textbf{Desarrollo -- Probeta \#"
                    + str(i) + r"}\par"
                ))
                add_step(
                    f"1. Esfuerzos principales y presión de poros (probeta {i})",
                    [
                        r"\sigma_1=\sigma_3+\sigma_d="
                        + tex(f"{test['pc']:.1f}") + "+"
                        + tex(f"{test['desv_def']:.1f}") + "="
                        + tex(f"{test['pc'] + test['desv_def']:.1f}")
                        + r"\,\mathrm{kPa}",
                        r"u=" + tex(f"{u_value:.1f}") + r"\,\mathrm{kPa}",
                        r"\sigma'_3=\sigma_3-u="
                        + tex(f"{test['pc']:.1f}") + "-"
                        + tex(f"{u_value:.1f}") + "="
                        + tex(f"{sigma3_eff:.1f}") + r"\,\mathrm{kPa}",
                        r"\sigma'_1=\sigma_1-u="
                        + tex(f"{test['pc'] + test['desv_def']:.1f}") + "-"
                        + tex(f"{u_value:.1f}") + "="
                        + tex(f"{sigma1_eff:.1f}") + r"\,\mathrm{kPa}",
                    ],
                )
                add_step(
                    f"2. Esfuerzos invariantes (probeta {i})",
                    [
                        r"p'=\frac{\sigma'_1+\sigma'_3}{2}",
                        r"p'=\frac{" + tex(f"{sigma1_eff:.1f}")
                        + "+" + tex(f"{sigma3_eff:.1f}") + r"}{2}",
                        r"p'=" + tex(f"{test['p_def']:.1f}")
                        + r"\,\mathrm{kPa}",
                        r"q=\frac{\sigma'_1-\sigma'_3}{2}",
                        r"q=\frac{" + tex(f"{sigma1_eff:.1f}")
                        + "-" + tex(f"{sigma3_eff:.1f}") + r"}{2}",
                        r"q=" + tex(f"{test['q_def']:.1f}")
                        + r"\,\mathrm{kPa}",
                    ],
                )

        with doc.create(Subsection("Ajuste de la envolvente Kf")):
            p_vals = [float(test["p_def"]) for test in tests]
            q_vals = [float(test["q_def"]) for test in tests]
            n_pts = len(tests)
            mean_p, mean_q = float(np.mean(p_vals)), float(np.mean(q_vals))
            centered_p = np.asarray(p_vals) - mean_p
            centered_q = np.asarray(q_vals) - mean_q
            sum_pp = float(np.sum(centered_p ** 2))
            sum_pq = float(np.sum(centered_p * centered_q))
            if res["only_phi"]:
                sum_p2 = float(np.sum(np.asarray(p_vals) ** 2))
                tan_alpha = float(np.sum(np.asarray(p_vals) * q_vals) / sum_p2)
                intercept = 0.0
                doc.append(
                    "Ajuste restringido al origen (solo ángulo de fricción; cohesión fijada en cero)."
                )
            else:
                tan_alpha = float(res["coef"][0])
                intercept = float(res["coef"][1])
            regression_rows = [
                (f"#{i}", f"{p:.2f}", f"{q:.2f}",
                 f"{dp:.2f}", f"{dq:.2f}", f"{dp ** 2:.2f}", f"{dp * dq:.2f}")
                for i, (p, q, dp, dq) in enumerate(
                    zip(p_vals, q_vals, centered_p, centered_q), 1
                )
            ]
            add_table(
                ["Probeta", "p' (kPa)", "q (kPa)", "Desviación p' (kPa)",
                 "Desviación q (kPa)", "Desviación p' al cuadrado (kPa2)",
                 "Producto de desviaciones (kPa2)"],
                regression_rows,
                "|l|r|r|r|r|r|r|",
            )
            add_step(
                "Cálculo de medias y sumatorias",
                [
                    r"\bar{p}'=\frac{\sum p'}{n}="
                    + tex(f"{sum(p_vals):.2f}") + r"/" + str(n_pts)
                    + "=" + tex(f"{mean_p:.2f}") + r"\,\mathrm{kPa}",
                    r"\bar{q}=\frac{\sum q}{n}="
                    + tex(f"{sum(q_vals):.2f}") + r"/" + str(n_pts)
                    + "=" + tex(f"{mean_q:.2f}") + r"\,\mathrm{kPa}",
                    r"S_{pp}=\sum(p'-\bar{p}')^2="
                    + tex(f"{sum_pp:.2f}") + r"\,\mathrm{kPa}^2",
                    r"S_{pq}=\sum(p'-\bar{p}')(q-\bar{q})="
                    + tex(f"{sum_pq:.2f}") + r"\,\mathrm{kPa}^2",
                ],
            )
            if res["only_phi"]:
                add_step(
                    "Pendiente de la envolvente forzada al origen",
                    [
                        r"\tan(\alpha)=\frac{\sum(p'q)}{\sum(p'^2)}",
                        r"\tan(\alpha)="
                        + tex(f"{float(np.sum(np.asarray(p_vals) * q_vals)):.2f}")
                        + r"/" + tex(f"{float(np.sum(np.asarray(p_vals) ** 2)):.2f}")
                        + "=" + tex(f"{tan_alpha:.5f}"),
                        r"q=" + tex(f"{tan_alpha:.5f}") + r"p'\quad(a=0)",
                    ],
                )
            else:
                add_step(
                    "Pendiente e intercepto de la envolvente",
                    [
                        r"\tan(\alpha)=\frac{S_{pq}}{S_{pp}}",
                        r"\tan(\alpha)=" + tex(f"{sum_pq:.2f}") + r"/"
                        + tex(f"{sum_pp:.2f}") + "=" + tex(f"{tan_alpha:.5f}"),
                        r"a=\bar{q}-\tan(\alpha)\bar{p}'",
                        r"a=" + tex(f"{mean_q:.2f}") + "-"
                        + tex(f"{tan_alpha:.5f}") + r"\times"
                        + tex(f"{mean_p:.2f}") + "=" + tex(f"{intercept:.2f}")
                        + r"\,\mathrm{kPa}",
                    ],
                )
            add_step(
                "Ecuación final de la recta Kf",
                [
                    r"q=a+p'\tan(\alpha)",
                    r"q=" + tex(f"{intercept:.2f}") + "+"
                    + tex(f"{tan_alpha:.5f}") + r"p'\quad(\mathrm{kPa})",
                ],
            )

        with doc.create(Subsection("Parámetros de Mohr-Coulomb")):
            add_step(
                "Conversión a parámetros de Mohr-Coulomb",
                [
                    r"\phi'=\arcsin(\tan(\alpha))="
                    + r"\arcsin(" + tex(f"{tan_alpha:.5f}") + r")",
                    r"\phi'=" + tex(f"{float(res['phi']):.2f}") + r"^\circ",
                    r"c'=\frac{a}{\cos(\phi')}="
                    + r"\frac{" + tex(f"{intercept:.2f}") + r"}"
                    + r"{\cos(" + tex(f"{float(res['phi']):.2f}") + r"^\circ)}",
                    r"c'=" + tex(f"{float(res['c']):.2f}")
                    + r"\,\mathrm{kPa}",
                    r"\tau=c'+\sigma'\tan(\phi')",
                    r"\tau=" + tex(f"{float(res['c']):.2f}")
                    + r"+\sigma'\tan(" + tex(f"{float(res['phi']):.2f}")
                    + r"^\circ)",
                ],
            )

        with doc.create(Subsection("Módulos elásticos por probeta")):
            doc.append(
                "Convención: la deformación axial (e1) y volumétrica (ev) se ingresa "
                "en porcentaje; por ello, toda pendiente respecto de e1 (%) se multiplica por 100 para "
                "expresarla respecto de la deformación unitaria. Los módulos se reportan "
                "en kPa y su conversión a MPa se realiza dividiendo entre 1000."
            )
            module_rows = []
            for i, test in enumerate(tests, 1):
                mod = test["mod"]
                doc.append(NoEscape(
                    r"\par\medskip\noindent\colorbox{triaxialblue}{"
                    r"\parbox{\dimexpr\linewidth-2\fboxsep\relax}{"
                    r"\color{white}\textbf{PROBETA \#" + str(i) + r" -- "
                    + tex(test["name"]) + r"}}}\par\smallskip"
                ))
                add_step(
                    "Paso 1. Esfuerzo máximo y nivel de carga del 50 %",
                    [
                        r"\sigma_{d,\max}="
                        + tex(f"{mod['smax']:.2f}") + r"\,\mathrm{kPa}",
                        r"\sigma_{d,50}=0.5\,\sigma_{d,\max}",
                        r"\sigma_{d,50}=0.5\times"
                        + tex(f"{mod['smax']:.2f}") + "="
                        + tex(f"{mod['s50']:.2f}") + r"\,\mathrm{kPa}",
                    ],
                )
                bracket = mod["half_bracket"]
                if bracket:
                    e0, s0, e1, s1 = bracket
                    if s1 != s0:
                        interpolated_strain = e0 + (
                            (mod["s50"] - s0) / (s1 - s0)
                        ) * (e1 - e0)
                    else:
                        interpolated_strain = e1
                    add_step(
                        "Paso 2. Interpolación de la deformación axial al 50 %",
                        [
                            r"(\epsilon_a,\sigma_a)=("
                            + tex(f"{e0:.4f}") + r"\%,"
                            + tex(f"{s0:.2f}") + r"\,\mathrm{kPa})",
                            r"(\epsilon_b,\sigma_b)=("
                            + tex(f"{e1:.4f}") + r"\%,"
                            + tex(f"{s1:.2f}") + r"\,\mathrm{kPa})",
                            r"\epsilon_{1,50}=\epsilon_a+"
                            r"\frac{\sigma_{d,50}-\sigma_a}{\sigma_b-\sigma_a}"
                            r"(\epsilon_b-\epsilon_a)",
                            r"\epsilon_{1,50}=" + tex(f"{e0:.4f}")
                            + r"+\frac{" + tex(f"{mod['s50']:.2f}")
                            + "-" + tex(f"{s0:.2f}") + r"}{"
                            + tex(f"{s1:.2f}") + "-" + tex(f"{s0:.2f}")
                            + r"}(" + tex(f"{e1:.4f}") + "-"
                            + tex(f"{e0:.4f}") + r")",
                            r"\epsilon_{1,50}="
                            + tex(f"{interpolated_strain:.4f}") + r"\%",
                        ],
                    )
                else:
                    add_step(
                        "Paso 2. Deformación axial al 50 %",
                        [r"\epsilon_{1,50}="
                         + tex(f"{mod['e50']:.4f}") + r"\%"],
                        "No se encontró el cruce del 50 % en la curva medida.",
                    )
                add_step(
                    "Paso 3. Módulo secante E50",
                    [
                        r"E_{50}=\frac{\sigma_{d,50}}{\epsilon_{1,50}/100}",
                        r"\epsilon_{1,50,\mathrm{decimal}}="
                        + tex(f"{mod['e50']:.4f}") + r"/100="
                        + tex(f"{mod['e50'] / 100:.6f}"),
                        r"E_{50}=\frac{" + tex(f"{mod['s50']:.2f}")
                        + r"}{" + tex(f"{mod['e50'] / 100:.6f}") + r"}",
                        r"E_{50}=" + tex(f"{mod['E_sec']:.2f}")
                        + r"\,\mathrm{kPa}",
                        r"E_{50}=" + tex(f"{mod['E_sec']:.2f}")
                        + r"/1000=" + tex(f"{mod['E_sec'] / 1000:.3f}")
                        + r"\,\mathrm{MPa}",
                    ],
                )

                for step_label, fit_key, title, fallback in (
                    ("Paso 4a. Tangente inicial Ei", "ini_fit",
                     "Tangente inicial Ei", mod["ini_fallback"]),
                    ("Paso 4b. Tangente al 50 % Et50", "tan_fit",
                     "Tangente al 50 % Et50", mod["tan_fallback"]),
                ):
                    fit = mod[fit_key]
                    xs = np.asarray(fit["e"], dtype=float)
                    ys = np.asarray(fit["y"], dtype=float)
                    n_fit = len(xs)
                    if n_fit >= 2 and np.ptp(xs) > 0:
                        sum_x = float(np.sum(xs))
                        sum_y = float(np.sum(ys))
                        sum_x2 = float(np.sum(xs ** 2))
                        sum_xy = float(np.sum(xs * ys))
                        numerator = n_fit * sum_xy - sum_x * sum_y
                        denominator = n_fit * sum_x2 - sum_x ** 2
                        lo_pct, hi_pct = ((0, 20) if fit_key == "ini_fit"
                                          else (40, 60))
                        note = (" Se usaron los dos puntos disponibles más cercanos "
                                "al intervalo indicado porque había menos de dos "
                                "lecturas dentro de la ventana.") if fallback else ""
                        add_step(
                            step_label,
                            [
                                r"b=\frac{n\sum xy-(\sum x)(\sum y)}"
                                r"{n\sum x^2-(\sum x)^2}",
                                r"b=\frac{" + tex(f"{n_fit}({sum_xy:.4f})"
                                                   f"-({sum_x:.4f})({sum_y:.4f})")
                                + r"}{" + str(n_fit) + r"\left("
                                + tex(f"{sum_x2:.4f}") + r"\right)-\left("
                                + tex(f"{sum_x:.4f}") + r"\right)^2}",
                                r"b=" + tex(f"{fit['slope']:.5f}")
                                + r"\,\mathrm{kPa}/\%",
                                r"E=b\times100="
                                + tex(f"{fit['slope']:.5f}") + r"\times100="
                                + tex(f"{fit['slope'] * 100:.2f}")
                                + r"\,\mathrm{kPa}",
                                r"E=" + tex(f"{fit['slope'] * 100:.2f}")
                                + r"/1000=" + tex(f"{fit['slope'] / 10:.3f}")
                                + r"\,\mathrm{MPa}",
                            ],
                            f"Intervalo de esfuerzo: {lo_pct}–{hi_pct} % de σd,max; "
                            f"n = {n_fit} puntos. Valores (e1 %, σd kPa): "
                            + "; ".join(f"({x:.3f}, {y:.2f})"
                                        for x, y in zip(xs, ys)) + "." + note,
                        )
                    else:
                        doc.append(tex(
                            f"{title}: no se pudo estimar la pendiente. Se requieren "
                            "al menos dos deformaciones distintas en la ventana seleccionada."
                        ))

                if tipo == "CU":
                    add_step(
                        "Paso 5. Relación de Poisson",
                        [
                            r"\epsilon_v=0\quad\text{(condición no drenada)}",
                            r"\nu=0.50",
                        ],
                        "Se adopta comportamiento no drenado con volumen constante.",
                    )
                elif mod["has_ev"]:
                    nu_values = mod["nu_all"]
                    ev50 = mod["ev50"]
                    add_step(
                        "Paso 5. Relación de Poisson a partir de la deformación volumétrica",
                        [
                            r"\nu_{50}=\frac{1}{2}"
                            r"\left(1-\frac{\epsilon_{v,50}}{\epsilon_{1,50}}\right)",
                            r"\nu_{50}=\frac{1}{2}"
                            + r"\left(1-\frac{" + tex(f"{ev50:.4f}")
                            + r"}{" + tex(f"{mod['e50']:.4f}") + r"}\right)",
                            r"\nu_{50}=" + tex(f"{nu_values['sec']:.4f}"),
                            r"b_{v,i}=" + tex(f"{mod['ini_ev_fit']['slope']:.5f}")
                            + r",\quad b_{v,50}="
                            + tex(f"{mod['tan_ev_fit']['slope']:.5f}"),
                            r"\nu_i=\frac{1}{2}(1-b_{v,i})="
                            + tex(f"{nu_values['ini']:.4f}"),
                            r"\nu_{t50}=\frac{1}{2}(1-b_{v,50})="
                            + tex(f"{nu_values['tan']:.4f}"),
                        ],
                        "εv,50 es la deformación volumétrica interpolada al mismo ε1,50.",
                    )
                else:
                    add_step(
                        "Paso 5. Relación de Poisson",
                        [r"\nu=" + tex(f"{mod['nu']:.3f}")],
                        "No se dispone de εv medido; se utilizó el valor asumido "
                        f"ν = {mod['nu']:.3f} ({mod['nu_src']}).",
                    )
                add_step(
                    "Paso 6. Módulo de corte G",
                    [
                        r"G=\frac{E}{2(1+\nu)}",
                        r"G=\frac{" + tex(f"{mod['E']:.2f}") + r"}{2(1+"
                        + tex(f"{mod['nu']:.4f}") + r")}",
                        r"G=" + tex(f"{mod['G']:.2f}")
                        + r"\,\mathrm{kPa}",
                        r"G=" + tex(f"{mod['G']:.2f}") + r"/1000="
                        + tex(f"{mod['G'] / 1000:.3f}") + r"\,\mathrm{MPa}",
                    ],
                    "Módulo E empleado: " + MODE_NAME[res["mode"]] + ".",
                )
                module_rows.append((
                    f"#{i}", f"{test['pc']:.1f}", f"{mod['E_sec']/1000:.2f}",
                    f"{mod['E_ini']/1000:.2f}", f"{mod['E_tan']/1000:.2f}",
                    f"{mod['nu']:.3f}", f"{mod['G']/1000:.2f}",
                    f"{mod['E']/1000:.2f}",
                ))
            add_table(
                ["Probeta", "Confinamiento σ3 (kPa)", "E50 (MPa)", "Ei (MPa)",
                 "Et50 (MPa)", "Poisson ν", "G (MPa)", "E usado (MPa)"],
                module_rows,
                "|l|r|r|r|r|r|r|r|",
            )
            e50_path = os.path.join(report_tmpdir.name, "modulo_secante_e50.png")
            make_e50_figure(tests, e50_path)
            tex_e50_path = os.path.abspath(e50_path).replace("\\", "/")
            doc.append(NoEscape(
                r"\begin{center}\includegraphics[width=0.88\textwidth]{\detokenize{"
                + tex_e50_path
                + r"}}\\\small Figura. Representación del módulo secante E50: "
                r"la línea discontinua une el origen con el punto de esfuerzo al 50\% "
                r"de la resistencia desviadora máxima.\end{center}"
            ))
            with doc.create(Itemize()) as recommendations:
                recommendations.add_item(
                    "Interprete E50 como la rigidez secante entre el origen y el "
                    "punto correspondiente al 50 % del esfuerzo desviador máximo. "
                    "El procedimiento del ensayo se referencia en "
                    + ("ASTM D4767 (ASTM International, 2020a)."
                       if tipo == "CU" else
                       "ASTM D7181 (ASTM International, 2020b).")
                )
                recommendations.add_item(
                    "Para el diseño, seleccione el valor compatible con el nivel "
                    "de deformación esperado y el confinamiento de campo; revise "
                    "la dispersión entre probetas antes de adoptar un promedio."
                )
                recommendations.add_item(
                    "No extrapole E50 fuera del rango de deformaciones medido sin "
                    "una justificación geotécnica y una evaluación del ingeniero "
                    "responsable."
                )

    with doc.create(Section("Gráficas del ensayo")):
        doc.append(
            "Las figuras se acompañan de su ecuación de interpretación y de los "
            "parámetros usados para construirlas."
        )
        doc.append(NoEscape(r"\clearpage"))
        for image_path, caption in make_report_figs(
                tests, res, tipo, report_tmpdir.name):
            tex_path = os.path.abspath(image_path).replace("\\", "/")
            doc.append(NoEscape(r"\begin{figure}[H]\centering"))
            doc.append(NoEscape(
                r"\includegraphics[width=\textwidth,height=7cm,keepaspectratio]"
                r"{\detokenize{" + tex_path + "}}"
            ))
            doc.append(NoEscape(r"\caption{" + tex(caption) + r"}"))
            doc.append(NoEscape(r"\end{figure}"))
            figure_name = os.path.basename(image_path).split(".")[0]
            if figure_name == "curvas":
                add_step(
                    "Lectura y ecuaciones de la curva esfuerzo-deformación",
                    [
                        r"\sigma_{d,50}=0.5\,\sigma_{d,\max}",
                        r"E_{50}=\frac{\sigma_{d,50}}{\epsilon_{1,50}/100}",
                        r"E_i=100\,b_i,\quad E_{t50}=100\,b_{t50}",
                    ],
                    "La secante une el origen con el punto (ε1,50; σd,50). "
                    "Las pendientes tangentes se ajustan por regresión lineal en "
                    "las ventanas indicadas en la memoria de cada probeta.",
                )
                graph_rows = [
                    (f"#{i} - {test['name']}",
                     f"{test['mod']['e50']:.3f}",
                     f"{test['mod']['s50']:.2f}",
                     f"{test['mod']['E_sec']/1000:.3f}",
                     f"{test['mod']['E_ini']/1000:.3f}",
                     f"{test['mod']['E_tan']/1000:.3f}")
                    for i, test in enumerate(tests, 1)
                ]
                add_table(
                    ["Probeta", "e1,50 (%)", "0.5 sd,max (kPa)", "E50 (MPa)",
                     "Ei (MPa)", "Et50 (MPa)"],
                    graph_rows,
                    "|l|r|r|r|r|r|",
                )
            elif figure_name == "pq":
                add_step(
                    "Ecuaciones de la trayectoria p'-q",
                    [
                        r"p'=\frac{\sigma'_1+\sigma'_3}{2}",
                        r"q=\frac{\sigma'_1-\sigma'_3}{2}",
                        r"q=a+p'\tan(\alpha)",
                        r"\tan(\alpha)="
                        + tex(f"{float(res['coef'][0]):.5f}")
                        + r",\quad a="
                        + tex(f"{float(res['coef'][1]):.3f}")
                        + r"\,\mathrm{kPa}",
                    ],
                    "Los esfuerzos p' y q se expresan en kPa. En el ajuste solo φ, "
                    "la envolvente se fuerza a pasar por el origen.",
                )
            elif figure_name == "mohr":
                add_step(
                    "Ecuaciones de los círculos de Mohr",
                    [
                        r"C=\frac{\sigma'_1+\sigma'_3}{2}=p'",
                        r"R=\frac{\sigma'_1-\sigma'_3}{2}=q",
                        r"(\sigma'-C)^2+\tau^2=R^2",
                        r"\tau=c'+\sigma'\tan(\phi')",
                    ],
                    "C es el centro y R el radio de cada círculo.",
                )
                circle_rows = [
                    (f"#{i} - {test['name']}",
                     f"{test['p_def']:.2f}", f"{test['q_def']:.2f}",
                     f"{test['p_def'] - test['q_def']:.2f}",
                     f"{test['p_def'] + test['q_def']:.2f}")
                    for i, test in enumerate(tests, 1)
                ]
                add_table(
                    ["Probeta", "Centro C (kPa)", "Radio R (kPa)",
                     "Esfuerzo menor efectivo σ'3 (kPa)",
                     "Esfuerzo mayor efectivo σ'1 (kPa)"],
                    circle_rows,
                    "|l|r|r|r|r|",
                )
            elif figure_name == "vol":
                add_step(
                    "Ecuación de la relación de Poisson",
                    [
                        r"\nu=\frac{1}{2}"
                        r"\left(1-\frac{\Delta\epsilon_v}{\Delta\epsilon_1}\right)",
                    ],
                    "εv y ε1 deben estar expresadas en la misma unidad porcentual. "
                    "Verifique que el signo de la deformación volumétrica del archivo "
                    "coincida con la convención adoptada.",
                )
                nu_rows = [
                    (f"#{i} - {test['name']}", f"{test['mod']['nu']:.4f}",
                     test["mod"]["nu_src"])
                    for i, test in enumerate(tests, 1)
                ]
                add_table(
                    ["Probeta", "Relación de Poisson ν utilizada", "Origen del valor"],
                    nu_rows,
                    "|l|r|p{8cm}|",
                )

        with doc.create(Section("Resumen e interpretación geotécnica")):
            result_rows = [
                ("Ángulo de fricción efectivo", f"{res['phi']:.2f} grados"),
                ("Cohesión efectiva", f"{res['c']:.2f} kPa"),
                ("Módulo de elasticidad promedio",
                 f"{np.mean([t['mod']['E'] for t in tests])/1000:.2f} MPa"),
                ("Módulo de corte promedio",
                 f"{np.mean([t['mod']['G'] for t in tests])/1000:.2f} MPa"),
                ("Relación de Poisson promedio",
                 f"{np.mean([t['mod']['nu'] for t in tests]):.3f}"),
            ]
            add_table(["Parámetro", "Resultado"], result_rows,
                      "|p{8cm}|p{7.5cm}|")
            with doc.create(Itemize()) as items:
                for text in interpret(res, tests, tipo, skey):
                    items.add_item(NoEscape(tex(text)))
            for warning in res.get("warns", []):
                doc.append(NoEscape(r"\noindent\textbf{Advertencia:} "))
                doc.append(tex(warning))
                doc.append(NoEscape(r"\par"))
            doc.append(
                "Los parámetros reportados deben ser evaluados por el ingeniero "
                "responsable considerando la calidad de la muestra, las condiciones "
                "de ensayo y los factores de seguridad aplicables conforme a la "
                "Norma Técnica E.050."
            )

    with doc.create(Section("Referencias normativas y bibliográficas")):
        references = [
            ("ASTM International. (2020a). ASTM D4767-11(2020): Standard Test Method for Consolidated Undrained Triaxial Compression Test for Cohesive Soils. ASTM International.",
             "https://doi.org/10.1520/D4767-11R20", "doi:10.1520/D4767-11R20"),
            ("ASTM International. (2020b). ASTM D7181-20: Standard Test Method for Consolidated Drained Triaxial Compression Test for Soils. ASTM International.",
             "https://doi.org/10.1520/D7181-20", "doi:10.1520/D7181-20"),
            ("Bowles, J. E. (1996). Foundation Analysis and Design (5th ed.). McGraw-Hill.",
             "https://search.worldcat.org/search?q=Foundation+Analysis+and+Design+Bowles", "Consultar fuente"),
            ("Das, B. M., & Sobhan, K. (2018). Principles of Geotechnical Engineering (9th ed.). Cengage Learning.",
             "https://www.cengage.com/c/etextbook-principles-of-geotechnical-engineering-9e-das-sobhan/9780357700273/", "Consultar fuente"),
            ("Head, K. H., & Epps, R. J. (2014). Manual of Soil Laboratory Testing. Volume 3: Effective Stress Tests (3rd ed.). Whittles Publishing.",
             "https://search.worldcat.org/search?q=Manual+of+Soil+Laboratory+Testing+Effective+Stress+Tests", "Consultar fuente"),
            ("Holtz, R. D., Kovacs, W. D., & Sheahan, T. C. (2011). An Introduction to Geotechnical Engineering (2nd ed.). Pearson.",
             "https://books.google.com/books?id=EY7hcAAACAAJ", "Consultar fuente"),
            ("Lambe, T. W., & Whitman, R. V. (1969). Soil Mechanics. John Wiley & Sons.",
             "https://search.worldcat.org/title/Soil-mechanics/oclc/1467646534", "Consultar fuente"),
            ("Ministerio de Vivienda, Construcción y Saneamiento. (2018). Norma Técnica E.050: Suelos y Cimentaciones. Reglamento Nacional de Edificaciones.",
             "https://www.gob.pe/es/institucion/vivienda/informes-publicaciones/2309793-reglamento-nacional-de-edificaciones-rne", "Consultar norma"),
        ]
        for reference, url, link_label in references:
            doc.append(NoEscape(r"\noindent\hangindent=1.5em\hangafter=1 "))
            doc.append(tex(reference) + " ")
            doc.append(NoEscape(
                r"\href{" + url + r"}{" + tex(link_label) + r"}\par\medskip"
            ))

    output_base = os.path.splitext(pdf_path)[0]
    try:
        doc.generate_pdf(
            output_base,
            clean=True,
            clean_tex=True,
            compiler="pdflatex",
            compiler_args=["-halt-on-error", "-file-line-error"],
        )
    finally:
        report_tmpdir.cleanup()


# ======================================================================
#  INTERFAZ
# ======================================================================
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Milk_TRIGEO 2026")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(1180, max(780, int(sw * 0.82)))
        h = min(780, max(560, int(sh * 0.82)))
        self.geometry(f"{w}x{h}+{max((sw - w) // 2, 0)}+{max((sh - h) // 2, 0)}")
        self.minsize(720, 520)
        try:
            ttk.Style().theme_use("clam")
        except tk.TclError:
            pass
        self.tests, self.res, self.path = [], None, None

        self.var_tipo = tk.StringVar(value="Auto")
        self.var_def = tk.StringVar(value="14")
        self.var_phi = tk.BooleanVar(value=True)
        self.var_mode = tk.StringVar(value=list(MODES)[0])
        self.var_nu = tk.StringVar(value="0.30")
        self.var_file = tk.StringVar(value="(ningún archivo)")
        self.var_suelo = tk.StringVar(value=SUCS_ITEMS[0])
        self.var_info = {k: tk.StringVar() for k in ("proyecto", "ubic", "prof", "resp")}

        self._show_welcome()

    def _show_welcome(self):
        """Pantalla de presentación inicial; la interfaz de trabajo abre al continuar."""
        self.configure(background="#0B1F33")
        self.welcome = tk.Frame(self, bg="#0B1F33")
        self.welcome.pack(fill="both", expand=True)
        self.splash_accent = tk.Canvas(self.welcome, height=8, bg="#0B1F33",
                                       highlightthickness=0, bd=0)
        self.splash_accent.pack(fill="x", side="top")

        card = tk.Frame(self.welcome, bg="#F7F9FC", padx=24, pady=16)
        card.place(relx=0.5, rely=0.51, anchor="center",
                   relwidth=0.92, relheight=0.92)
        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=2)
        card.grid_columnconfigure(2, weight=1)

        logo1_card = tk.Frame(card, bg="#FFFFFF", padx=8, pady=7,
                              highlightthickness=1, highlightbackground="#DCE5EF")
        logo1_card.grid(row=0, column=0, sticky="n", padx=(4, 14), pady=(0, 6))
        self.welcome_logo1 = tk.Label(logo1_card, bg="#FFFFFF", bd=0)
        self.welcome_logo1.pack()
        tk.Label(logo1_card, text="ENSAYO TRIAXIAL", bg="#FFFFFF", fg="#24415B",
                 font=("Segoe UI", 8, "bold")).pack(pady=(3, 0))

        title_area = tk.Frame(card, bg="#F7F9FC")
        title_area.grid(row=0, column=1, sticky="nsew", padx=6)
        tk.Label(title_area, text="APLICATIVO DE ANÁLISIS GEOTÉCNICO",
                 bg="#DDF3F1", fg="#0A6169", padx=10, pady=5,
                 font=("Segoe UI", 8, "bold")).pack(pady=(6, 13))
        tk.Label(title_area, text="Milk_TRIGEO 2026", bg="#F7F9FC", fg="#102A43",
                 font=("Segoe UI", 27, "bold")).pack()
        tk.Label(title_area, text="Ensayos de compresión triaxial  ·  CD / CU",
                 bg="#F7F9FC", fg="#526579",
                 font=("Segoe UI", 11)).pack(pady=(7, 0))

        logo2_card = tk.Frame(card, bg="#FFFFFF", padx=8, pady=7,
                              highlightthickness=1, highlightbackground="#DCE5EF")
        logo2_card.grid(row=0, column=2, sticky="n", padx=(14, 4), pady=(0, 6))
        self.welcome_logo2 = tk.Label(logo2_card, bg="#FFFFFF", bd=0)
        self.welcome_logo2.pack()

        tk.Frame(card, bg="#DCE5EF", height=1).grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=(15, 16))

        tk.Label(card, text="Caracterización de resistencia y deformabilidad del suelo",
                 bg="#F7F9FC", fg="#102A43", font=("Segoe UI", 15, "bold")
                 ).grid(row=2, column=0, columnspan=3, pady=(0, 6))
        tk.Label(card, text="Carga tus datos de laboratorio, calcula parámetros y genera tu reporte técnico.",
                 bg="#F7F9FC", fg="#526579", font=("Segoe UI", 10),
                 wraplength=680, justify="center"
                 ).grid(row=3, column=0, columnspan=3, pady=(0, 12))

        upload_guide = tk.Frame(card, bg="#F7F9FC")
        upload_guide.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        upload_guide.grid_columnconfigure(0, weight=1)
        upload_guide.grid_columnconfigure(1, weight=1)
        cd_card = tk.Frame(upload_guide, bg="#EAF2FF", padx=13, pady=9)
        cd_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        tk.Label(cd_card, text="EXCEL PARA CD  ·  DRENADO", bg="#EAF2FF",
                 fg="#2357A5", font=("Segoe UI", 9, "bold"), anchor="w"
                 ).pack(anchor="w", pady=(0, 4))
        tk.Label(
            cd_card,
            text="Obligatorio: deformación axial e1 (%) y esfuerzo desviador σd (kPa).\n"
                 "Confinamiento σ3 (kPa): columna pc/σ3 o número en el nombre de la hoja.\n"
                 "Deformación volumétrica εv (%): opcional; se usa para calcular ν medido.",
            bg="#EAF2FF", fg="#344B64", font=("Segoe UI", 8),
            justify="left", anchor="w", wraplength=360,
        ).pack(fill="x", anchor="w")

        cu_card = tk.Frame(upload_guide, bg="#FDF3E7", padx=13, pady=9)
        cu_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        tk.Label(cu_card, text="EXCEL PARA CU  ·  NO DRENADO", bg="#FDF3E7",
                 fg="#9A5B1E", font=("Segoe UI", 9, "bold"), anchor="w"
                 ).pack(anchor="w", pady=(0, 4))
        tk.Label(
            cu_card,
            text="Obligatorio: e1 (%), σd (kPa) y presión de poros u (kPa).\n"
                 "Confinamiento σ3 (kPa): columna pc/σ3 o número en el nombre de la hoja.\n"
                 "En CU no se requiere εv; se adopta volumen constante (ν = 0.50).",
            bg="#FDF3E7", fg="#5B4A3A", font=("Segoe UI", 8),
            justify="left", anchor="w", wraplength=360,
        ).pack(fill="x", anchor="w")

        tags = tk.Frame(card, bg="#F7F9FC")
        tags.grid(row=5, column=0, columnspan=3, pady=(0, 5))
        for text, color in (("E50  ·  MÓDULO SECANTE", "#E1F3F1"),
                            ("MOHR-COULOMB", "#E6EDF7")):
            tk.Label(tags, text=text, bg=color, fg="#17324D", padx=13, pady=8,
                     font=("Segoe UI", 8, "bold")).pack(side="left", padx=6)

        self.splash_anim = tk.Canvas(card, height=48, bg="#F7F9FC",
                                     highlightthickness=0, bd=0)
        self.splash_anim.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(0, 2))
        self._splash_t0 = time.perf_counter()

        self.start_button = tk.Button(
            card, text="COMENZAR  →", command=self._start_application,
            bg="#0E7C86", fg="#FFFFFF", activebackground="#0A6169",
            activeforeground="#FFFFFF", relief="flat", bd=0,
            padx=34, pady=12, cursor="hand2", font=("Segoe UI", 11, "bold"),
        )
        self.start_button.grid(row=7, column=0, columnspan=3, pady=(0, 7))
        self.start_button.bind("<Enter>", lambda _e: self._fade_button("#0A6169"))
        self.start_button.bind("<Leave>", lambda _e: self._fade_button("#0E7C86"))
        self.bind("<Return>", lambda _e: self._start_application())
        tk.Label(card, text="Ing. A. Milkenson  |  Mecánica de Suelos  |  © 2026",
                 bg="#F7F9FC", fg="#7B8794", font=("Segoe UI", 8)
                 ).grid(row=8, column=0, columnspan=3, pady=(2, 0))

        self._load_welcome_logos()
        self._animate_splash()
        self._animate_splash_accent()

    # ---------- animaciones suaves (basadas en tiempo, ~30 fps) ----------
    @staticmethod
    def _hex_rgb(color):
        color = color.lstrip("#")
        return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))

    @classmethod
    def _mix(cls, c1, c2, t):
        """Mezcla lineal entre dos colores hex (t = 0 -> c1, t = 1 -> c2)."""
        t = min(max(t, 0.0), 1.0)
        r1, r2 = cls._hex_rgb(c1), cls._hex_rgb(c2)
        return "#%02x%02x%02x" % tuple(round(a + (b - a) * t) for a, b in zip(r1, r2))

    @staticmethod
    def _ease(t):
        """Suavizado cúbico de entrada y salida."""
        t = min(max(t, 0.0), 1.0)
        return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2

    def _fade_button(self, target, steps=6, delay=18):
        """Transición suave del color del botón al pasar el cursor."""
        if getattr(self, "_btn_job", None):
            try:
                self.after_cancel(self._btn_job)
            except tk.TclError:
                pass
        if not self.start_button.winfo_exists():
            return
        start = self.start_button.cget("bg")

        def tick(i=1):
            if not self.start_button.winfo_exists():
                return
            self.start_button.configure(bg=self._mix(start, target, i / steps))
            if i < steps:
                self._btn_job = self.after(delay, lambda: tick(i + 1))

        tick()

    def _animate_splash_accent(self):
        """Franja superior con degradado marino-turquesa que se desplaza lentamente."""
        if not hasattr(self, "splash_accent") or not self.splash_accent.winfo_exists():
            return
        canvas = self.splash_accent
        width = max(canvas.winfo_width(), 400)
        stripe = 6
        n = width // stripe + 2
        palette = ("#0B3C5D", "#0E7C86", "#3FBFAD", "#0E7C86")
        phase = (time.perf_counter() / 14.0) % 1.0          # un ciclo cada 14 s
        if not hasattr(self, "_accent_items") or len(self._accent_items) != n:
            canvas.delete("all")
            self._accent_items = [
                canvas.create_rectangle(i * stripe, 0, i * stripe + stripe + 1, 8,
                                        fill="#0E7C86", outline="")
                for i in range(n)
            ]
        k = len(palette)
        for i, item in enumerate(self._accent_items):
            pos = ((i / n) * 1.5 - phase) % 1.0 * k
            idx = int(pos) % k
            color = self._mix(palette[idx], palette[(idx + 1) % k], pos - int(pos))
            canvas.itemconfigure(item, fill=color)
        self._splash_accent_job = self.after(50, self._animate_splash_accent)

    def _animate_splash(self):
        """Curva esfuerzo-deformación que se dibuja con suavidad, se mantiene y se desvanece."""
        if not hasattr(self, "splash_anim") or not self.splash_anim.winfo_exists():
            return
        canvas = self.splash_anim
        bg = "#F7F9FC"
        width = max(canvas.winfo_width(), 300)
        height = max(canvas.winfo_height(), 46)
        left, right = 28, width - 26
        base, top = height - 8, 8

        draw_t, hold_t, fade_t = 3.0, 1.2, 1.0
        cycle = draw_t + hold_t + fade_t
        t = (time.perf_counter() - self._splash_t0) % cycle
        progress = self._ease(t / draw_t) if t < draw_t else 1.0
        fade = 0.0 if t < draw_t + hold_t else (t - draw_t - hold_t) / fade_t
        fade = self._ease(fade)

        count = 160
        shown = progress * (count - 1)
        full = int(shown)
        pts = []
        for i in range(min(full + 2, count)):
            f = i / (count - 1)
            x = left + (right - left) * f
            y = base - (base - top) * (1 - np.exp(-3.2 * f))
            pts.append((x, y))
        if full + 1 < count and len(pts) >= 2:           # punto parcial interpolado
            frac = shown - full
            (x0, y0), (x1, y1) = pts[-2], pts[-1]
            pts[-1] = (x0 + (x1 - x0) * frac, y0 + (y1 - y0) * frac)

        canvas.delete("all")
        axis = self._mix("#C8D5E3", bg, fade * 0.0)
        canvas.create_line(left, base, right, base, fill=axis, width=1)
        canvas.create_line(left, base, left, top, fill=axis, width=1)
        canvas.create_text(left - 6, top + 1, text="σd", anchor="e",
                           fill="#63758A", font=("Segoe UI", 8, "bold"))
        canvas.create_text(right, base + 2, text="e1", anchor="se",
                           fill="#63758A", font=("Segoe UI", 8, "bold"))

        if len(pts) >= 2:
            line_color = self._mix("#0E7C86", bg, fade)
            canvas.create_line(*[c for p in pts for c in p], fill=line_color,
                               width=3, capstyle="round", joinstyle="round")
            tip_x, tip_y = pts[-1]
            halo = self._mix("#3FBFAD", bg, 0.65 + 0.35 * fade)
            dot = self._mix("#0B3C5D", bg, fade)
            canvas.create_oval(tip_x - 9, tip_y - 9, tip_x + 9, tip_y + 9,
                               fill=halo, outline="")
            canvas.create_oval(tip_x - 4.5, tip_y - 4.5, tip_x + 4.5, tip_y + 4.5,
                               fill=dot, outline="#FFFFFF", width=1)
        self._splash_anim_job = self.after(33, self._animate_splash)

    def _load_welcome_logos(self):
        self._welcome_logo_refs = []
        try:
            from PIL import Image, ImageTk
            for label, filename, bounds in (
                (self.welcome_logo1, "img triaxial 1.webp", (116, 92)),
                (self.welcome_logo2, "img logo 2.png", (140, 92)),
            ):
                logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
                if not os.path.isfile(logo_path):
                    continue
                try:
                    with Image.open(logo_path) as source:
                        image = source.convert("RGBA")
                    resampling = getattr(Image, "Resampling", Image)
                    image.thumbnail(bounds, resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(image, master=self)
                    label.configure(image=photo)
                    self._welcome_logo_refs.append(photo)
                except Exception:
                    continue
        except ImportError:
            pass

    def _start_application(self):
        for job_name in ("_splash_anim_job", "_splash_accent_job"):
            job = getattr(self, job_name, None)
            if not job:
                continue
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        if hasattr(self, "welcome") and self.welcome.winfo_exists():
            self.welcome.destroy()
        self.unbind("<Return>")
        self.configure(background=ttk.Style().lookup("TFrame", "background") or "#F0F0F0")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = int(sw * 0.92), int(sh * 0.86)
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{max((sh - h) // 2 - 20, 0)}")
        self.minsize(1000, 640)

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned, padding=6)
        right = ttk.Frame(paned, padding=2)
        paned.add(left, weight=0)
        paned.add(right, weight=1)
        self._build_left(left)
        self._build_right(right)
        ttk.Label(
            self,
            text="© 2026 Ing. A. Milkenson | Mecánica de Suelos",
            anchor="center",
            foreground="#64748B",
        ).pack(fill="x", pady=(0, 4))

    # ---------- construcción ----------
    def _build_left(self, left):
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        left.rowconfigure(6, weight=1)
        ttk.Button(left, text="📂 Cargar archivo (.xlsx / .csv)",
                   command=self.load).grid(row=0, column=0, sticky="ew")
        ttk.Label(left, textvariable=self.var_file, wraplength=360,
                  foreground="#555").grid(row=1, column=0, sticky="w", pady=(2, 6))

        nb = ttk.Notebook(left)
        nb.grid(row=2, column=0, sticky="nsew")

        # --- pestaña Ensayos
        t1 = ttk.Frame(nb, padding=6)
        nb.add(t1, text="Ensayos")
        t1.columnconfigure(0, weight=1); t1.rowconfigure(1, weight=1)
        ttk.Label(t1, text="Doble clic en σ3 para editar:").grid(row=0, column=0, sticky="w")
        self.tree = ttk.Treeview(t1, columns=("n", "s3", "pts", "u", "ev"), show="headings",
                                 selectmode="extended")
        for c, t, wd in (("n", "Hoja", 130), ("s3", "σ3 (kPa)", 70), ("pts", "Pts", 40),
                         ("u", "u", 35), ("ev", "εv", 35)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=wd, minwidth=30, anchor="center" if c != "n" else "w")
        self.tree.grid(row=1, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", self.edit_pc)
        ttk.Button(t1, text="Quitar seleccionado", command=self.remove
                   ).grid(row=2, column=0, sticky="w", pady=4)

        # --- pestaña Parámetros
        t2 = ttk.Frame(nb, padding=8)
        nb.add(t2, text="Parámetros")
        t2.columnconfigure(1, weight=1)
        rows = [("Tipo de ensayo:", ttk.Combobox(
                    t2, textvariable=self.var_tipo, state="readonly",
                    values=["Auto", "CD (consolidado drenado)", "CU (consolidado no drenado)"])),
                ("Deformación de falla e1 (%):", ttk.Entry(t2, textvariable=self.var_def)),
                ("Módulo E a usar:", ttk.Combobox(
                    t2, textvariable=self.var_mode, state="readonly", values=list(MODES))),
                ("ν asumido (si no hay εv):", ttk.Entry(t2, textvariable=self.var_nu))]
        for i, (txt, wdg) in enumerate(rows):
            ttk.Label(t2, text=txt).grid(row=i, column=0, sticky="w", pady=4, padx=(0, 6))
            wdg.grid(row=i, column=1, sticky="ew", pady=4)
        ttk.Checkbutton(t2, text="Solo φ (c = 0)", variable=self.var_phi
                        ).grid(row=len(rows), column=0, columnspan=2, sticky="w", pady=4)
        ttk.Label(t2, wraplength=330, foreground="#555", font=("TkDefaultFont", 8),
                  text="εv (deformación volumétrica) se detecta automáticamente si el archivo "
                       "tiene esa columna (contracción positiva). En CU se usa ν = 0.5."
                  ).grid(row=len(rows) + 1, column=0, columnspan=2, sticky="w")

        # --- pestaña Material / Proyecto
        t3 = ttk.Frame(nb, padding=8)
        nb.add(t3, text="Material / Proyecto")
        t3.columnconfigure(1, weight=1)
        ttk.Label(t3, text="Material (SUCS, E.050):").grid(row=0, column=0, columnspan=2, sticky="w")
        cb = ttk.Combobox(t3, textvariable=self.var_suelo, state="readonly", values=SUCS_ITEMS)
        cb.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 2))
        cb.bind("<<ComboboxSelected>>", self.on_suelo)
        self.lbl_suelo = ttk.Label(t3, text="", wraplength=330, foreground="#0a5")
        self.lbl_suelo.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 8))
        for i, (k, txt) in enumerate((("proyecto", "Proyecto:"), ("ubic", "Ubicación / calicata:"),
                                      ("prof", "Profundidad:"), ("resp", "Responsable:"))):
            ttk.Label(t3, text=txt).grid(row=3 + i, column=0, sticky="w", pady=3)
            ttk.Entry(t3, textvariable=self.var_info[k]).grid(row=3 + i, column=1,
                                                              sticky="ew", pady=3, padx=(6, 0))

        # --- botones de acción
        bf = ttk.Frame(left)
        bf.grid(row=3, column=0, sticky="ew", pady=(8, 2))
        bf.columnconfigure((0, 1), weight=1)
        ttk.Button(bf, text="▶ Calcular y graficar", command=self.run
                   ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(bf, text="📄 Generar reporte PDF", command=self.make_pdf
                   ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(bf, text="💾 Exportar .xlsx", command=self.export_xlsx
                   ).grid(row=2, column=0, sticky="ew", padx=(0, 2), pady=2)
        ttk.Button(bf, text="🖼 Guardar gráfico", command=self.save_fig
                   ).grid(row=2, column=1, sticky="ew", padx=(2, 0), pady=2)

        self.lbl_res = ttk.Label(left, text="", font=("TkDefaultFont", 12, "bold"),
                                 foreground="#0a5", wraplength=370)
        self.lbl_res.grid(row=5, column=0, sticky="w", pady=4)
        lf = ttk.Frame(left)
        lf.grid(row=6, column=0, sticky="nsew")
        lf.columnconfigure(0, weight=1); lf.rowconfigure(0, weight=1)
        self.log = tk.Text(lf, width=44, height=7, wrap="word", state="disabled",
                           font=("TkDefaultFont", 8))
        self.log.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(lf, command=self.log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log.config(yscrollcommand=sb.set)

    def _build_right(self, right):
        self.nb_r = ttk.Notebook(right)
        self.nb_r.pack(fill="both", expand=True)
        g = ttk.Frame(self.nb_r)
        self.nb_r.add(g, text="Gráficos")
        self.fig = Figure(figsize=(10, 6), dpi=100, layout="constrained")
        self.canvas = FigureCanvasTkAgg(self.fig, master=g)
        tb = NavigationToolbar2Tk(self.canvas, g, pack_toolbar=False)
        tb.pack(side="bottom", fill="x")
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        r = ttk.Frame(self.nb_r, padding=6)
        self.nb_r.add(r, text="Resultados")
        r.columnconfigure(0, weight=1); r.rowconfigure(1, weight=1)
        self.lbl_sum = ttk.Label(r, text="Calcule para ver los resultados.",
                                 font=("TkDefaultFont", 11, "bold"))
        self.lbl_sum.grid(row=0, column=0, sticky="w", pady=(0, 6))
        cols = ("n", "s3", "pf", "qf", "smax", "esec", "eini", "etan", "nu", "g")
        heads = ("Ensayo", "σ3 (kPa)", "p' falla", "q falla", "σd máx", "E50 (MPa)",
                 "Ei (MPa)", "Et50 (MPa)", "ν", "G (MPa)")
        self.rt = ttk.Treeview(r, columns=cols, show="headings")
        for c, h in zip(cols, heads):
            self.rt.heading(c, text=h)
            self.rt.column(c, width=95 if c != "n" else 150, anchor="center", stretch=True)
        self.rt.grid(row=1, column=0, sticky="nsew")
        xs = ttk.Scrollbar(r, orient="horizontal", command=self.rt.xview)
        xs.grid(row=2, column=0, sticky="ew")
        self.rt.config(xscrollcommand=xs.set)

    # ---------- utilidades ----------
    def say(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def tipo_sel(self):
        v = self.var_tipo.get()
        return v[:2] if v != "Auto" else None

    def on_suelo(self, _=None):
        k = sucs_key(self.var_suelo.get())
        if not k:
            self.lbl_suelo.config(text="")
        elif SUCS[k][1] is None:
            self.lbl_suelo.config(text=f"{k}: suelo orgánico, sin rango típico de φ.")
        else:
            self.lbl_suelo.config(text=f"{k}: φ referencial {SUCS[k][1]}° – {SUCS[k][2]}°")

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, t in enumerate(self.tests):
            pc = "?" if t["pc"] is None else f"{t['pc']:g}"
            has_u = "✓" if "u" in t["df"].columns else "–"
            has_v = "✓" if "ev" in t["df"].columns else "–"
            self.tree.insert("", "end", iid=str(i),
                             values=(t["name"], pc, len(t["df"]), has_u, has_v))

    # ---------- acciones ----------
    def load(self):
        path = filedialog.askopenfilename(
            title="Seleccione el archivo de ensayos",
            filetypes=[("Excel / CSV", "*.xlsx *.xlsm *.xls *.csv *.txt"), ("Todos", "*.*")])
        if not path:
            return
        try:
            tests, warns, tipo = read_tests(path)
        except Exception as e:
            messagebox.showerror("Error al leer", str(e))
            return
        self.path, self.tests = path, tests
        self.var_file.set(os.path.basename(path))
        if tipo:
            self.var_tipo.set("CD (consolidado drenado)" if tipo == "CD"
                              else "CU (consolidado no drenado)")
        else:
            self.var_tipo.set("CU (consolidado no drenado)"
                              if all("u" in t["df"].columns for t in tests) else "Auto")
        self.log.config(state="normal"); self.log.delete("1.0", "end")
        self.log.config(state="disabled")
        self.say(f"Archivo: {os.path.basename(path)}")
        self.say(f"{len(tests)} ensayo(s) leído(s); tipo detectado: {tipo or 'no detectado'}")
        for w in warns:
            self.say("⚠ " + w)
        for t in tests:
            if t["pc"] is None:
                t["pc"] = simpledialog.askfloat(
                    "Confinamiento", f"σ3 (kPa) del ensayo '{t['name']}':", parent=self)
        self.refresh_tree()
        self.res = None
        self.fig.clear(); self.canvas.draw()
        self.lbl_res.config(text="")
        self.rt.delete(*self.rt.get_children())

    def edit_pc(self, event):
        if self.tree.identify_column(event.x) != "#2":
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        t = self.tests[int(iid)]
        v = simpledialog.askfloat("σ3", f"σ3 (kPa) de '{t['name']}':",
                                  initialvalue=t["pc"], parent=self)
        if v is not None:
            t["pc"] = v
            self.refresh_tree()

    def remove(self):
        for i in sorted((int(i) for i in self.tree.selection()), reverse=True):
            del self.tests[i]
        self.refresh_tree()

    def run(self):
        if not self.tests:
            messagebox.showwarning("Sin datos", "Primero cargue un archivo.")
            return
        if any(t["pc"] is None for t in self.tests):
            messagebox.showwarning("Falta σ3", "Hay ensayos sin σ3 (doble clic para editar).")
            return
        try:
            deform = float(self.var_def.get().replace(",", "."))
            nu_as = float(self.var_nu.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Error", "Deformación e1 o ν inválidos.")
            return
        if not 0 <= nu_as <= 0.5:
            messagebox.showerror("Error", "El ν asumido debe estar entre 0 y 0.5.")
            return
        tipo = self.tipo_sel()
        if tipo is None:
            tipo = "CU" if all("u" in t["df"].columns for t in self.tests) else "CD"
            self.say(f"Tipo asumido: {tipo}")
        try:
            res = compute(self.tests, tipo, deform, self.var_phi.get(),
                          MODES[self.var_mode.get()], nu_as)
        except Exception as e:
            messagebox.showerror("Error de cálculo", str(e))
            return
        res["deform"], res["tipo"] = deform, tipo
        self.res = res
        for w in res["warns"]:
            self.say("⚠ " + w)
        draw(self.fig, self.tests, res, tipo)
        self.canvas.draw()
        self.lbl_res.config(text=f"φ = {res['phi']:.2f}°   c = {res['c']:.2f} kPa")
        self.say(f"φ = {res['phi']:.2f}°, c = {res['c']:.2f} kPa")
        self.fill_results(res, tipo)
        k = sucs_key(self.var_suelo.get())
        if k and SUCS[k][1] is not None:
            self.say(f"SUCS {k}: φ referencial {SUCS[k][1]}°–{SUCS[k][2]}°")

    def fill_results(self, res, tipo):
        self.rt.delete(*self.rt.get_children())
        for t in self.tests:
            m = t["mod"]
            self.rt.insert("", "end", values=(
                t["name"], f"{t['pc']:g}", f"{t['p_def']:.1f}", f"{t['q_def']:.1f}",
                f"{m['smax']:.1f}", f"{m['E_sec'] / 1000:.2f}", f"{m['E_ini'] / 1000:.2f}",
                f"{m['E_tan'] / 1000:.2f}", f"{m['nu']:.3f}", f"{m['G'] / 1000:.2f}"))
        src = self.tests[0]["mod"]["nu_src"]
        self.lbl_sum.config(
            text=f"φ = {res['phi']:.2f}°   c = {res['c']:.2f} kPa   |   "
                 f"E usado: {MODE_NAME[res['mode']]}   |   ν {src}")

    def export_xlsx(self):
        if not self.res:
            messagebox.showwarning("Sin resultados", "Primero calcule.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".xlsx",
                                            filetypes=[("Excel", "*.xlsx")],
                                            initialfile="resultados_triaxial.xlsx")
        if not path:
            return
        r = self.res
        with pd.ExcelWriter(path) as xw:
            pd.DataFrame({
                "σ3 (kPa)": [t["pc"] for t in self.tests],
                "p' falla (kPa)": r["p"], "q falla (kPa)": r["q"],
                "σd falla (kPa)": [t["desv_def"] for t in self.tests],
                "σd máx (kPa)": [t["mod"]["smax"] for t in self.tests],
                "E50 (kPa)": [t["mod"]["E_sec"] for t in self.tests],
                "Ei (kPa)": [t["mod"]["E_ini"] for t in self.tests],
                "Et50 (kPa)": [t["mod"]["E_tan"] for t in self.tests],
                "ν": [t["mod"]["nu"] for t in self.tests],
                "G (kPa)": [t["mod"]["G"] for t in self.tests],
            }).to_excel(xw, sheet_name="Resumen", index=False)
            pd.DataFrame({"Parámetro": ["Tipo", "Material SUCS", "e1 (%)", "φ (°)", "c (kPa)",
                                        "Módulo usado"],
                          "Valor": [r["tipo"], self.var_suelo.get(), r["deform"], r["phi"],
                                    r["c"], MODE_NAME[r["mode"]]]}
                         ).to_excel(xw, sheet_name="Resumen", index=False, startcol=12)
            for t in self.tests:
                t["calc"].to_excel(xw, sheet_name=re.sub(r"[\[\]:*?/\\]", "_", str(t["name"]))[:31],
                                   index=False)
        self.say(f"Exportado: {path}")

    def save_fig(self):
        if not self.res:
            messagebox.showwarning("Sin gráfico", "Primero calcule.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".png",
                                            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf")],
                                            initialfile="triaxial.png")
        if path:
            self.fig.savefig(path, dpi=300)
            self.say(f"Gráfico guardado: {path}")

    def make_pdf(self):
        if not self.res:
            messagebox.showwarning("Sin resultados", "Primero calcule (▶ Calcular y graficar).")
            return
        path = filedialog.asksaveasfilename(defaultextension=".pdf",
                                            filetypes=[("PDF", "*.pdf")],
                                            initialfile="reporte_triaxial.pdf")
        if not path:
            return
        info = {k: v.get().strip() for k, v in self.var_info.items()}
        self.config(cursor="watch"); self.update_idletasks()
        try:
            _build_report_reportlab(
                path, self.tests, self.res, self.res["tipo"], info,
                sucs_key(self.var_suelo.get()))
        except Exception as e:
            self.config(cursor="")
            messagebox.showerror(
                "Error al generar PDF",
                f"Ocurrió un error al generar el reporte PDF:\n\n{e}")
            return
        self.config(cursor="")
        self.say(f"Reporte PDF: {path}")
        messagebox.showinfo("PDF generado", "Reporte PDF y memoria de cálculo generados correctamente ✔")


if __name__ == "__main__":
    App().mainloop()