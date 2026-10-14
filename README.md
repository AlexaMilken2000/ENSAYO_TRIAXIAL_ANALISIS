# Ensayo Triaxial CD / CU

Aplicación de escritorio para Windows para analizar ensayos triaxiales. El
proyecto incluye el código fuente, las imágenes de la interfaz y la
configuración necesaria para generar un ejecutable.

## Probar la aplicación

Extraiga la carpeta completa y ejecute `dist\EnsayoTriaxial\EnsayoTriaxial.exe`.
La carpeta contiene Python y las dependencias; no requiere instalar Python,
MiKTeX ni TeX Live en la computadora donde se ejecuta. No mueva el `.exe`
fuera de esa carpeta. La computadora de destino debe usar Windows compatible
con aplicaciones x64.

La distribución usa el formato de carpeta de PyInstaller y no aplica UPX.
Esto evita el empaquetado comprimido de un solo archivo, que puede activar
heurísticas de algunos antivirus, pero no garantiza que todos los motores
reconozcan el programa como seguro.

## Compilar en Windows

1. Instale Python 3.9 o posterior para Windows desde
   <https://www.python.org/downloads/windows/>. Durante la instalación,
   incluya Tcl/Tk. Para compilar, la computadora necesita conexión a Internet
   para descargar los paquetes de Python.
2. Extraiga la carpeta completa del proyecto, conservando juntos el script,
   las imágenes, `log32.png`, `log32.ico`, `requirements.txt`, `requirements-build.txt`,
   `EnsayoTriaxial.spec` y `build_windows.bat`.
3. Haga doble clic en `build_windows.bat` y espere a que termine.
4. La aplicación compilada se generará en `dist\EnsayoTriaxial\`.
   Para probarla, ejecute `dist\EnsayoTriaxial\EnsayoTriaxial.exe`.

El primer proceso de compilación crea un entorno virtual `.venv` e instala las
dependencias. Para volver a compilar, ejecute el mismo archivo `.bat`.

## Dependencias

Las bibliotecas de ejecución se enumeran en `requirements.txt`. PyInstaller,
utilizado para compilar, está en `requirements-build.txt`. El reporte PDF se
genera con ReportLab, por lo que no requiere un compilador LaTeX externo.

## Archivos del proyecto

- `trial2.0.py`: código fuente de la aplicación.
- `img triaxial 1.webp` y `img logo 2.png`: imágenes de la pantalla de inicio.
- `log32.png` y `log32.ico`: imagen original e icono de Windows del ejecutable.
- `EnsayoTriaxial.spec`: configuración de compilación en formato de carpeta,
  sin UPX y con el icono de Windows.
- `build_windows.bat`: crea el entorno de compilación y genera el `.exe`.
