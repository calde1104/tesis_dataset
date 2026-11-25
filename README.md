# Dataset de ventas y variables externas

Ventas mensuales por producto (2021–2025) cruzadas con variables externas de Paraguay.


## Contenido

| Archivo | Descripción |
|---|---|
| `Datos Originales.xlsx` | Ventas, con una pestaña por año |
| `ingest_variables_externas.py` | Descarga las variables externas y genera el dataset enriquecido |
| `output_csv/clima_mensual.csv` | Temperatura y precipitaciones de Asunción |
| `output_csv/calendario_mensual.csv` | Feriados y fechas comerciales |
| `output_csv/macroeconomico_mensual.csv` | Indicadores macroeconómicos |
| `output_csv/dataset_enriquecido.zip` | Ventas combinadas con las variables externas |
| `requirements.txt` | Dependencias de Python |

## Uso

Requiere Python 3.10 o superior.

```bash
pip install -r requirements.txt
python ingest_variables_externas.py
```
