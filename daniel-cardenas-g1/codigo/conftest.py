"""Root conftest — asegura que `codigo/` esté en sys.path para imports absolutos.

Este archivo es cargado automáticamente por pytest antes de recolectar tests.
También permite ejecutar módulos directamente (python main.py) añadiendo
el directorio padre a sys.path.
"""

import sys
import os

# Añadir el directorio codigo/ a sys.path para que los imports absolutos funcionen.
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)
