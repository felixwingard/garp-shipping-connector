# -*- coding: utf-8 -*-
"""PyInstaller bootstrap — körs som fristående skript utan relativ import.
Använder absolut import så att src-paketet laddas korrekt."""
from src.main import main

if __name__ == "__main__":
    main()
