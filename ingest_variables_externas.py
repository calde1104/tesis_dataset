import os
import re
import time
import unicodedata
import requests
import pandas as pd
import holidays
from datetime import date
from dateutil.relativedelta import relativedelta

VENTAS_EXCEL = "./Datos Originales.xlsx"

CSV_OUTPUT_DIR = "./output_csv"

START_DATE = date(2021, 1, 1)
END_DATE   = date.today().replace(day=1)

WEATHER_LAT  = -25.2867
WEATHER_LON  = -57.6470
WEATHER_CITY = "Asuncion"

COL_ANIO     = "anio"
COL_MES      = "mes"
COL_SKU      = "sku"
COL_CATEGORIA = "categoria"
COL_EMPRESA  = "empresa"
COL_MARCA    = "marca"
COL_UNIDADES = "unidades vendidas"
COL_FACTURA  = "facturación"

MAPEO_COLUMNAS = {
    "año":         "anio",
    "ano":         "anio",
    "facturación": "monto_facturado",
    "facturacion": "monto_facturado",
}

CLAVE_SERIE = ["sku", "marca", "empresa"]

def mes_range(start: date, end: date) -> list:
    months = []
    cur = start.replace(day=1)
    while cur <= end.replace(day=1):
        months.append(cur)
        cur += relativedelta(months=1)
    return months

def save_csv(df: pd.DataFrame, nombre: str) -> str:
    os.makedirs(CSV_OUTPUT_DIR, exist_ok=True)
    path = os.path.join(CSV_OUTPUT_DIR, f"{nombre}.csv")
    df.to_csv(path, index=False)
    print(f"  [OK] {os.path.abspath(path)}")
    return path

def get_json(url: str, params: dict = None, timeout: int = 30) -> dict | None:
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [ERROR] {url[:60]}... → {e}")
        return None

def _expandir_anual_a_mensual(df: pd.DataFrame, col: str) -> pd.DataFrame:
    filas = []
    for _, row in df.iterrows():
        for m in range(1, 13):
            filas.append({"anio": int(row["anio"]), "mes": m, col: row[col]})
    return pd.DataFrame(filas)

def _imf_dataservices(series_key: str, col_name: str,
                       start: str, end: str) -> pd.DataFrame:
    dataset = "CPI" if "PCPI" in series_key else "IFS"
    url = f"http://dataservices.imf.org/REST/SDMX_JSON.svc/CompactData/{dataset}/{series_key}"
    try:
        r = requests.get(url, params={"startPeriod": start, "endPeriod": end}, timeout=30)
        r.raise_for_status()
        data = r.json()
        obs_raw = data["CompactData"]["DataSet"]["Series"]["Obs"]
        obs_list = [obs_raw] if isinstance(obs_raw, dict) else obs_raw
        rows = []
        for obs in obs_list:
            periodo = obs.get("@TIME_PERIOD", "")
            valor   = obs.get("@OBS_VALUE")
            if periodo and valor is not None:
                try:
                    rows.append({
                        "anio": int(periodo[:4]),
                        "mes":  int(periodo[5:7]),
                        col_name: float(valor)
                    })
                except Exception:
                    pass
        if rows:
            df = pd.DataFrame(rows)
            print(f"  [OK] {col_name}: {len(df)} meses")
            return df
        else:
            print(f"  [VACÍO] {col_name}: sin observaciones en el rango")
    except Exception as e:
        print(f"  [ERROR] {col_name} (dataservices): {e}")
    return pd.DataFrame()

def _imf_datamapper(indicator: str, col_name: str) -> pd.DataFrame:
    url = f"https://www.imf.org/external/datamapper/api/v1/{indicator}/PRY"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        valores = r.json().get("values", {}).get(indicator, {}).get("PRY", {})
        rows = [
            {"anio": int(a), col_name: float(v)}
            for a, v in valores.items() if v is not None
        ]
        if rows:
            df = pd.DataFrame(rows)
            df = df[df["anio"] >= START_DATE.year]
            df = _expandir_anual_a_mensual(df, col_name)
            print(f"  [OK] {col_name}: {df['anio'].nunique()} años")
            return df
    except Exception as e:
        print(f"  [ERROR] {col_name} (datamapper): {e}")
    return pd.DataFrame()

def _worldbank(indicator: str, col_name: str) -> pd.DataFrame:
    url  = f"https://api.worldbank.org/v2/country/PY/indicator/{indicator}"
    data = get_json(url, params={"format": "json", "per_page": 100, "mrv": 10})
    if data and len(data) > 1 and data[1]:
        rows = [
            {"anio": int(d["date"]), col_name: d["value"]}
            for d in data[1] if d["value"] is not None
        ]
        if rows:
            df = pd.DataFrame(rows)
            df = df[df["anio"] >= START_DATE.year]
            df = _expandir_anual_a_mensual(df, col_name)
            print(f"  [OK] {col_name}: {df['anio'].nunique()} años")
            return df
    return pd.DataFrame()

