# -*- coding: utf-8 -*-
"""
Created on Fri Oct  3 11:02:50 2025

@author: d049274
"""

import pandas as pd
from sqlalchemy import create_engine, text
from colorama import init, Back
from datetime import datetime  # Importado para el manejo explícito de fechas
import warnings
warnings.filterwarnings('ignore')

init(autoreset=True)

CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=192.168.10.184,7433;"
    "DATABASE=SIMULADOR_PRACTICAS;"
    "UID=UsrTelecontrol;"
    "PWD=*1T3l3control2*;"
    "Trusted_Connection=no;"
    "LANGUAGE=Spanish;"
)

def configurar_conexion():
    engine = create_engine(f"mssql+pyodbc:///?odbc_connect={CONN_STR}")
    
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        raise Exception(f"Error en conexión: {str(e)}")
    
    return engine

def leer_hoja(ruta_excel, nombre_hoja):
    try:
        df = pd.read_excel(
            ruta_excel, 
            sheet_name=nombre_hoja, 
            engine='openpyxl',
            header=5,
            skiprows=0
        )
        df = df.dropna(how='all')
        print(f"\nLeída hoja '{nombre_hoja}' con {len(df)} filas.")
        return df
    except Exception as e:
        raise Exception(f"Error al leer hoja '{nombre_hoja}': {str(e)}")

def procesar_hoja(df, codigo_senal):
    df.columns = [col.strip().upper() if isinstance(col, str) else col for col in df.columns]
    
    rename_principal = {
        'FECHA HORA INICIO': 'FECHAINICIOBASEFORM',
        'FECHA HORA FIN': 'FECHAFINBASEFORM',
        'EPISODIO': 'EPISODIOBASEFORM',
        'TIEMPO VERTIDO (HH:MM)': 'TIEMPOVERTIDOBASEFORM',
        'TIEMPO DURACION EVENTO (HH:MM)': 'TIEMPODURACIONEVENTOBASEFORM'
    }
    df = df.rename(columns=rename_principal)
    
    if 'LLUVIA' in df.columns:
        df = df.drop(columns=['LLUVIA'])
    
    rename_lluvia = {}
    if 'LLUVIA.1' in df.columns:
        rename_lluvia['LLUVIA.1'] = 'LLUVIABASEFORM'
    if 'LLUVIA 24H' in df.columns:
        rename_lluvia['LLUVIA 24H'] = 'LLUVIA24HBASEFORM'
    if 'LLUVIA 48H' in df.columns:
        rename_lluvia['LLUVIA 48H'] = 'LLUVIA48HBASEFORM'
    
    df = df.rename(columns=rename_lluvia)

    
    for col in ['TIEMPOVERTIDOBASEFORM', 'TIEMPODURACIONEVENTOBASEFORM']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
            df[col] = df[col].apply(
                lambda x: x + ':00' if isinstance(x, str) and len(x.split(':')) == 2 else x
            )
    
    for col in ['LLUVIABASEFORM', 'LLUVIA24HBASEFORM', 'LLUVIA48HBASEFORM']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace(',', '.').str.strip()
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
    df['CODSEÑALSIMUL'] = codigo_senal
    
    # Eliminar filas sin fecha de inicio válida
    df = df.dropna(subset=['FECHAINICIOBASEFORM'])
    
    # Seleccionar solo las columnas relevantes (si existen)
    columnas_tabla = [
        'FECHAINICIOBASEFORM', 'FECHAFINBASEFORM', 'EPISODIOBASEFORM', 'CODSEÑALSIMUL',
        'TIEMPOVERTIDOBASEFORM', 'TIEMPODURACIONEVENTOBASEFORM', 'LLUVIABASEFORM',
        'LLUVIA24HBASEFORM', 'LLUVIA48HBASEFORM'
    ]
    df = df[[col for col in columnas_tabla if col in df.columns]]
    
    return df

def insertar_datos(df, engine, nombre_tabla='ALIVIOS_BASEFORM', schema='dbo'):
    if df.empty:
        print("No hay datos para insertar.")
        return 0
    
    try:
        df.to_sql(
            name=nombre_tabla,
            schema=schema,
            con=engine,
            if_exists='append',
            index=False,
            chunksize=1000,
            method='multi'
        )
        return len(df)
    except Exception as e:
        raise Exception(f"\n{Back.RED}Error al insertar datos{Back.RESET}: {str(e)}")

def importar_todas_hojas(ruta_excel, mapeo_hojas):
    total_insertadas = 0
    
    engine = configurar_conexion()
        
    lista_dfs = []
    for nombre_hoja, codigo_senal in mapeo_hojas.items():
        try:
            df = leer_hoja(ruta_excel, nombre_hoja)
            
            df_procesado = procesar_hoja(df, codigo_senal)
            
            if df_procesado.empty:
                print(f"\n{Back.RED}No hay datos válidos en '{nombre_hoja}{Back.RESET}'. Saltando.")
                continue
            
            lista_dfs.append(df_procesado)
            print(f"Datos de '{nombre_hoja}' agregados a la lista (temporal: {len(df_procesado)} filas).")
            
        except Exception as e:
            print(f"\n{Back.RED}Error en hoja '{nombre_hoja}{Back.RESET}': {str(e)}")
            continue
    
    if lista_dfs:
        df_total = pd.concat(lista_dfs, ignore_index=True)
        
        with engine.connect() as conn:
            result = conn.execute(text("SELECT ISNULL(MAX(codigo), 0) FROM dbo.ALIVIOS_BASEFORM"))
            max_codigo_existente = result.scalar()
        
        inicio_codigo = max_codigo_existente + 1
        df_total['codigo'] = range(inicio_codigo, inicio_codigo + len(df_total))        
        
        insertadas = insertar_datos(df_total, engine, nombre_tabla='ALIVIOS_BASEFORM', schema='dbo')
        total_insertadas = insertadas
    else:
        print("No hay datos válidos para insertar en ninguna hoja.")
    
    engine.dispose()
    print(f"\nTotal de filas insertadas: {total_insertadas}.")

if __name__ == "__main__":
    ruta_excel = r'\\10.253.128.201\g01242020011\Nuevo OM\300 desarrollos plataformas TIC\306.00 Simulador_Practicas\Datos\AliviosBaseform\Informe Alivios_2T 2025_TAFALLA-OLITE.xlsx'    
    
    mapeo_hojas = {
        'Caudal Aliv Ent': 8,
        'Aliv general Sofrel': 25,
        'Alivio Venecia -  Aliv Sofrel': 26,
        'CAMINEROS - Aliv Sofrel': 29
    }
    
    importar_todas_hojas(ruta_excel, mapeo_hojas)