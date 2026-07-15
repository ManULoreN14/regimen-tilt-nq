import json
import pandas as pd
import os

# Ruta ajustada al nuevo nombre de archivo
archivo = r"C:\Users\m21lo\Desktop\FUND_FLOWS.txt"
resultado = r"C:\Users\m21lo\Desktop\resultado_flujos.csv"

def procesar():
    if not os.path.exists(archivo):
        print(f"ERROR: No encuentro el archivo en {archivo}")
        return

    try:
        with open(archivo, 'r', encoding='utf-8') as f:
            datos = json.load(f)
            
        # Extraemos la lista
        lista = datos['data']['fundFlowsData']['data']
        df = pd.DataFrame(lista)
        
        # Procesamiento de columnas
        df['Signo'] = df['fundFlows'].apply(lambda x: 'Entrada' if x > 0 else 'Salida')
        
        # Selección y orden de columnas para tu panel
        cols = ['navDate', 'Signo', 'fundFlows', 'nav', 'navChangePercent', 'aum']
        df_final = df[cols].rename(columns={
            'navDate': 'Fecha',
            'fundFlows': 'Cantidad_USD',
            'nav': 'NAV',
            'navChangePercent': 'Cambio_%',
            'aum': 'AUM'
        })
        
        # Orden cronológico
        df_final = df_final.sort_values(by='Fecha')
        
        # Guardar
        df_final.to_csv(resultado, index=False, encoding='utf-8')
        print(f"¡Éxito! CSV generado en: {resultado}")
            
    except KeyError as e:
        print(f"Error de estructura JSON. No encuentro la ruta: {e}")
    except json.JSONDecodeError:
        print("Error: El archivo no es un JSON válido. Verifica las llaves { } al inicio y final.")
    except Exception as e:
        print(f"Error inesperado: {e}")

if __name__ == "__main__":
    procesar()