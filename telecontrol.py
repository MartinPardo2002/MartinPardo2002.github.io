# -*- coding: utf-8 -*-
"""
Created on Mon Sep 15 12:10:20 2025

@author: D049274
"""

import re
import shutil
import pyodbc
import pandas as pd
from pathlib import Path
from colorama import init, Back
from datetime import datetime, timedelta
import pytz
import math

init(autoreset=True)

# --------------------------------
ZONA_LOCAL = pytz.timezone("Europe/Madrid")

CARPETA_DESTINO = Path(r'\\10.253.128.201\g01242020011\Nuevo OM\300 desarrollos plataformas TIC\306.00 Simulador_Practicas\Datos\Historico')

CONN_BBDD = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=192.168.10.184,7433;"
    "DATABASE=SIMULADOR_PRACTICAS;"
    "UID=UsrTelecontrol;"
    "PWD=*1T3l3control2*;"
    "Trusted_Connection=no;"
    "LANGUAGE=Spanish;"
)
# --------------------------------

def conectar_sqlserver():
    return pyodbc.connect(CONN_BBDD)


def obtener_carpeta_origen(conn) -> Path:
    cursor = conn.cursor()
    cursor.execute("SELECT carpeta FROM FUENTES WHERE codigo = 1")
    resultado = cursor.fetchone()
    
    if not resultado:
        raise ValueError("No se encontró registro en FUENTES con código 1")
        
    return Path(str(resultado[0]).strip())


def normalize_id(x): #  normalizar ValueID para que coincida con codigotelecontrol.
    if x is None:
        return ""
    
    s = str(x).strip()
    
    if s == "" or s.lower() in ("nan", "none"):
        return ""
    
    try:
        f = float(s)
        if math.isfinite(f):
            if f.is_integer():
                return str(int(f))
            else:
                return ('%f' % f).rstrip('0').rstrip('.')
    except Exception:
        pass
    
    return s


def obtener_codigos_senales(conn) -> dict:
    cursor = conn.cursor()
    cursor.execute("SELECT codigotelecontrol, codigo FROM SEÑALES")
    resultado = cursor.fetchall()
    
    if not resultado:
        raise ValueError("No se encontró ningún registro en la tabla SEÑALES")
        
    return {normalize_id(r[0]): r[1] for r in resultado}


def leer_fichero(fichero: Path) -> pd.DataFrame:
    if fichero.suffix.lower() == ".csv":
        df = pd.read_csv(fichero, sep=';', on_bad_lines='skip', encoding='utf-8')
    else:
        df = pd.read_excel(fichero)

    columnas = ["ValueID", "Timestamp", "RealValue"]
    
    if not all(col in df.columns for col in columnas):
        raise ValueError(f"{Back.RED}Fichero {fichero.name} no tiene columnas necesarias: {columnas}{Back.RESET}")

    df = df[columnas].copy()
    df["ValueID"] = df["ValueID"].apply(normalize_id)
    df["RealValue"] = df["RealValue"].astype(str).str.replace(',', '.')
    df["RealValue"] = pd.to_numeric(df["RealValue"], errors='coerce')
    
    
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], dayfirst=True, errors='coerce')
    df["Timestamp"] = df["Timestamp"] + pd.Timedelta(hours=2)
    df = df.dropna(subset=["Timestamp", "RealValue"]) 
    df["Timestamp"] = df["Timestamp"].dt.floor('min')
    df["Timestamp"] = df["Timestamp"].dt.tz_localize('UTC')
    df["FECHAHORA"] = df["Timestamp"].dt.tz_convert(ZONA_LOCAL)

    return df[["ValueID", "FECHAHORA", "RealValue"]].rename(columns={"RealValue": "VALOR"})


def extraer_hora_fichero(nombre: str) -> datetime:
    patron = r"(\d{2})_(\d{2})_(\d{4})_(\d{2})_(\d{2})_(\d{2})"
    m = re.search(patron, nombre)
    
    if not m:
        raise ValueError(f"{Back.RED}No se pudo extraer fecha de {nombre}{Back.RESET}")
    dia, mes, año, hora, minuto, segundo = map(int, m.groups())
    
    return ZONA_LOCAL.localize(datetime(año, mes, dia, hora, minuto, segundo))


def buscar_fichero_prev(carpeta: Path, fichero: Path) -> pd.DataFrame:
    ficheros = sorted(
        [f for f in carpeta.glob("*") if f.suffix.lower() in [".csv", ".xlsx"]],
        key=lambda f: extraer_hora_fichero(f.name)
    )
    
    try:
        idx = ficheros.index(fichero)
    except ValueError:
        return pd.DataFrame()
    
    if idx == 0:
        return pd.DataFrame()

    try:
        return leer_fichero(ficheros[idx - 1])
    except Exception as e:
        print(f"{Back.RED}No se pudo leer fichero previo {ficheros[idx - 1].name}: {e}{Back.RESET}")
        return pd.DataFrame()


def insertar_filas_nuevas(conn, df_actual: pd.DataFrame, df_prev: pd.DataFrame, mapa_codigos: dict):
    if df_prev.empty:
        df_nuevas = df_actual.copy()
    else:
        merged = df_actual.merge(df_prev, on=["ValueID", "FECHAHORA", "VALOR"], how="left", indicator=True)
        df_nuevas = merged[merged["_merge"] == "left_only"].drop(columns=["_merge"])
        df_nuevas = df_nuevas[df_actual.columns]

    if df_nuevas.empty:
        print("No hay filas nuevas para insertar.")
        return

    df_nuevas = df_nuevas.drop_duplicates(subset=["ValueID", "FECHAHORA"], keep='first')
   
    cursor = conn.cursor()
    insertadas = 0
    
    for _, row in df_nuevas.iterrows():
        valueid = row["ValueID"]
        if valueid not in mapa_codigos:
            print(f"Advertencia: ValueID '{valueid}' no encontrado en SEÑALES. Fila omitida.")
            continue
        
        try:
            fecha_sin_microsegundos = row["FECHAHORA"].replace(second=0).to_pydatetime()
            if fecha_sin_microsegundos.tzinfo is not None:
                fecha_sin_microsegundos = fecha_sin_microsegundos.astimezone(pytz.UTC).replace(tzinfo=None)
            fecha_str = fecha_sin_microsegundos.strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "INSERT INTO VALORES (codseñal, fechahora, valor) VALUES (?, ?, ?)",
                mapa_codigos[valueid],
                fecha_str,
                row["VALOR"]
            )
            insertadas += 1
            
        except pyodbc.Error as e:
            print(f"{Back.RED}Error DB al insertar ValueID {valueid}: {e}{Back.RESET}")
            
    conn.commit()
    print(f"Insertadas {insertadas} filas nuevas.")


def copiar_fichero(fichero: Path, destino: Path):
    destino.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fichero, destino / fichero.name)


def eliminar_antiguos(carpeta: Path, horas: int):
    limite = datetime.now(tz=ZONA_LOCAL) - timedelta(hours=horas)
    contador = 0
    
    for fichero in carpeta.glob("*"):
        if fichero.is_file():            
            try:
                if extraer_hora_fichero(fichero.name) < limite:
                    fichero.unlink()
                    contador += 1
                    
            except Exception as e:
                print(f"No se pudo eliminar {fichero.name}: {e}")
                
    print(f"\nSe han eliminado {contador} ficheros antiguos de la carpeta {carpeta.name}.")


def main():
    conn = conectar_sqlserver()
    mapa_codigos = obtener_codigos_senales(conn)

    CARPETA_ORIGEN = obtener_carpeta_origen(conn)

    for fichero in CARPETA_ORIGEN.glob("*"):
        if fichero.suffix.lower() not in [".csv", ".xlsx"] or (CARPETA_DESTINO / fichero.name).exists():
            print(f"El fichero {fichero.name} ya está procesado.")
            continue 
           
        try:
            print(f"\nProcesando {fichero.name}")
            df_actual = leer_fichero(fichero)
            df_prev = buscar_fichero_prev(CARPETA_ORIGEN, fichero)
            insertar_filas_nuevas(conn, df_actual, df_prev, mapa_codigos)
            copiar_fichero(fichero, CARPETA_DESTINO) 

           
        except Exception as e:
            print(f"{Back.RED}Error con {fichero.name}: {e}{Back.RESET}")
            
    eliminar_antiguos(CARPETA_ORIGEN, horas=3)
    conn.close()


if __name__ == "__main__":
    main()

