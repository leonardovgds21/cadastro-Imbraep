"""Caminhos do app e endereço da plataforma.

Quando roda como executável, os dados ficam ao lado do .exe (dados/), para a
pasta poder ser copiada inteira para outro computador. Os certificados vão
para "certificados_Imbraep" na Área de Trabalho de cada computador.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# IMBRAEP_URL troca o endereço (usado nos testes com o site simulado).
URL_BASE = os.environ.get("IMBRAEP_URL", "https://inbraep.treinamento.online").rstrip("/")
NOME_PASTA_CERTIFICADOS = "certificados_Imbraep"


def pasta_base() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def pasta_dados() -> Path:
    pasta = pasta_base() / "dados"
    pasta.mkdir(exist_ok=True)
    return pasta


def area_de_trabalho() -> Path:
    """A Área de Trabalho de verdade do Windows (pode estar dentro do OneDrive)."""
    if sys.platform == "win32":
        import ctypes

        caminho = ctypes.create_unicode_buffer(260)
        # CSIDL_DESKTOPDIRECTORY = 0x10: segue o redirecionamento do OneDrive
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, caminho) == 0 and caminho.value:
            return Path(caminho.value)
    return Path.home() / "Desktop"


def pasta_certificados() -> Path:
    destino = os.environ.get("IMBRAEP_CERTIFICADOS")  # só para os testes
    pasta = Path(destino) if destino else area_de_trabalho() / NOME_PASTA_CERTIFICADOS
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def pasta_downloads() -> Path:
    """Pasta temporária dos downloads do navegador, fora do OneDrive (que mexe
    nos arquivos enquanto eles são gravados)."""
    pasta = Path(tempfile.gettempdir()) / "CadastroImbraep" / "downloads"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta
