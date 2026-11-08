"""Avvio di Clonaut nell'AppImage, eseguito dall'AppRun con il Python incluso.

NON `python3 -m clonaut`: con -m Python mette la cartella corrente in
sys.path[0], davanti a tutto, e un json.py (o un checkout di clonaut/) nella
cartella di avvio verrebbe importato al posto dei moduli veri. Eseguendo uno
script, sys.path[0] è la cartella dello script: usr/share/clonaut.
"""
import sys

from clonaut.app import main

sys.exit(main())
