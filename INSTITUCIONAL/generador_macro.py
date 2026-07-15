import pandas as pd
import os

# Ruta de tu carpeta de datos
ruta_base = r"C:\Users\m21lo\regimen-tilt-nq\INSTITUCIONAL"

def cargar_vix(archivo, nombre_columna):
    """Función auxiliar para cargar los históricos de volatilidad del CBOE de forma robusta"""
    ruta = os.path.join(ruta_base, archivo)
    if not os.path.exists(ruta):
        print(f"⚠️ Aviso: No se encontró {archivo}")
        return None
    
    try:
        df = pd.read_csv(ruta)
        
        # 1. Limpiar los nombres de las columnas eliminando espacios en blanco extraños
        df.columns = df.columns.str.strip()
        
        # 2. Identificar la columna de Fecha de forma dinámica
        col_fecha = None
        for col in ['DATE', 'Date', 'Trade Date', 'Trade_Date']:
            if col in df.columns:
                col_fecha = col
                break
        
        # Fallback: asume la primera columna si no encuentra coincidencias típicas
        if col_fecha is None:
            col_fecha = df.columns[0]
            
        df['Fecha'] = pd.to_datetime(df[col_fecha])
        
        # 3. Identificar la columna de Cierre de forma dinámica
        col_cierre = None
        for col in ['CLOSE', 'Close', 'Last', 'PX_LAST']:
            if col in df.columns:
                col_cierre = col
                break
                
        # Fallback: asume la última columna
        if col_cierre is None:
            col_cierre = df.columns[-1]
            
        # Limpiar y renombrar para el cruce
        df_limpio = df[['Fecha', col_cierre]].copy()
        df_limpio = df_limpio.rename(columns={col_cierre: nombre_columna})
        
        return df_limpio
        
    except Exception as e:
        print(f"Error procesando {archivo}: {e}")
        return None

def consolidar():
    print("Iniciando la consolidación de datos Quant...")
    
    # 1. Cargar el ecosistema de Volatilidad
    vix = cargar_vix("VIX_History.csv", "VIX_Close")
    vix9d = cargar_vix("VIX9D_History.csv", "VIX9D_Close")
    vix3m = cargar_vix("VIX3M_History.csv", "VIX3M_Close")
    vvix = cargar_vix("VVIX_History.csv", "VVIX_Close")
    
    # Tomar el VIX general como calendario base
    if vix is not None:
        df_master = vix
    else:
        print("Error: El archivo VIX_History.csv es obligatorio para crear el calendario base.")
        return

    # Unir resto de volatilidades de forma segura
    lista_volatilidad = [vix9d, vix3m, vvix]
    for df in lista_volatilidad:
        if df is not None and 'Fecha' in df.columns:
            df_master = pd.merge(df_master, df, on='Fecha', how='left')

    # 2. Cargar Flujos de Capital (QQQ)
    ruta_flujos = os.path.join(ruta_base, "resultado_flujos.csv")
    if os.path.exists(ruta_flujos):
        try:
            flujos = pd.read_csv(ruta_flujos)
            flujos['Fecha'] = pd.to_datetime(flujos['Fecha'])
            
            # Seleccionar solo lo esencial si existen en el df
            cols_flujos = [c for c in ['Fecha', 'Signo', 'Cantidad_USD', 'NAV', 'Cambio_%', 'AUM'] if c in flujos.columns]
            flujos = flujos[cols_flujos]
            
            df_master = pd.merge(df_master, flujos, on='Fecha', how='left')
        except Exception as e:
            print(f"Error cruzando flujos: {e}")
    else:
        print("⚠️ Aviso: resultado_flujos.csv no encontrado.")

    # 3. Cargar Posicionamiento Institucional (COT Report)
    ruta_cot = os.path.join(ruta_base, "cot_209742_consolidado.txt")
    if os.path.exists(ruta_cot):
        try:
            cot = pd.read_csv(ruta_cot)
            cot['Fecha'] = pd.to_datetime(cot['Report_Date_as_YYYY-MM-DD'])
            cot = cot.drop(columns=['Report_Date_as_YYYY-MM-DD', 'CFTC_Contract_Market_Code'])
            
            df_master = pd.merge(df_master, cot, on='Fecha', how='left')
            
            # Proyectar el dato semanal a los días diarios (Forward Fill)
            cols_cot = [c for c in cot.columns if c != 'Fecha']
            df_master[cols_cot] = df_master[cols_cot].ffill()
        except Exception as e:
            print(f"Error cruzando COT: {e}")
    else:
        print("⚠️ Aviso: cot_209742_consolidado.txt no encontrado.")

    # --- INGENIERÍA DE CARACTERÍSTICAS (Métricas Avanzadas) ---
    print("Calculando ratios de confirmación de sentimiento...")
    
    if 'VIX9D_Close' in df_master.columns and 'VIX_Close' in df_master.columns:
        df_master['Pánico_Corto_Plazo'] = df_master['VIX9D_Close'] / df_master['VIX_Close']
        
    if 'VIX_Close' in df_master.columns and 'VIX3M_Close' in df_master.columns:
        df_master['Estructura_VIX_3M'] = df_master['VIX_Close'] / df_master['VIX3M_Close']
        
    if 'VVIX_Close' in df_master.columns and 'VIX_Close' in df_master.columns:
        df_master['Spread_VVIX_VIX'] = df_master['VVIX_Close'] - df_master['VIX_Close']

    # Exportar dataset unificado
    df_master = df_master.sort_values('Fecha').dropna(subset=['VIX_Close'])
    ruta_salida = os.path.join(ruta_base, "macro_quant_master.csv")
    df_master.to_csv(ruta_salida, index=False, encoding='utf-8')
    
    print(f"\n✅ Operación completada con éxito.")
    print(f"Dataset maestro listo en: {ruta_salida}")

if __name__ == "__main__":
    consolidar()