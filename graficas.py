# -*- coding: utf-8 -*-
"""
Created on Mon Oct 13 11:32:47 2025

@author: d049274
"""

from flask import Flask, render_template, request
from sqlalchemy import create_engine, text
import pandas as pd
import plotly.graph_objects as go
from colorama import Back
import plotly
import json
import urllib
from datetime import datetime, timedelta
import logging
import numpy as np
from collections import Counter 
import subprocess 
import sys 

app = Flask(__name__)

CONN_BBDD = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=192.168.10.184,7433;"
    "DATABASE=SIMULADOR_PRACTICAS;"
    "UID=UsrTelecontrol;"
    "PWD=*1T3l3control2*;"
    "Trusted_Connection=no;"
    "LANGUAGE=Spanish;"
)

def conectar_sqlserver():
    params = urllib.parse.quote_plus(CONN_BBDD)
    engine = create_engine(f"mssql+pyodbc:///?odbc_connect={params}")
    return engine

def obtener_localidades(engine):
    query = text("SELECT DISTINCT IdLocalidad, Nombre FROM Depuradoras.dbo.Localidades ORDER BY IdLocalidad")
    try:
        with engine.connect() as conn:
            result = conn.execute(query)
            localidades = [{'id': row[0], 'nombre': row[1]} for row in result]
        return localidades
    except Exception as e:
        print(f"Error al obtener localidades: {e}")
        return []

def obtener_codsenales(engine, codinstalacion=None):
    if codinstalacion:
        query = text("SELECT codigo, descripcion FROM señales WHERE CODINSTALACION = :codinstalacion ORDER BY codigo")
        with engine.connect() as conn:
            result = conn.execute(query, {'codinstalacion': codinstalacion})
            codsenales = [{'codigo': row[0], 'descripcion': row[1]} for row in result]
    else:
        query = text("SELECT codigo, descripcion FROM señales ORDER BY codigo")
        with engine.connect() as conn:
            result = conn.execute(query)
            codsenales = [{'codigo': row[0], 'descripcion': row[1]} for row in result]
    return codsenales 

def obtener_descripcion(engine, codsenal):
    query = text("SELECT descripcion FROM señales WHERE codigo = :codsenal")
    with engine.connect() as conn:
        result = conn.execute(query, {'codsenal': codsenal}).fetchone()
    return result[0] if result else codsenal

def obtener_todos_alivios(engine):
    query = text("""
        SELECT FECHAINICIO, FECHAFIN 
        FROM ALIVIOS_TELECONTROL 
        WHERE FECHAFIN IS NOT NULL  -- Solo alivios completados
        ORDER BY FECHAINICIO
    """)
    try:
        with engine.connect() as conn:
            result = conn.execute(query)
            alivios = [(row[0], row[1]) for row in result if row[0] and row[1]] 
        return alivios
    except Exception as e:
        print(f"Error al obtener alivios: {e}")
        return []

def obtener_alivios_baseform(engine, fecha_inicio, fecha_fin):
    query = text("""
        SELECT FECHAINICIOBASEFORM, FECHAFINBASEFORM 
        FROM dbo.ALIVIOS_BASEFORM 
        WHERE FECHAINICIOBASEFORM BETWEEN :inicio AND :fin 
        ORDER BY FECHAINICIOBASEFORM
    """)
    try:
        with engine.connect() as conn:
            result = conn.execute(query, {'inicio': fecha_inicio, 'fin': fecha_fin})
            alivios = [(row[0], row[1]) for row in result if row[0] and row[1]]
        return alivios
    except Exception as e:
        print(f"Error al obtener alivios de ALIVIOS_BASEFORM: {e}")
        return []

def obtener_datos(engine, codsenal, fecha_inicio_dt, fecha_fin_dt):
    query = text("""
        SELECT fechahora, valor FROM valores
        WHERE codseñal = :codsenal
        AND fechahora BETWEEN :fecha_inicio AND :fecha_fin
        ORDER BY fechahora
    """)
    with engine.connect() as conn:
        df = pd.read_sql_query(query, conn, params={
            'codsenal': codsenal,
            'fecha_inicio': fecha_inicio_dt,  
            'fecha_fin': fecha_fin_dt
        })
    return df