def generar_macroeconomico() -> pd.DataFrame:
    print("\n[1/4] Variables macroeconómicas")

    start_str = START_DATE.strftime("%Y-%m")
    end_str   = (END_DATE - relativedelta(months=1)).strftime("%Y-%m")
    dfs = []

    print("  IMF dataservices (mensual)...")
    for col, key in [
        ("ipc_indice",         "M.PY.PCPI_IX"),
        ("tipo_cambio_pyg_usd","M.PY.ENDA_XDC_USD_RATE"),
    ]:
        df = _imf_dataservices(key, col, start_str, end_str)
        if not df.empty:
            dfs.append(df)
        time.sleep(1)

    cols_ya_obtenidos = [list(d.columns) for d in dfs]
    cols_ya_obtenidos = [c for sub in cols_ya_obtenidos for c in sub]
    if "ipc_indice" not in cols_ya_obtenidos:
        print("  [FALLBACK] IPC via World Bank...")
        df = _worldbank("FP.CPI.TOTL", "ipc_indice")
        if not df.empty:
            dfs.append(df)
    if "tipo_cambio_pyg_usd" not in cols_ya_obtenidos:
        print("  [FALLBACK] Tipo de cambio via World Bank...")
        df = _worldbank("PA.NUS.FCRF", "tipo_cambio_pyg_usd")
        if not df.empty:
            dfs.append(df)

    print("  IMF DataMapper (anual)...")
    for col, ind in [
        ("ipc_var_interanual", "PCPIPCH"),
        ("pbi_crecimiento",    "NGDP_RPCH"),
        ("tasa_desempleo",     "LUR"),
    ]:
        df = _imf_datamapper(ind, col)
        if not df.empty:
            dfs.append(df)
        time.sleep(0.5)

    print("  World Bank (anual)...")
    for col, ind in [
        ("remesas_usd",       "BX.TRF.PWKR.CD.DT"),
        ("inversion_ext_usd", "BX.KLT.DINV.CD.WD"),
    ]:
        df = _worldbank(ind, col)
        if not df.empty:
            dfs.append(df)
        time.sleep(0.5)

    if not dfs:
        print("  [INFO] Sin datos macro — revisá tu conexión a internet.")
        return pd.DataFrame()

    from functools import reduce
    resultado = reduce(
        lambda l, r: pd.merge(l, r, on=["anio", "mes"], how="outer"), dfs
    )
    resultado = resultado.sort_values(["anio", "mes"]).reset_index(drop=True)
    resultado = resultado[
        (resultado["anio"] > START_DATE.year) |
        ((resultado["anio"] == START_DATE.year) & (resultado["mes"] >= START_DATE.month))
    ]
    save_csv(resultado, "macroeconomico_mensual")
    return resultado

def generar_clima() -> pd.DataFrame:
    print("\n[2/4] Open-Meteo — Clima mensual")

    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude":   WEATHER_LAT,
        "longitude":  WEATHER_LON,
        "start_date": START_DATE.strftime("%Y-%m-%d"),
        "end_date":   (END_DATE - relativedelta(days=1)).strftime("%Y-%m-%d"),
        "daily":      "temperature_2m_max,temperature_2m_mean,precipitation_sum",
        "timezone":   "America/Asuncion",
    }

    data = get_json(url, params=params, timeout=40)
    if not data:
        return pd.DataFrame()

    df_d = pd.DataFrame({
        "fecha":            pd.to_datetime(data["daily"]["time"]),
        "temp_max":         data["daily"]["temperature_2m_max"],
        "temp_media":       data["daily"]["temperature_2m_mean"],
        "precipitacion_mm": data["daily"]["precipitation_sum"],
    })
    df_d["anio"] = df_d["fecha"].dt.year
    df_d["mes"]  = df_d["fecha"].dt.month

    df_m = df_d.groupby(["anio", "mes"]).agg(
        temp_max_promedio   = ("temp_max",         "mean"),
        temp_media_promedio = ("temp_media",        "mean"),
        precipitacion_mm    = ("precipitacion_mm",  "sum"),
    ).reset_index().round(2)
    df_m["ciudad"] = WEATHER_CITY

    print(f"  [OK] {len(df_m)} meses de datos climáticos")
    save_csv(df_m, "clima_mensual")
    return df_m

def generar_calendario() -> pd.DataFrame:
    print("\n[3/4] Calendario — Feriados y eventos Paraguay")

    py_hols = holidays.Paraguay(years=range(START_DATE.year, END_DATE.year + 1))

    festivos = {
        (1,  1):  "Año Nuevo",
        (5, 14):  "Dia de la Madre (PY)",
        (6, 17):  "Dia del Padre",
        (6, 24):  "San Juan",
        (12, 25): "Navidad",
    }

    filas = []
    for d in mes_range(START_DATE, END_DATE):
        anio, mes = d.year, d.month
        feriados_mes  = [x for x in py_hols if x.year == anio and x.month == mes]
        festivos_mes  = [n for (m, _), n in festivos.items() if m == mes]
        filas.append({
            "anio":                    anio,
            "mes":                     mes,
            "cantidad_feriados":       len(feriados_mes),
            "tiene_festivo_comercial": int(bool(festivos_mes)),
            "nombre_festivo":          "; ".join(festivos_mes) if festivos_mes else "",
            "quincena_aguinaldo":      int(mes == 12),
            "inicio_ciclo_escolar":    int(mes == 2),
            "ciclo_cobro_mensual":     1,
        })

    df = pd.DataFrame(filas)
    print(f"  [OK] {len(df)} meses de calendario")
    save_csv(df, "calendario_mensual")
    return df

def normalizar_columna(nombre) -> str:
    texto = unicodedata.normalize("NFC", str(nombre)).strip().lower()
    if texto in MAPEO_COLUMNAS:
        return MAPEO_COLUMNAS[texto]
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", texto).strip("_")

def normalizar_sku(valor) -> str:
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()

def agregar_por_mes(df: pd.DataFrame) -> pd.DataFrame:
    clave = CLAVE_SERIE + ["anio", "mes"]
    cantidades = ["unidades_vendidas", "monto_facturado"]
    orden = df.sort_values(
        clave + cantidades,
        ascending=[True] * len(clave) + [False, False],
        kind="mergesort",
    )
    sumas = orden.groupby(clave, as_index=False, sort=False)[cantidades].sum()
    sumas["monto_facturado"] = sumas["monto_facturado"].round(2)
    descriptivas = orden.drop_duplicates(clave).drop(columns=cantidades)
    mensual = descriptivas.merge(sumas, on=clave, how="left", validate="one_to_one")
    return mensual[list(df.columns)].reset_index(drop=True)

def agregar_rezagos(df: pd.DataFrame) -> pd.DataFrame:
    periodo = df["anio"] * 12 + df["mes"]
    claves = [df[c] for c in CLAVE_SERIE]
    serie = pd.Series(
        df["unidades_vendidas"].to_numpy(),
        index=pd.MultiIndex.from_arrays(claves + [periodo]),
    )

    def rezago(k: int) -> pd.Series:
        buscado = pd.MultiIndex.from_arrays(claves + [periodo - k])
        return pd.Series(serie.reindex(buscado).to_numpy(), index=df.index)

    for k in (1, 2, 12):
        df[f"lag_{k}"] = rezago(k)
    df["ma_3m"] = pd.concat([rezago(k) for k in (1, 2, 3)], axis=1).mean(axis=1).round(2)
    return df

def generar_dataset_enriquecido(df_macro, df_clima, df_cal):
    print("\n[4/4] Dataset enriquecido")

    if not os.path.exists(VENTAS_EXCEL):
        print(f"  [INFO] Excel de ventas no encontrado: {os.path.abspath(VENTAS_EXCEL)}")
        print("         Cuando lo tengas, ajustá VENTAS_EXCEL y volvé a correr.")
        print("         Los CSVs de clima, calendario y macro ya quedaron guardados.")
        return

    print(f"  Leyendo: {os.path.abspath(VENTAS_EXCEL)}")

    xl = pd.ExcelFile(VENTAS_EXCEL)
    print(f"  Pestañas encontradas: {xl.sheet_names}")

    columnas_utiles = ["anio", "mes", "canal", "categoria", "sku",
                       "descripcion", "empresa", "marca",
                       "familia", "departamento",
                       "unidades_vendidas", "monto_facturado"]

    hojas = []
    for sheet in xl.sheet_names:
        try:
            hoja = pd.read_excel(VENTAS_EXCEL, sheet_name=sheet, header=1)
            hoja.columns = [normalizar_columna(c) for c in hoja.columns]
            hoja = hoja.loc[:, ~hoja.columns.duplicated()]
            hoja = hoja[[c for c in columnas_utiles if c in hoja.columns]]
            hoja = hoja.dropna(subset=["anio", "mes"])
            hoja["anio"] = pd.to_numeric(hoja["anio"], errors="coerce")
            hoja["mes"]  = pd.to_numeric(hoja["mes"],  errors="coerce")
            hoja = hoja.dropna(subset=["anio", "mes"])
            hoja["anio"] = hoja["anio"].astype(int)
            hoja["mes"]  = hoja["mes"].astype(int)
            hojas.append(hoja)
            print(f"  [OK] Pestaña '{sheet}': {len(hoja):,} filas")
        except Exception as e:
            print(f"  [SKIP] Pestaña '{sheet}': {e}")

    if not hojas:
        print("  [ERROR] No se pudo leer ninguna pestaña.")
        return

    df = pd.concat(hojas, ignore_index=True)
    print(f"  Total combinado: {len(df):,} filas")

    df["unidades_vendidas"] = pd.to_numeric(df["unidades_vendidas"], errors="coerce")
    df["monto_facturado"]   = pd.to_numeric(df["monto_facturado"],   errors="coerce")
    df = df.dropna(subset=["unidades_vendidas", "monto_facturado"])
    filas_antes = len(df)
    df = df[df["unidades_vendidas"] > 0].copy()
    if len(df) < filas_antes:
        print(f"  [INFO] Se eliminaron {filas_antes - len(df)} filas con unidades_vendidas = 0")

    filas_antes = len(df)
    df = df.dropna(subset=CLAVE_SERIE).copy()
    if len(df) < filas_antes:
        print(f"  [INFO] Se eliminaron {filas_antes - len(df)} filas sin SKU, marca o empresa")
    df["sku"] = df["sku"].map(normalizar_sku)
    for col in ("marca", "empresa"):
        df[col] = df[col].astype(str).str.strip()
    filas_antes = len(df)
    df = agregar_por_mes(df)
    print(f"  [INFO] Agregado por {' + '.join(CLAVE_SERIE + ['anio', 'mes'])}: "
          f"{filas_antes:,} filas → {len(df):,} filas")

    df["precio_unitario"] = (df["monto_facturado"] / df["unidades_vendidas"]).round(2)

    df = df.sort_values(CLAVE_SERIE + ["anio", "mes"])
    df = agregar_rezagos(df)

    total_cat = df.groupby(["anio","mes","categoria"])["unidades_vendidas"].transform("sum")
    df["market_share_unidades"] = (df["unidades_vendidas"] / total_cat).round(4)
    df["market_share_unidades"] = df.groupby(CLAVE_SERIE)["market_share_unidades"].shift(1)

    precio_cat = df.groupby(["anio","mes","categoria"])["precio_unitario"].transform("mean")
    df["price_gap_pct"] = ((df["precio_unitario"] - precio_cat) / precio_cat * 100).round(2)
    df["price_gap_pct"] = df.groupby(CLAVE_SERIE)["price_gap_pct"].shift(1)

    if not df_clima.empty:
        df = df.merge(
            df_clima[["anio","mes","temp_max_promedio","temp_media_promedio","precipitacion_mm"]],
            on=["anio","mes"], how="left"
        )
    if not df_cal.empty:
        df = df.merge(df_cal, on=["anio","mes"], how="left")
    if not df_macro.empty:
        df = df.merge(df_macro, on=["anio","mes"], how="left")

    save_csv(df, "dataset_enriquecido")

    os.makedirs(CSV_OUTPUT_DIR, exist_ok=True)
    excel_path = os.path.join(CSV_OUTPUT_DIR, "dataset_enriquecido.xlsx")
    anios = sorted(df["anio"].unique())
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        for anio in anios:
            hoja = df[df["anio"] == anio].sort_values(["mes", "categoria", "sku"])
            hoja.to_excel(writer, sheet_name=str(anio), index=False)
            print(f"  [OK] Pestaña {anio}: {len(hoja):,} filas")
    print(f"  [OK] Excel guardado en: {os.path.abspath(excel_path)}")

    print(f"\n  Filas totales: {len(df):,}")
    print(f"  Columnas:      {len(df.columns)}")
    print(f"  Años:          {anios}")
    print(f"  {list(df.columns)}")

def main():
    print("=" * 60)
    print("  Pipeline variables externas — Paraguay")
    print(f"  Rango: {START_DATE} → {END_DATE}")
    print(f"  Salida: {os.path.abspath(CSV_OUTPUT_DIR)}")
    print("=" * 60)

    df_macro = generar_macroeconomico()
    df_clima  = generar_clima()
    df_cal    = generar_calendario()

    generar_dataset_enriquecido(df_macro, df_clima, df_cal)

    print("\n✓ Listo. Revisá la carpeta output_csv/")

if __name__ == "__main__":
    main()