def crear_grafico_estatico(dfs_list, codsenales_list, descripciones_list, todos_alivios, fecha_inicio_grafico=None, fecha_fin_grafico=None):
    if not dfs_list:
        return None

    processed_dfs = []
    all_x_vals = set()  
    colors = ['red', 'blue', 'green', 'orange', 'black', 'cyan', 'magenta', 'lime', 'pink', 'teal']

    for i, df in enumerate(dfs_list):
        if df is None or df.empty:
            continue
        df = df.sort_values('fechahora')
        df['fechahora'] = pd.to_datetime(df['fechahora'])
        x_vals = df['fechahora'].tolist()
        y_vals = df['valor'].tolist()
        processed_dfs.append({'x': x_vals, 'y': y_vals, 'codsenal': codsenales_list[i], 'desc': descripciones_list[i], 'color': colors[i % len(colors)]})
        all_x_vals.update(x_vals)

    if not processed_dfs:
        return None

    fig = go.Figure()

    for pd_df in processed_dfs:
        fig.add_trace(go.Scatter(
            x=pd_df['x'],
            y=pd_df['y'],
            mode='lines',
            line=dict(color=pd_df['color']),
            name=pd_df['desc'],
            showlegend=True,
            legendgroup=pd_df['desc'],  
            hovertemplate='O %{y:.2f}<extra></extra>',
            hoverlabel=dict(  
                bgcolor=pd_df['color'],
                font_color='white', 
                font_size=12,
                font_family='Arial',
                namelength=0
            )
        ))

    all_timestamps = sorted(list(all_x_vals))
    if not all_timestamps:
        return None

    shapes = []
    if todos_alivios:
        for fechainicio_str, fechafin_str in todos_alivios:
            try:
                fechainicio = pd.to_datetime(fechainicio_str).replace(microsecond=0)
                fechafin = pd.to_datetime(fechafin_str).replace(microsecond=0)
                
                if fecha_inicio_grafico and fecha_fin_grafico:
                    if fechafin < fecha_inicio_grafico or fechainicio > fecha_fin_grafico:
                        continue
                
                shapes.append(dict(
                    type="rect",
                    x0=fechainicio,
                    x1=fechafin,
                    yref="paper",
                    y0=0,
                    y1=1,
                    fillcolor="black",
                    opacity=0.4,
                    layer="below",
                    line_width=0,
                    name=f"Alivio {fechainicio.strftime('%d/%m/%Y %H:%M')} - {fechafin.strftime('%d/%m/%Y %H:%M')}"
                ))
            except (ValueError, TypeError):
                continue

    fig.update_layout(
        hovermode='x',
        spikedistance=-1,
        xaxis=dict(
            showspikes=True,
            spikemode='across',
            spikesnap='cursor',
            spikethickness=0.7,
            spikecolor='rgba(0,0,0,0.6)',
            spikedash='solid',
            hoverformat='%d/%m/%Y %H:%M',
            gridcolor='#e0e0e0',
            gridwidth=0.5,
            showline=True,
            linewidth=1,
            linecolor='black',
            showticklabels=True,
            ticks='outside',
            ticklabelposition='outside bottom'
        ),
        yaxis=dict( 
            showspikes=True,
            spikemode='across',
            spikesnap='cursor',
            spikethickness=0.7,
            spikecolor='rgba(0,0,0,0.6)',
            spikedash='solid',
            hoverformat='.2f',
            tickformat='.2f',  
            gridcolor='#e0e0e0',
            gridwidth=0.5,
            showline=True,
            linewidth=1,
            linecolor='black',
            showticklabels=True,
            ticks='outside',
            ticklabelposition='outside left'
        ),
        hoverlabel=dict(
            bgcolor='white',
            font_size=12,
            font_family='Arial',
            namelength=0
        ),
        margin=dict(t=70),
        shapes=shapes,
        plot_bgcolor='white',
        paper_bgcolor='white',
        legend=dict(
            x=0, y=1.073, xanchor='left', yanchor='top',
            orientation='h', itemdoubleclick='toggle'
        )
    )

    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def calcular_estadisticas(df):
    if df is None or df.empty:
        return None
    return {
        'max': df['valor'].max(),
        'min': df['valor'].min(),
        'mean': df['valor'].mean(),
        'count': len(df)
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/medidores', methods=['GET', 'POST'])
def medidores():
    engine = conectar_sqlserver()
    localidades = obtener_localidades(engine)
    id_localidad = request.args.get('id_localidad') if request.method == 'GET' else request.form.get('id_localidad')
    if not id_localidad:  
        id_localidad = None
    selected_nombre = ''
    if id_localidad:
        selected_nombre = next((loc['nombre'] for loc in localidades if str(loc['id']) == str(id_localidad)), '')
    codsenales = obtener_codsenales(engine, id_localidad)
    grafico_json = None
    error_msgs = []  
    valid_dfs = []  
    valid_descripciones = []  
    valid_estadisticas = []  
    selected_codsenales = request.form.getlist('codsenal[]') if request.method == 'POST' else []  
    fecha_inicio_val = request.form.get('fecha_inicio', '') if request.method == 'POST' else ''
    fecha_fin_val = request.form.get('fecha_fin', '') if request.method == 'POST' else ''

    if request.method == 'POST':
        codsenales_list = [c for c in request.form.getlist('codsenal[]') if c]  
        fecha_inicio_str = request.form.get('fecha_inicio')
        fecha_fin_str = request.form.get('fecha_fin')

        counter = Counter(codsenales_list)
        duplicates = [item for item, count in counter.items() if count > 1]
        
        if duplicates:
            duplicados_str = ', '.join(duplicates)
            error_msgs.append(f"Advertencia: Has seleccionado Codseñal '{duplicados_str}' más de una vez")
            codsenales_list = list(set(codsenales_list))

        if codsenales_list and fecha_inicio_str and fecha_fin_str:
            try:
                fecha_inicio = datetime.strptime(fecha_inicio_str, '%d/%m/%Y %H:%M')
                fecha_fin = datetime.strptime(fecha_fin_str, '%d/%m/%Y %H:%M')

                if fecha_fin < fecha_inicio:
                    error_msgs.append("La fecha final no puede ser anterior a la fecha de inicio.")
                else:
                    todos_alivios = obtener_todos_alivios(engine)

                    has_any_data = False
                    valid_codsenales = []  
                    for codsenal in codsenales_list:
                        df = obtener_datos(engine, codsenal, fecha_inicio, fecha_fin)
                        if not df.empty:
                            descripcion = obtener_descripcion(engine, codsenal)
                            valid_dfs.append(df)
                            valid_descripciones.append(descripcion)
                            valid_codsenales.append(codsenal)  
                            valid_estadisticas.append(calcular_estadisticas(df))
                            has_any_data = True
                        else:
                            desc = obtener_descripcion(engine, codsenal)
                            error_msgs.append(f"No hay datos para el codseñal {codsenal}: {desc}")

                    grafico_json = crear_grafico_estatico(
                        valid_dfs, 
                        valid_codsenales, 
                        valid_descripciones, 
                        todos_alivios, 
                        fecha_inicio_grafico=fecha_inicio, 
                        fecha_fin_grafico=fecha_fin
                    )

            except ValueError:
                error_msgs.append("Formato de fecha incorrecto. Use: dd/mm/aaaa hh:mm")

    num_selects = max(1, len(selected_codsenales))

    if fecha_inicio_val:
        try:
            dt = datetime.strptime(fecha_inicio_val, '%d/%m/%Y %H:%M:%S')
            fecha_inicio_val = dt.strftime('%d/%m/%Y %H:%M')
        except ValueError:
            pass  
    if fecha_fin_val:
        try:
            dt = datetime.strptime(fecha_fin_val, '%d/%m/%Y %H:%M:%S')
            fecha_fin_val = dt.strftime('%d/%m/%Y %H:%M')
        except ValueError:
            pass

    return render_template(
        'medidores.html',
        codsenales=codsenales,
        grafico_json=grafico_json,
        error_msgs=error_msgs,
        valid_descripciones=valid_descripciones,
        valid_estadisticas=valid_estadisticas,
        selected_codsenales=selected_codsenales,
        num_selects=num_selects,
        fecha_inicio_val=fecha_inicio_val,
        fecha_fin_val=fecha_fin_val,
        localidades=localidades,
        selected_id_localidad=id_localidad,
        selected_nombre=selected_nombre
    )

@app.route('/alivios', methods=['GET', 'POST'])
def alivios():
    engine = conectar_sqlserver()
    localidades = obtener_localidades(engine)
    id_localidad = request.args.get('id_localidad') if request.method == 'GET' else request.form.get('id_localidad')
    if not id_localidad:
        id_localidad = None
    selected_nombre = ''
    if id_localidad:
        selected_nombre = next((loc['nombre'] for loc in localidades if str(loc['id']) == str(id_localidad)), '')

    grafico_json = None
    selected_periodo = '1mes'  # Default
    if request.method == 'POST':
        periodo = request.form.get('periodo')
        now = datetime.now()
        if periodo == '1mes':
            fecha_inicio = now - timedelta(days=30)
        elif periodo == '3meses':
            fecha_inicio = now - timedelta(days=90)
        elif periodo == '6meses':
            fecha_inicio = now - timedelta(days=180)
        elif periodo == '1ano':
            fecha_inicio = now - timedelta(days=365)
        else:
            fecha_inicio = now - timedelta(days=30)
        selected_periodo = periodo
        
        if id_localidad == '13':
            # Obtener períodos de alivio para los shapes grises
            alivios_periodos = obtener_alivios_baseform(engine, fecha_inicio, now)
            
            # Obtener datos de detalle para la línea del gráfico
            query_detalle = text("""
                SELECT ab.FECHAINICIOBASEFORM as FECHA, abd.VALOR 
                FROM dbo.ALIVIOS_BASEFORM ab 
                JOIN dbo.ALIVIOS_BASEFORM_DETALLE abd ON ab.CODIGO = abd.CODIGOBASEFORM 
                WHERE ab.FECHAINICIOBASEFORM BETWEEN :inicio AND :fin 
                ORDER BY ab.FECHAINICIOBASEFORM
            """)
            try:
                with engine.connect() as conn:
                    df = pd.read_sql_query(query_detalle, conn, params={'inicio': fecha_inicio, 'fin': now})
                if not df.empty:
                    # Crear gráfico con línea de valores y shapes para períodos de alivio
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=df['FECHA'], 
                        y=[-10,10], 
                        mode='lines', 
                        line=dict(color='white')
                    ))
                    
                    # Añadir shapes para períodos de alivio (rectángulos grises)
                    shapes = []
                    for fechainicio, fechafin in alivios_periodos:
                        try:
                            fechainicio_dt = pd.to_datetime(fechainicio)
                            fechafin_dt = pd.to_datetime(fechafin)
                            shapes.append(dict(
                                type="rect",
                                x0=fechainicio_dt,
                                x1=fechafin_dt,
                                yref="paper",
                                y0=0,
                                y1=1,
                                fillcolor="gray",
                                opacity=0.5,
                                layer="below",
                                line_width=0,
                                name=f"Período de Alivio: {fechainicio_dt.strftime('%d/%m/%Y %H:%M')} - {fechafin_dt.strftime('%d/%m/%Y %H:%M')}"
                            ))
                        except (ValueError, TypeError):
                            continue
                    
                    fig.update_layout(
                        xaxis_title='Fecha',
                        yaxis_title='Valor',
                        shapes=shapes,
                        plot_bgcolor='white',
                        paper_bgcolor='white'
                    )
                    grafico_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
            except Exception as e:
                print(f"Error al obtener datos de ALIVIOS_BASEFORM_DETALLE: {e}")
            
    return render_template(
        'alivios.html', 
        grafico_json=grafico_json, 
        selected_periodo=selected_periodo, 
        localidades=localidades, 
        selected_id_localidad=id_localidad, 
        selected_nombre=selected_nombre
    )



if __name__ == '__main__':
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)  
    
    print("---------------------------------------")
    
    # Iniciar el primer subproceso
    proc1 = subprocess.Popen([sys.executable, 'telecontrol.py'])
    print("Iniciando telecontrol.py. Esperando a que termine...")
    proc1.wait()  # Bloquea hasta que telecontrol.py termine
    print("telecontrol.py ha finalizado. (Código de salida: " + str(proc1.returncode) + ")")
    
    # Iniciar el segundo subproceso
    proc2 = subprocess.Popen([sys.executable, 'alivios_telecontrol.py'])
    print("\nIniciando alivios_telecontrol.py. Esperando a que termine...")
    proc2.wait()  # Bloquea hasta que alivios_telecontrol.py termine
    print("alivios_telecontrol.py ha finalizado. (Código de salida: " + str(proc2.returncode) + ")")
    
    print("---------------------------------------")
    print("Abrir app")
    print(f"{Back.GREEN}http://10.242.20.170:5000{Back.RESET}")
    print(f"Para cerrar, pulsa {Back.GREEN}CTRL+C{Back.RESET}")
    print("---------------------------------------")
    
    # Ahora se inicia el servidor Flask
    app.run(host='10.242.20.170', port=5000, debug=False)